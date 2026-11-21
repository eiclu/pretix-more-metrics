"""
Unique visitors, counted in Redis HyperLogLogs.

Every shop request adds a salted hash of the client IP and of the session cookie to the
HyperLogLog of the current 10 second bucket. At scrape time, the buckets of the last
1/5/15 minutes are merged with PFCOUNT. A HyperLogLog only keeps counters (about 12 KB at
most per key, ~1% error), so neither IPs nor session IDs are stored.
"""
import functools
import hashlib
import logging
import time

from django.conf import settings
from django.http.cookie import parse_cookie

from . import conf, redis_conn

logger = logging.getLogger(__name__)

BUCKET_SECONDS = 10
WINDOWS = (("1m", 60), ("5m", 300), ("15m", 900))
KEY_PREFIX = "pretix_more_metrics:visitors"
KEY_TTL = max(s for _, s in WINDOWS) + 2 * BUCKET_SECONDS
LOOPBACK = {"127.0.0.1", "::1", ""}

_warned_loopback = False


@functools.lru_cache(maxsize=1)
def _salt():
    return conf.visitor_salt().encode()


def _hash(value):
    return hashlib.blake2b(value.encode(), key=_salt()[:64], digest_size=8).hexdigest()


def _key(by, bucket):
    return f"{KEY_PREFIX}:{by}:{bucket}"


def client_ip(environ):
    """
    Same logic as pretix's ``get_client_ip``. Returns ``None`` for loopback addresses,
    which is what pretix sees behind a reverse proxy unless ``trust_x_forwarded_for`` is on.
    """
    global _warned_loopback
    ip = environ.get("REMOTE_ADDR", "") or ""
    if settings.TRUST_X_FORWARDED_FOR:
        xff = environ.get("HTTP_X_FORWARDED_FOR")
        if xff:
            ip = xff.split(",")[0].strip()
    if ip in LOOPBACK:
        if not _warned_loopback and not settings.TRUST_X_FORWARDED_FOR:
            logger.warning(
                "pretix-more-metrics: requests come from a loopback address, so visitors can not be counted by "
                "IP. If pretix runs behind a reverse proxy, set trust_x_forwarded_for=on in the [pretix] section "
                "of pretix.cfg."
            )
            _warned_loopback = True
        return None
    return ip


def session_id(environ):
    cookie = environ.get("HTTP_COOKIE")
    if not cookie:
        return None
    return parse_cookie(cookie).get(settings.SESSION_COOKIE_NAME) or None


def identifiers(environ):
    ids = []
    if conf.visitors_by_ip():
        ip = client_ip(environ)
        if ip:
            ids.append(("ip", ip))
    if conf.visitors_by_session():
        sid = session_id(environ)
        if sid:
            ids.append(("session", sid))
    return ids


def add_to_pipeline(pipe, environ, now=None):
    """
    Queues the PFADD commands for this request on ``pipe``. Returns the number of queued commands.
    """
    bucket = int(now if now is not None else time.time()) // BUCKET_SECONDS
    n = 0
    for by, value in identifiers(environ):
        key = _key(by, bucket)
        pipe.pfadd(key, _hash(value))
        pipe.expire(key, KEY_TTL)
        n += 2
    return n


def collect_visitors(now=None):
    r = redis_conn.get_redis()
    if r is None:
        return []
    kinds = [by for by, enabled in (("ip", conf.visitors_by_ip()), ("session", conf.visitors_by_session()))
             if enabled]
    bucket = int(now if now is not None else time.time()) // BUCKET_SECONDS
    pipe = r.pipeline(transaction=False)
    labels = []
    for by in kinds:
        for window, seconds in WINDOWS:
            pipe.pfcount(*[_key(by, bucket - i) for i in range(seconds // BUCKET_SECONDS)])
            labels.append({"by": by, "window": window})
    return [("pretix_unique_visitors", lbl, count) for lbl, count in zip(labels, pipe.execute())]
