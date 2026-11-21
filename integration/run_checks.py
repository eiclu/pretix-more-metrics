#!/usr/bin/env python3
"""
End-to-end test: drives a real pretix (docker compose) through a small ticket sale and checks,
through the Prometheus HTTP API, that the plugin's metrics were scraped with the expected values.

Usage: run_checks.py '<SEED JSON printed by seed.py>'
Only the Python standard library is used.
"""
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PRETIX = "http://localhost:8345"
PROMETHEUS = "http://localhost:9090"

seed = json.loads(sys.argv[1])
ORG, EVENT = seed["organizer"], seed["event"]
EVENT_URL = f"{PRETIX}/{ORG}/{EVENT}/"


class Browser:
    """One shop visitor: own cookie jar (=session) and own client IP (via X-Forwarded-For)."""

    def __init__(self, ip):
        self.ip = ip
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, url, data=None, headers=None):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, headers={"X-Forwarded-For": self.ip, **(headers or {})})
        with self.opener.open(req, timeout=30) as resp:
            return resp.read().decode()

    def cookie(self, name):
        return next((c.value for c in self.jar if c.name == name), None)

    def add_to_cart(self, item, count):
        html = self.request(EVENT_URL)
        token = self.cookie("pretix_csrftoken") or re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)[1]
        result = json.loads(self.request(
            EVENT_URL + "cart/add?ajax=1",
            data={"csrfmiddlewaretoken": token, f"item_{item}": str(count)},
            headers={"X-CSRFToken": token, "X-Requested-With": "XMLHttpRequest"},
        ))
        for _ in range(60):
            if result.get("ready"):
                return result
            time.sleep(0.5)
            result = json.loads(self.request(PRETIX + result["check_url"]))
        raise AssertionError(f"add to cart did not finish: {result}")


