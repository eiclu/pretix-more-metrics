"""
Hooks the plugin's collectors into pretix's built-in ``/metrics`` endpoint.

pretix has no extension point in ``pretix.base.metrics.metric_values()``. Its view
(``pretix.base.views.metrics.serve_metrics``) calls ``metrics.metric_values()`` through
the module at request time, so replacing the module attribute with a wrapper is enough
for our values to show up in the same response. The wrapper never lets an error in this
plugin break pretix's own metrics.
"""
import functools
import logging
import time

from django.core.cache import cache
from django_scopes import scopes_disabled

from . import __version__
from .exposition import add_samples

logger = logging.getLogger(__name__)

MARKER = "_pretix_more_metrics_wrapped"
CACHE_PREFIX = "pretix_more_metrics:collector:"


def _collectors():
    from . import conf
    from .collectors import carts, database, quotas, redis_info, system
    from .requests import collect_in_flight
    from .visitors import collect_visitors

    collectors = [
        ("quotas", quotas.collect, conf.quota_cache_seconds()),
        ("shop", carts.collect, conf.quota_cache_seconds()),
        ("visitors", collect_visitors, 0),
        ("in_flight", collect_in_flight, 0),
        ("database", database.collect, 0),
        ("redis", redis_info.collect, 0),
    ]
    if conf.system_enabled():
        collectors.append(("system", system.collect, 0))
    return collectors


def _run(name, func, ttl):
    if ttl > 0:
        cached = cache.get(CACHE_PREFIX + name)
        if cached is not None:
            return cached
    samples = list(func())
    if ttl > 0:
        cache.set(CACHE_PREFIX + name, samples, ttl)
    return samples


def collect_into(metrics):
    add_samples(metrics, [("pretix_more_metrics_info", {"version": __version__}, 1)])
    for name, func, ttl in _collectors():
        t0 = time.perf_counter()
        try:
            with scopes_disabled():
                samples = _run(name, func, ttl)
            add_samples(metrics, samples)
            up = 1
        except Exception:
            logger.exception("pretix-more-metrics: collector %s failed", name)
            up = 0
        add_samples(metrics, [
            ("pretix_more_metrics_collector_up", {"collector": name}, up),
            ("pretix_more_metrics_collector_duration_seconds", {"collector": name},
             round(time.perf_counter() - t0, 6)),
        ])
    return metrics


def install():
    from pretix.base import metrics as pretix_metrics

    original = getattr(pretix_metrics, "metric_values", None)
    if original is None or not callable(original):
        logger.warning(
            "pretix-more-metrics: pretix.base.metrics.metric_values not found, additional metrics are disabled. "
            "This pretix version is not supported."
        )
        return False
    if getattr(original, MARKER, False):
        return True

    @functools.wraps(original)
    def metric_values(*args, **kwargs):
        metrics = original(*args, **kwargs)
        try:
            collect_into(metrics)
        except Exception:
            logger.exception("pretix-more-metrics: collecting additional metrics failed")
        return metrics

    setattr(metric_values, MARKER, True)
    pretix_metrics.metric_values = metric_values
    return True
