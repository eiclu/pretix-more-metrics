import logging

from celery.signals import task_failure
from django.conf import settings
from django.core.signals import request_finished, request_started
from django.dispatch import receiver
from pretix.base.signals import order_paid, order_placed

from . import counters, requests, task_errors

logger = logging.getLogger(__name__)


@receiver(request_started, dispatch_uid="pretix_more_metrics_request_started")
def on_request_started(sender, environ=None, **kwargs):
    if settings.METRICS_ENABLED and environ is not None:
        requests.on_request_started(environ)


@receiver(request_finished, dispatch_uid="pretix_more_metrics_request_finished")
def on_request_finished(sender, **kwargs):
    if settings.METRICS_ENABLED:
        requests.on_request_finished()


def _sales_channel(order):
    channel = getattr(order, "sales_channel", None)
    return getattr(channel, "identifier", None) or str(channel or "")


@receiver(order_placed, dispatch_uid="pretix_more_metrics_order_placed")
def on_order_placed(sender, order, **kwargs):
    if not settings.METRICS_ENABLED:
        return
    try:
        labels = dict(organizer=sender.organizer.slug, event=sender.slug, sales_channel=_sales_channel(order))
        counters.orders_placed_total.inc(1, **labels)
        counters.order_positions_placed_total.inc(order.positions.count(), **labels)
    except Exception:
        logger.exception("pretix-more-metrics: could not count placed order")


@receiver(order_paid, dispatch_uid="pretix_more_metrics_order_paid")
def on_order_paid(sender, order, **kwargs):
    if not settings.METRICS_ENABLED:
        return
    try:
        counters.orders_paid_total.inc(1, organizer=sender.organizer.slug, event=sender.slug)
    except Exception:
        logger.exception("pretix-more-metrics: could not count paid order")


@task_failure.connect(weak=False, dispatch_uid="pretix_more_metrics_task_failure")
def on_task_failure(sender=None, exception=None, **kwargs):
    if not settings.METRICS_ENABLED or sender is None:
        return
    name = getattr(sender, "name", "") or ""
    if not task_errors.is_shop_task(name):
        return
    try:
        reason = task_errors.classify(name, exception)
        counters.shop_task_errors_total.inc(1, task=task_errors.short_task_name(name), reason=reason)
    except Exception:
        logger.exception("pretix-more-metrics: could not count task failure")
