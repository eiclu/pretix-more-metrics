# Runs inside the pretix container: `pretix shell < seed.py`
# Creates an organizer, a live event with this plugin enabled, two quotas and an API token.
import datetime
import json

from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Event, Organizer, Team

with scopes_disabled():
    organizer, _ = Organizer.objects.get_or_create(slug="ci", defaults={"name": "CI Organizer"})
    event = Event.objects.filter(organizer=organizer, slug="ball").first()
    if not event:
        event = Event.objects.create(
            organizer=organizer, name="TU Ball", slug="ball", currency="EUR",
            date_from=now() + datetime.timedelta(days=60), live=True,
            plugins="pretix.plugins.banktransfer,pretix_more_metrics",
        )
        event.settings.payment_banktransfer__enabled = True
        event.settings.payment_banktransfer_bank_details = "CI bank"
    students_item = event.items.get_or_create(name="TU Studierende", defaults=dict(default_price=10, admission=True))[0]
    big_item = event.items.get_or_create(name="Große Ballkarte", defaults=dict(default_price=40, admission=True))[0]
    students = event.quotas.get_or_create(name="[A] TU Studierende", defaults=dict(size=5))[0]
    students.items.add(students_item)
    big = event.quotas.get_or_create(name="[A] Große Ballkarten", defaults=dict(size=50))[0]
    big.items.add(big_item)

    team, _ = Team.objects.get_or_create(
        organizer=organizer, name="CI",
        defaults=dict(all_events=True, all_event_permissions=True, all_organizer_permissions=True),
    )
    token = team.tokens.first() or team.tokens.create(name="ci")

print("SEED=" + json.dumps({
    "organizer": organizer.slug,
    "event": event.slug,
    "students_item": students_item.pk,
    "big_item": big_item.pk,
    "token": token.token,
}))
