# pretix-more-metrics

A pretix plugin that adds the metrics needed for a live ticket-sale dashboard to
**pretix's built-in Prometheus endpoint** (`/metrics`). You keep a single scrape job: the plugin's
metrics appear in the same response as pretix's own (`pretix_view_duration_seconds`,
`pretix_task_runs_total`, `pretix_celery_tasks_queued_count`, …).

nginx metrics (connections, status classes as seen by nginx) are out of scope, keep using
nginx-prometheus-exporter for those.

## Installation

```
pip install git+https://github.com/eiclu/pretix-more-metrics
```

then restart pretix (web and worker processes). The plugin has no database models or static files.

With the Docker image:

```Dockerfile
FROM pretix/standalone:stable
USER root
RUN pip3 install git+https://github.com/eiclu/pretix-more-metrics
USER pretixuser
RUN cd /pretix/src && make production
```

Then:

1. Enable pretix's metrics endpoint in `pretix.cfg` (this plugin does nothing without it):
   ```ini
   [metrics]
   enabled=true
   user=metrics
   passphrase=<secret>
   ```
2. pretix must run with Redis (`[redis]` section). Visitor, in-flight, Redis and counter metrics need it.
3. Behind a reverse proxy, set `trust_x_forwarded_for=on` in `[pretix]` so visitors can be
   counted by IP (otherwise every request comes from 127.0.0.1 and only session counting works).
4. **Enable the plugin on each event** whose quotas and orders should be exported
   (event settings → Plugins → "More metrics"). Visitor, request, database, Redis and host
   metrics are global and don't need this.

### Options

All optional, in `pretix.cfg` (or as environment variables `PRETIX_MORE_METRICS_<OPTION>`):

```ini
[more_metrics]
; Seconds per-quota and per-event numbers are cached between scrapes
quota_cache_seconds=10
; Count unique visitors by client IP and/or by session cookie
visitors_by_ip=on
visitors_by_session=on
; Secret mixed into the visitor hashes (default: derived from SECRET_KEY)
visitor_salt=
; Export host CPU/memory/load from /proc
system=on
```

## Metrics

Per-event metrics only cover events with the plugin enabled whose presale has not ended.

| Metric | Type | Labels | Notes |
|---|---|---|---|
| `pretix_quota_size` | gauge | organizer, event, subevent, quota_id, quota | unlimited quotas have no size |
| `pretix_quota_available` | gauge | same | what can still be sold right now (after carts, vouchers, waiting list) |
| `pretix_quota_availability_state` | gauge | same | 100 ok, 20 reserved (in carts), 10 ordered, 0 gone |
| `pretix_quota_closed` | gauge | same | |
| `pretix_quota_used` | gauge | same + kind (`paid`, `pending`, `exited`, `cart`, `vouchers`, `waitinglist`) | |
| `pretix_cart_positions_active` | gauge | organizer, event | exact, unexpired cart positions |
| `pretix_orders` | gauge | organizer, event, status (`n` pending, `p` paid, `e` expired, `c` canceled) | |
| `pretix_order_positions` | gauge | organizer, event, status | tickets/add-ons in orders |
| `pretix_orders_placed_total` | counter | organizer, event, sales_channel | from the `order_placed` signal (shop, API, POS) |
| `pretix_order_positions_placed_total` | counter | organizer, event, sales_channel | |
| `pretix_orders_paid_total` | counter | organizer, event | |
| `pretix_shop_task_errors_total` | counter | task, reason | failed cart/checkout tasks; reason is pretix's error key, e.g. `unavailable_listed`/`in_part_listed` (sold out), `max_items`, `voucher_invalid`, `busy`; `exception` for crashes |
| `pretix_unique_visitors` | gauge | by (`ip`, `session`), window (`1m`, `5m`, `15m`) | see below |
| `pretix_http_requests_in_flight` | gauge | | requests the gunicorn workers are serving right now |
| `pretix_db_connections` | gauge | state | PostgreSQL connections to pretix's database, from `pg_stat_activity` |
| `pretix_db_max_connections`, `pretix_db_size_bytes` | gauge | | |
| `pretix_db_transactions_total` | counter | result (`commit`, `rollback`) | |
| `pretix_db_deadlocks_total`, `pretix_db_blocks_total{source}` | counter | | |
| `pretix_redis_connected_clients`, `_blocked_clients`, `_used_memory_bytes`, `_maxmemory_bytes`, `_keys{db}` | gauge | | from Redis `INFO` |
| `pretix_redis_commands_processed_total`, `_keyspace_hits_total`, `_keyspace_misses_total`, `_evicted_keys_total`, `_expired_keys_total`, `_connections_received_total` | counter | | |
| `pretix_host_cpu_seconds_total` | counter | mode | from `/proc/stat` |
| `pretix_host_cpus`, `pretix_host_load1/5/15` | gauge | | |
| `pretix_host_memory_{total,available,free,buffers,cached}_bytes`, `pretix_host_swap_{total,free}_bytes` | gauge | | from `/proc/meminfo` |
| `pretix_more_metrics_collector_up`, `_collector_duration_seconds` | gauge | collector | 0 means the collector failed, see pretix's log |

