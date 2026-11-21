"""
Plugin configuration, read from the ``[more_metrics]`` section of ``pretix.cfg``::

    [more_metrics]
    ; Seconds the per-quota numbers are cached between scrapes (default 10)
    quota_cache_seconds=10
    ; Count unique visitors by client IP and/or by session cookie (default: both on)
    visitors_by_ip=on
    visitors_by_session=on
    ; Secret mixed into the visitor hashes (default: derived from pretix's SECRET_KEY)
    visitor_salt=
    ; Export host CPU/memory/load from /proc (default on, Linux only)
    system=on
"""
import hashlib

from django.conf import settings

SECTION = "more_metrics"


def _config():
    return getattr(settings, "CONFIG_FILE", None)


def _get(option, fallback):
    cfg = _config()
    if cfg is None:
        return fallback
    return cfg.get(SECTION, option, fallback=fallback)


def _getboolean(option, fallback):
    cfg = _config()
    if cfg is None:
        return fallback
    return cfg.getboolean(SECTION, option, fallback=fallback)


def _getint(option, fallback):
    cfg = _config()
    if cfg is None:
        return fallback
    return cfg.getint(SECTION, option, fallback=fallback)


def quota_cache_seconds():
    return _getint("quota_cache_seconds", 10)


def visitors_by_ip():
    return _getboolean("visitors_by_ip", True)


def visitors_by_session():
    return _getboolean("visitors_by_session", True)


def system_enabled():
    return _getboolean("system", True)


def visitor_salt():
    salt = _get("visitor_salt", "")
    if not salt:
        salt = hashlib.sha256(("pretix_more_metrics:" + settings.SECRET_KEY).encode()).hexdigest()
    return salt
