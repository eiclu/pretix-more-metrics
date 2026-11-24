import os

import pytest

from pretix_more_metrics import requests, visitors


def environ(path="/htu/tuball/", ip="203.0.113.5", session=None, method="GET", xff=None):
    env = {"PATH_INFO": path, "REMOTE_ADDR": ip, "REQUEST_METHOD": method}
    if session:
        env["HTTP_COOKIE"] = f"pretix_csrftoken=x; pretix_session={session}"
    if xff:
        env["HTTP_X_FORWARDED_FOR"] = xff
    return env


def visitor_counts():
    return {(lbl["by"], lbl["window"]): v for _, lbl, v in visitors.collect_visitors()}


def in_flight():
    return requests.collect_in_flight()[0][2]


def test_in_flight(redis):
    requests.on_request_started(environ())
    assert in_flight() == 1
    requests.on_request_finished()
    assert in_flight() == 0


def test_in_flight_ignores_metrics_endpoint(redis):
    requests.on_request_started(environ(path="/metrics"))
    assert in_flight() == 0
    requests.on_request_finished()
    assert in_flight() == 0


def test_in_flight_drops_dead_processes(redis):
    redis.hset(requests.IN_FLIGHT_KEY, 2 ** 22 + 12345, 5)  # beyond pid_max, can not exist
    redis.hset(requests.IN_FLIGHT_KEY, os.getpid(), 2)
    assert in_flight() == 2
    assert redis.hlen(requests.IN_FLIGHT_KEY) == 1


def test_unique_visitors_by_ip_and_session(redis):
    requests.on_request_started(environ(ip="203.0.113.5", session="s1"))
    requests.on_request_started(environ(ip="203.0.113.5", session="s2"))
    requests.on_request_started(environ(ip="203.0.113.6"))
    requests.on_request_started(environ(ip="203.0.113.7", path="/control/"))
    requests.on_request_started(environ(ip="203.0.113.8", path="/api/v1/"))
    counts = visitor_counts()
    assert counts[("ip", "1m")] == 2
    assert counts[("session", "1m")] == 2
    assert counts[("ip", "15m")] == 2


def test_session_cookie_on_https(redis):
    """On HTTPS pretix calls the cookie __Host-pretix_session."""
    env = environ(ip="203.0.113.5")
    env["HTTP_COOKIE"] = "__Host-pretix_csrftoken=x; __Host-pretix_session=s1"
    requests.on_request_started(env)
    env2 = environ(ip="203.0.113.5")
    env2["HTTP_COOKIE"] = "__Host-pretix_session=s2"
    requests.on_request_started(env2)
    assert visitor_counts()[("session", "1m")] == 2


def test_https_session_cookie_wins_over_legacy_cookie():
    env = {"HTTP_COOKIE": "pretix_session=old; __Host-pretix_session=new"}
    assert visitors.session_id(env) == "new"
    assert visitors.session_id({"HTTP_COOKIE": "pretix_session=plain"}) == "plain"
    assert visitors.session_id({"HTTP_COOKIE": "other=1"}) is None
    assert visitors.session_id({}) is None


def test_ids_are_not_stored_in_clear(redis):
    requests.on_request_started(environ(ip="203.0.113.5", session="secret-session"))
    keys = redis.keys("pretix_more_metrics:visitors:*")
    assert keys
    for key in keys:
        # fakeredis stores HyperLogLogs as sets of the added elements, real Redis as registers.
        stored = redis.smembers(key) if redis.type(key) == b"set" else {redis.get(key)}
        blob = b"".join(stored) + key
        assert b"203.0.113.5" not in blob
        assert b"secret-session" not in blob


def test_windows(redis):
    pipe = redis.pipeline()
    t = 1_000_000
    visitors.add_to_pipeline(pipe, environ(ip="203.0.113.1"), now=t - 200)  # only in 5m and 15m
    visitors.add_to_pipeline(pipe, environ(ip="203.0.113.2"), now=t - 30)  # in all windows
    visitors.add_to_pipeline(pipe, environ(ip="203.0.113.3"), now=t - 600)  # only in 15m
    pipe.execute()
    counts = {(lbl["by"], lbl["window"]): v for _, lbl, v in visitors.collect_visitors(now=t)}
    assert counts[("ip", "1m")] == 1
    assert counts[("ip", "5m")] == 2
    assert counts[("ip", "15m")] == 3


def test_loopback_is_not_counted_without_trusted_proxy(redis, settings):
    settings.TRUST_X_FORWARDED_FOR = False
    requests.on_request_started(environ(ip="127.0.0.1", xff="203.0.113.9"))
    assert visitor_counts()[("ip", "1m")] == 0


def test_x_forwarded_for(redis, settings):
    settings.TRUST_X_FORWARDED_FOR = True
    requests.on_request_started(environ(ip="127.0.0.1", xff="203.0.113.9, 10.0.0.1"))
    requests.on_request_started(environ(ip="127.0.0.1", xff="203.0.113.10"))
    assert visitor_counts()[("ip", "1m")] == 2


def test_no_redis_is_a_noop(settings):
    settings.HAS_REDIS = False
    requests.on_request_started(environ())
    requests.on_request_finished()
    assert requests.collect_in_flight() == []
    assert visitors.collect_visitors() == []


@pytest.mark.django_db
def test_signal_receivers_run_on_real_requests(client, redis, event):
    client.get("/htu/tuball/", REMOTE_ADDR="203.0.113.50")
    assert visitor_counts()[("ip", "1m")] == 1
    assert in_flight() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("secure", [False, True])
def test_real_session_cookie_is_counted(client, redis, event, quota, secure):
    """Add to cart through pretix's real views so pretix itself chooses the cookie name."""
    from django_scopes import scopes_disabled

    with scopes_disabled():
        item = quota.items.first()
    client.post("/htu/tuball/cart/add", {f"item_{item.pk}": "1"}, secure=secure, REMOTE_ADDR="203.0.113.60")
    expected = "__Host-pretix_session" if secure else "pretix_session"
    assert expected in client.cookies
    client.get("/htu/tuball/", secure=secure, REMOTE_ADDR="203.0.113.60")
    assert visitor_counts()[("session", "1m")] == 1
