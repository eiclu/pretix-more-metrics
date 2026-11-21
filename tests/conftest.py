import datetime

import fakeredis
import pytest
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Event, Organizer

from pretix_more_metrics import visitors


@pytest.fixture
def redis(monkeypatch, settings):
    """
    Pretend pretix runs with Redis: every Redis connection pretix or this plugin asks for is
    the same in-memory fakeredis instance.
    """
    import django_redis
    import pretix.base.metrics

    fake = fakeredis.FakeRedis()
    settings.HAS_REDIS = True
    monkeypatch.setattr(django_redis, "get_redis_connection", lambda *args, **kwargs: fake)
    monkeypatch.setattr(pretix.base.metrics, "redis", fake, raising=False)
    visitors._salt.cache_clear()
    return fake


@pytest.fixture
def organizer():
    with scopes_disabled():
        return Organizer.objects.create(name="HTU", slug="htu")


@pytest.fixture
def event(organizer):
    with scopes_disabled():
        return Event.objects.create(
            organizer=organizer, name="TU Ball", slug="tuball",
            date_from=now() + datetime.timedelta(days=30),
            plugins="pretix.plugins.banktransfer,pretix_more_metrics",
            live=True,
        )


@pytest.fixture
def quota(event):
    with scopes_disabled():
        item = event.items.create(name="Große Ballkarte", default_price=0, admission=True)
        q = event.quotas.create(name='[A] Große "Ballkarten"', size=10)
        q.items.add(item)
        return q
