"""
Per-request bookkeeping, driven by Django's request_started / request_finished signals:

* requests in flight: a Redis hash ``pid -> number of requests this process is serving``.
  Entries of processes that no longer exist are removed at scrape time, so a killed
  worker can not leave the gauge too high.
* unique visitors, see ``visitors.py``.

Both share one Redis round trip per request.
"""
import logging
import os
import threading
import time

from . import redis_conn, visitors

logger = logging.getLogger(__name__)

IN_FLIGHT_KEY = "pretix_more_metrics:in_flight"

# First path segments that are never counted as shop visitors.
NOT_VISITORS = {
    "control", "api", "static", "media", "metrics", "healthcheck", "jsi18n", "csp_report",
    "redirect", "favicon.ico", "robots.txt", ".well-known", "__debug__",
}
# First path segments that are not counted as requests in flight (monitoring itself).
NOT_IN_FLIGHT = {"metrics", "healthcheck"}

_local = threading.local()
_initialized_pid = None
_last_error_log = 0.0


def _log_error():
    global _last_error_log
    if time.monotonic() - _last_error_log > 60:
        _last_error_log = time.monotonic()
        logger.exception("pretix-more-metrics: could not record request metrics")


def _first_segment(path):
    return path.lstrip("/").split("/", 1)[0]


def on_request_started(environ):
    global _initialized_pid
    r = redis_conn.get_redis()
    if r is None:
        return
    _local.in_flight = False
    segment = _first_segment(environ.get("PATH_INFO", "") or "")
    pid = os.getpid()
    try:
        pipe = r.pipeline(transaction=False)
        queued = 0
        count_in_flight = segment not in NOT_IN_FLIGHT
        if count_in_flight:
            if _initialized_pid != pid:
                # New process (or a recycled pid): nothing of ours can be in flight yet.
                pipe.hset(IN_FLIGHT_KEY, pid, 0)
            pipe.hincrby(IN_FLIGHT_KEY, pid, 1)
            queued += 1
        if segment not in NOT_VISITORS and environ.get("REQUEST_METHOD") in ("GET", "POST"):
            queued += visitors.add_to_pipeline(pipe, environ)
        if queued:
            pipe.execute()
            if count_in_flight:
                _initialized_pid = pid
                _local.in_flight = True
    except Exception:
        _log_error()


def on_request_finished():
    if not getattr(_local, "in_flight", False):
        return
    _local.in_flight = False
    r = redis_conn.get_redis()
    if r is None:
        return
    try:
        r.hincrby(IN_FLIGHT_KEY, os.getpid(), -1)
    except Exception:
        _log_error()


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def collect_in_flight():
    r = redis_conn.get_redis()
    if r is None:
        return []
    total = 0
    dead = []
    for pid, value in r.hgetall(IN_FLIGHT_KEY).items():
        if not _alive(int(pid)):
            dead.append(pid)
            continue
        total += max(int(value), 0)
    if dead:
        r.hdel(IN_FLIGHT_KEY, *dead)
    return [("pretix_http_requests_in_flight", {}, total)]
