import datetime

import pytest
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Order
from pretix.base.services.cart import (
    CartError, add_items_to_cart, error_messages,
)
from pretix.base.signals import order_paid, order_placed

from pretix_more_metrics import task_errors


def hash_value(redis, key):
    v = redis.hget("pretix_metrics", key)
    return float(v) if v is not None else None


@pytest.mark.django_db
def test_order_placed_and_paid(redis, event, quota):
    with scopes_disabled():
        item = quota.items.first()
        o = Order.objects.create(event=event, status=Order.STATUS_PENDING, email="a@example.org",
                                 expires=now() + datetime.timedelta(days=3), total=0,
                                 sales_channel=event.organizer.sales_channels.get(identifier="web"))
        o.positions.create(item=item, price=0)
        o.positions.create(item=item, price=0)
        order_placed.send(event, order=o, bulk=False)
        order_paid.send(event, order=o)

    labels = '{organizer="htu",event="tuball",sales_channel="web"}'
    assert hash_value(redis, "pretix_orders_placed_total" + labels) == 1
    assert hash_value(redis, "pretix_order_positions_placed_total" + labels) == 2
    assert hash_value(redis, 'pretix_orders_paid_total{organizer="htu",event="tuball"}') == 1


@pytest.mark.django_db
def test_order_placed_ignored_without_plugin(redis, event, quota):
    with scopes_disabled():
        event.plugins = ""
        event.save()
        o = Order.objects.create(event=event, status=Order.STATUS_PENDING, email="a@example.org",
                                 expires=now() + datetime.timedelta(days=3), total=0,
                                 sales_channel=event.organizer.sales_channels.get(identifier="web"))
        order_placed.send(event, order=o, bulk=False)
    assert redis.hlen("pretix_metrics") == 0


@pytest.mark.django_db
def test_sold_out_cart_error_is_counted(redis, event, quota):
    """Runs pretix's real add-to-cart task (eagerly) and asks for more than the quota has."""
    with scopes_disabled():
        item = quota.items.first()
        quota.size = 2
        quota.save()
    result = add_items_to_cart.apply(kwargs=dict(
        event=event.pk, cart_id="testcart", locale="de",
        items=[{"item": item.pk, "variation": None, "count": 3, "price": "", "voucher": None}],
    ))
    assert isinstance(result.result, CartError)
    assert hash_value(
        redis, 'pretix_shop_task_errors_total{task="add_items_to_cart",reason="in_part_listed"}'
    ) == 1


def test_classify_identity():
    exc = CartError(error_messages["ended"])
    assert task_errors.classify("pretix.base.services.cart.add_items_to_cart", exc) == "ended"


@pytest.mark.parametrize("lang", ["en", "de"])
def test_classify_formatted_translated_message(lang):
    from django.utils import translation

    with translation.override(lang):
        exc = CartError(error_messages["unavailable_listed"] % "Große Ballkarte")
        exc2 = CartError(error_messages["max_items"] % 4)
    assert task_errors.classify("pretix.base.services.cart.add_items_to_cart", exc) == "unavailable_listed"
    assert task_errors.classify("pretix.base.services.cart.add_items_to_cart", exc2) in ("max_items", "other")


def test_classify_other_and_exception():
    name = "pretix.base.services.cart.add_items_to_cart"
    assert task_errors.classify(name, CartError("something else entirely")) == "other"
    assert task_errors.classify(name, ValueError("x")) == "exception"
    assert task_errors.classify("pretix.base.services.mail.mail_send_task", ValueError("x")) is None


def test_order_errors():
    from pretix.base.services.orders import (
        OrderError, error_messages as order_messages,
    )

    exc = OrderError(order_messages["empty"])
    assert task_errors.classify("pretix.base.services.orders.perform_order", exc) == "empty"