def api(method, path, payload=None):
    req = urllib.request.Request(
        f"{PRETIX}/api/v1/organizers/{ORG}/events/{EVENT}/{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"Authorization": f"Token {seed['token']}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as e:
        raise AssertionError(f"API {method} {path} failed: {e.code} {e.read().decode()}")


def query(promql):
    url = f"{PROMETHEUS}/api/v1/query?" + urllib.parse.urlencode({"query": promql})
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    assert data["status"] == "success", data
    return [float(r["value"][1]) for r in data["data"]["result"]]


def generate_traffic():
    print("== Generating traffic")
    # 20 visitors who only look at the shop
    for i in range(20):
        Browser(f"198.51.100.{i + 1}").request(EVENT_URL)

    # 3 students put a ticket in their cart, quota "[A] TU Studierende" has 5
    for i in range(3):
        result = Browser(f"203.0.113.{i + 1}").add_to_cart(seed["students_item"], 1)
        assert result.get("success", True), result
    # one more wants 4, only 2 are left: pretix puts the 2 into the cart and reports "in_part_listed"
    result = Browser("203.0.113.99").add_to_cart(seed["students_item"], 4)
    print("   sold-out attempt:", result.get("message"))

    # 3 orders via the REST API on "[A] Große Ballkarten" (size 50), one gets paid
    codes = []
    for i in range(3):
        order = api("POST", "orders/", {
            "email": f"guest{i}@example.org", "locale": "de", "sales_channel": "web",
            "positions": [{"item": seed["big_item"], "attendee_name_parts": {"full_name": f"Guest {i}"}}],
        })
        codes.append(order["code"])
    api("POST", f"orders/{codes[0]}/mark_paid/")
    print("   orders:", codes)


SEL = f'organizer="{ORG}",event="{EVENT}"'
STUDENTS = f'{SEL},quota="[A] TU Studierende"'
BIG = f'{SEL},quota="[A] Große Ballkarten"'

CHECKS = [
    # (description, PromQL, predicate on the list of values)
    ("pretix is scraped", 'up{job="pretix"}', lambda v: v == [1]),
    ("plugin info", "pretix_more_metrics_info", lambda v: v == [1]),
    ("all collectors up", "min(pretix_more_metrics_collector_up)", lambda v: v == [1]),
    ("all 7 collectors present", "count(pretix_more_metrics_collector_up)", lambda v: v == [7]),
    # quotas
    ("quota size", f"pretix_quota_size{{{STUDENTS}}}", lambda v: v == [5]),
    ("quota carts", f'pretix_quota_used{{{STUDENTS},kind="cart"}}', lambda v: v == [5]),
    ("quota available", f"pretix_quota_available{{{STUDENTS}}}", lambda v: v == [0]),
    ("quota sold out state", f"pretix_quota_availability_state{{{STUDENTS}}}", lambda v: v == [20]),
    ("quota available %", f"pretix_quota_available{{{BIG}}} / pretix_quota_size{{{BIG}}}",
     lambda v: v == [0.94]),
    ("big quota pending", f'pretix_quota_used{{{BIG},kind="pending"}}', lambda v: v == [2]),
    ("big quota paid", f'pretix_quota_used{{{BIG},kind="paid"}}', lambda v: v == [1]),
    ("big quota available", f"pretix_quota_available{{{BIG}}}", lambda v: v == [47]),
    # shop
    ("active cart positions", f"pretix_cart_positions_active{{{SEL}}}", lambda v: v == [5]),
    ("orders pending", f'pretix_orders{{{SEL},status="n"}}', lambda v: v == [2]),
    ("orders paid", f'pretix_orders{{{SEL},status="p"}}', lambda v: v == [1]),
    ("orders placed counter", f'sum(pretix_orders_placed_total{{{SEL},sales_channel="web"}})', lambda v: v == [3]),
    ("positions placed counter", f"sum(pretix_order_positions_placed_total{{{SEL}}})", lambda v: v == [3]),
    ("orders paid counter", f"pretix_orders_paid_total{{{SEL}}}", lambda v: v == [1]),
    ("sold-out cart error", 'pretix_shop_task_errors_total{task="add_items_to_cart",reason="in_part_listed"}',
     lambda v: v == [1]),
    # pretix's built-in metrics still there
    ("built-in: carts filled", 'pretix_task_runs_total{task_name="pretix.base.services.cart.add_items_to_cart",'
                               'status="success"}', lambda v: v == [3]),
    ("built-in: view histogram", "sum(pretix_view_duration_seconds_count)", lambda v: v and v[0] > 0),
    ("built-in: queues", "count(pretix_celery_tasks_queued_count)", lambda v: v == [5]),
    # visitors: 20 lookers + 4 cart users (HyperLogLog is ~1% off, exact for small sets in practice)
    ("unique visitors by IP", 'pretix_unique_visitors{by="ip",window="5m"}', lambda v: v and 23 <= v[0] <= 25),
    ("unique visitors by session", 'pretix_unique_visitors{by="session",window="5m"}', lambda v: v == [4]),
    ("in flight back to 0", "pretix_http_requests_in_flight", lambda v: v == [0]),
    # infrastructure
    ("postgres connections", "sum(pretix_db_connections)", lambda v: v and v[0] >= 1),
    ("postgres max connections", "pretix_db_max_connections", lambda v: v and v[0] > 0),
    ("redis commands/s", "rate(pretix_redis_commands_processed_total[30s])", lambda v: v and v[0] > 0),
    ("redis clients", "pretix_redis_connected_clients", lambda v: v and v[0] > 0),
    ("host cpu", '1 - sum(rate(pretix_host_cpu_seconds_total{mode=~"idle|iowait"}[30s])) / max(pretix_host_cpus)',
     lambda v: v and 0 <= v[0] <= 1),
    ("host memory", "1 - pretix_host_memory_available_bytes / pretix_host_memory_total_bytes",
     lambda v: v and 0 < v[0] < 1),
]


def run_checks(timeout=90):
    print("== Checking metrics in Prometheus")
    pending = list(CHECKS)
    last = {}
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        still = []
        for desc, promql, pred in pending:
            values = query(promql)
            last[desc] = values
            if pred(values):
                print(f"   ok    {desc}: {values}")
            else:
                still.append((desc, promql, pred))
        pending = still
        if pending:
            time.sleep(5)
    for desc, promql, _ in pending:
        print(f"   FAIL  {desc}: {promql} -> {last.get(desc)}")
    return not pending


if __name__ == "__main__":
    generate_traffic()
    ok = run_checks()
    sys.exit(0 if ok else 1)
