from django.db.models import Count
from django.utils.timezone import now
from pretix.base.models import CartPosition, Order, OrderPosition

from .events import enabled_events, event_labels


def collect():
    events = {e.pk: e for e in enabled_events()}
    if not events:
        return []

    samples = []

    carts = dict(
        CartPosition.objects.filter(event_id__in=events.keys(), expires__gte=now())
        .order_by().values("event_id").annotate(c=Count("id")).values_list("event_id", "c")
    )
    for pk, event in events.items():
        samples.append(("pretix_cart_positions_active", event_labels(event), carts.get(pk, 0)))

    orders = {
        (row["event_id"], row["status"]): row["c"]
        for row in Order.objects.filter(event_id__in=events.keys())
        .order_by().values("event_id", "status").annotate(c=Count("id"))
    }
    positions = {
        (row["order__event_id"], row["order__status"]): row["c"]
        for row in OrderPosition.objects.filter(order__event_id__in=events.keys())
        .order_by().values("order__event_id", "order__status").annotate(c=Count("id"))
    }
    for pk, event in events.items():
        for status, _ in Order.STATUS_CHOICE:
            labels = dict(event_labels(event), status=status)
            samples.append(("pretix_orders", labels, orders.get((pk, status), 0)))
            samples.append(("pretix_order_positions", labels, positions.get((pk, status), 0)))
    return samples
