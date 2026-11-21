import base64

import pytest

from pretix_more_metrics import exporter


def _scrape(client):
    auth = base64.b64encode(b"metrics:secret").decode()
    resp = client.get("/metrics", HTTP_AUTHORIZATION="Basic " + auth)
    assert resp.status_code == 200
    return resp.content.decode()


def test_wrapper_is_installed():
    from pretix.base import metrics

    assert getattr(metrics.metric_values, exporter.MARKER, False)
    # Installing twice must not wrap twice
    assert exporter.install()
    assert not getattr(metrics.metric_values.__wrapped__, exporter.MARKER, False)


@pytest.mark.django_db
def test_metrics_endpoint_contains_builtin_and_plugin_metrics(client, redis, quota):
    body = _scrape(client)
    assert "pretix_model_instances" in body  # pretix's own
    assert 'pretix_more_metrics_info{version="' in body
    assert 'pretix_more_metrics_collector_up{collector="quotas"} 1' in body
    assert 'pretix_quota_size{organizer="htu",event="tuball",subevent="",quota_id="%d",' \
           'quota="[A] Große \\"Ballkarten\\""} 10' % quota.pk in body


@pytest.mark.django_db
def test_failing_collector_does_not_break_endpoint(client, redis, monkeypatch):
    def broken():
        raise RuntimeError("boom")

    monkeypatch.setattr(exporter, "_collectors", lambda: [("broken", broken, 0)])
    body = _scrape(client)
    assert "pretix_model_instances" in body
    assert 'pretix_more_metrics_collector_up{collector="broken"} 0' in body


@pytest.mark.django_db
def test_endpoint_still_requires_auth(client):
    assert client.get("/metrics").status_code == 401
