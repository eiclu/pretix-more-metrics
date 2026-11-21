import datetime

import pytest
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import CartPosition, Order

from pretix_more_metrics.collectors import carts, quotas


def _by_name(samples):
    out = {}
    for name, labels, value in samples:
        out.setdefault(name, []).append((labels, value))
    return out


@pytest.mark.django_db
def test_quota_metrics(event, quota):
    with scopes_disabled():
        item = quota.items.first()
        CartPosition.objects.create(event=event, item=item, price=0, cart_id="abc",
                                    expires=now() + datetime.timedelta(minutes=10))
        o = Order.objects.create(event=event, status=Order.STATUS_PAID, email="a@example.org",
                                 expires=now() + datetime.timedelta(days=3), total=0,
                                 sales_channel=event.organizer.sales_channels.get(identifier="web"))
        o.positions.create(item=item, price=0)
        o.positions.create(item=item, price=0)

        samples = _by_name(quotas.collect())

    labels = {"organizer": "htu", "event": "tuball", "subevent": "", "quota_id": str(quota.pk),
              "quota": quota.name}
    assert samples["pretix_quota_size"] == [(labels, 10)]
    assert samples["pretix_quota_available"] == [(labels, 7)]
    assert samples["pretix_quota_closed"] == [(labels, 0)]
    used = {lbl["kind"]: v for lbl, v in samples["pretix_quota_used"]}
    assert used["paid"] == 2
    assert used["cart"] == 1
    assert used["pending"] == 0


@pytest.mark.django_db
def test_events_without_plugin_are_ignored(event, quota):
    with scopes_disabled():
        event.plugins = "pretix.plugins.banktransfer"
        event.save()
        assert quotas.collect() == []
        assert carts.collect() == []


@pytest.mark.django_db
def test_ended_events_are_ignored(event, quota):
    with scopes_disabled():
        event.date_from = now() - datetime.timedelta(days=3)
        event.save()
        assert quotas.collect() == []


@pytest.mark.django_db
def test_cart_and_order_counts(event, quota):
    with scopes_disabled():
        item = quota.items.first()
        CartPosition.objects.create(event=event, item=item, price=0, cart_id="a",
                                    expires=now() + datetime.timedelta(minutes=10))
        CartPosition.objects.create(event=event, item=item, price=0, cart_id="b",
                                    expires=now() - datetime.timedelta(minutes=10))
        o = Order.objects.create(event=event, status=Order.STATUS_PENDING, email="a@example.org",
                                 expires=now() + datetime.timedelta(days=3), total=0,
                                 sales_channel=event.organizer.sales_channels.get(identifier="web"))
        o.positions.create(item=item, price=0)
        samples = _by_name(carts.collect())

    assert samples["pretix_cart_positions_active"] == [({"organizer": "htu", "event": "tuball"}, 1)]
    orders = {lbl["status"]: v for lbl, v in samples["pretix_orders"]}
    assert orders == {"n": 1, "p": 0, "e": 0, "c": 0}
    positions = {lbl["status"]: v for lbl, v in samples["pretix_order_positions"]}
    assert positions["n"] == 1
