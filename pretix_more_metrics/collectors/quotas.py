from pretix.base.models import Quota
from pretix.base.services.quotas import QuotaAvailability

from .events import enabled_events, event_labels

USAGE_KINDS = (
    ("paid", "count_paid_orders"),
    ("pending", "count_pending_orders"),
    ("exited", "count_exited_orders"),
    ("cart", "count_cart"),
    ("vouchers", "count_vouchers"),
    ("waitinglist", "count_waitinglist"),
)


def _quota_labels(quota, event):
    labels = event_labels(event)
    labels["subevent"] = str(quota.subevent_id or "")
    labels["quota_id"] = str(quota.pk)
    labels["quota"] = quota.name
    return labels


def collect():
    events = {e.pk: e for e in enabled_events()}
    if not events:
        return []

    quotas = []
    for q in Quota.objects.filter(event_id__in=events.keys()).select_related("subevent"):
        if q.subevent_id and (not q.subevent.active or q.subevent.presale_has_ended):
            continue
        quotas.append(q)
    if not quotas:
        return []

    qa = QuotaAvailability(full_results=True)
    qa.queue(*quotas)
    qa.compute()

    samples = []
    for q in quotas:
        labels = _quota_labels(q, events[q.event_id])
        state, available = qa.results[q]
        samples.append(("pretix_quota_size", labels, q.size))
        samples.append(("pretix_quota_available", labels, available))
        samples.append(("pretix_quota_availability_state", labels, state))
        samples.append(("pretix_quota_closed", labels, int(q.closed)))
        for kind, attr in USAGE_KINDS:
            samples.append(("pretix_quota_used", dict(labels, kind=kind), getattr(qa, attr)[q]))
    return samples