### Unique visitors

Every shop request (not `/control/`, `/api/`, static files, `/metrics`, health checks) adds a salted
hash of the client IP and of the `pretix_session` cookie to Redis HyperLogLogs in 10-second
buckets. At scrape time the buckets of the window are merged. No IPs or session IDs are stored,
and the count is accurate to about 1%.

* `by="ip"`: everyone who loads a shop page, including people who only refresh a sold-out page.
  Shared addresses (campus Wi-Fi, carrier NAT) count once, changing addresses (IPv6 privacy
  addresses, Wi-Fi ↔ mobile) count several times. Bots are included. The IP comes from
  `X-Forwarded-For` when `trust_x_forwarded_for` is on (same logic as pretix itself).
* `by="session"`: pretix only creates a session once someone interacts (add to cart, voucher, login),
  so this counts **people actively trying to buy**, one per browser.

## Grafana queries for the "Ticket Sale Live" dashboard

| Panel | Query |
|---|---|
| Active 1min / 5m | `pretix_unique_visitors{by="ip",window="1m"}` / `…window="5m"` |
| Active visitors over time | same, plus `pretix_unique_visitors{by="session",window="5m"}` for people in the shop |
| Requests/s (Django) | `sum(rate(pretix_view_requests_total[1m]))` |
| Being served | `pretix_http_requests_in_flight` |
| Carts filled / min | `sum(increase(pretix_task_runs_total{task_name="pretix.base.services.cart.add_items_to_cart",status="success"}[1m]))` |
| Cart attempts failed | `sum(increase(pretix_task_runs_total{task_name="pretix.base.services.cart.add_items_to_cart",status=~"expected-error\|error"}[1m]))` |
| … of which sold out | `sum(increase(pretix_shop_task_errors_total{task="add_items_to_cart",reason=~"unavailable.*\|in_part.*\|seat_unavailable"}[1m]))` |
| Orders placed / min | `sum(increase(pretix_orders_placed_total[1m]))` |
| Cart & checkout p95 | `histogram_quantile(0.95, sum by (le, task_name) (rate(pretix_task_duration_seconds_bucket{task_name=~"pretix.base.services.(cart.add_items_to_cart\|orders.perform_order)"}[1m])))` |
| Still available in % | `pretix_quota_available / pretix_quota_size` (bar gauge, legend `{{quota}}`) |
| Cart positions / orders | `pretix_cart_positions_active`, `sum by (event) (pretix_orders{status=~"n\|p"})` |
| pretix view duration | `histogram_quantile(0.95, sum by (le) (rate(pretix_view_duration_seconds_bucket[1m])))` |
| Background task queue | `pretix_celery_tasks_queued_count` (by `queue`) |
| CPU usage | `1 - sum(rate(pretix_host_cpu_seconds_total{mode=~"idle\|iowait"}[1m])) / max(pretix_host_cpus)` |
| Memory used | `1 - pretix_host_memory_available_bytes / pretix_host_memory_total_bytes` |
| PostgreSQL connections | `pretix_db_connections` (by `state`) |
| Redis | `rate(pretix_redis_commands_processed_total[1m])`, `pretix_redis_connected_clients` |

## How it hooks into pretix

pretix's `pretix.base.metrics.metric_values()` has no extension point. On startup the plugin replaces
it with a wrapper that calls the original and adds its own values; pretix's view looks the function
up at request time, so everything is served from `/metrics`. Errors in the plugin are logged and
reported as `pretix_more_metrics_collector_up 0`, they never break pretix's own metrics. If a future
pretix version removes `metric_values`, the plugin logs a warning and only the event counters
remain. Tested with pretix 2026.9.3.

Counters (`pretix_orders_placed_total`, `pretix_shop_task_errors_total`, …) use pretix's own metric
classes and live in the same Redis hash as pretix's built-in counters.

Notes:

* `pretix_http_requests_in_flight` and the host metrics assume pretix runs on a single machine.
  Inside Docker, `/proc` shows the host's CPU and memory, not the container's.
* `pg_stat_activity` only shows the states of connections of pretix's own database role unless that
  role has `pg_read_all_stats`. The scrape itself counts as one active connection.

## Development

```
pip install pretix -e ".[test]"
pytest
```

`integration/` holds a docker compose setup (pretix/standalone with this plugin, PostgreSQL, Redis,
Prometheus). GitHub Actions starts it, runs a small ticket sale against it (visitors, carts, a
sold-out attempt, API orders) and checks the resulting values through Prometheus's HTTP API.
Locally:

```
cd integration
docker compose up -d --build --wait
SEED=$(docker compose exec -T -e AUTOMIGRATE=skip pretix pretix shell < seed.py | sed -n 's/^SEED=//p')
python3 run_checks.py "$SEED"
docker compose down -v
```
