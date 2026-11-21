from pretix.base.models import Event

PLUGIN_NAME = "pretix_more_metrics"


def enabled_events():
    """
    Events that get per-event metrics: the plugin is enabled and the presale has not ended yet.
    """
    qs = Event.objects.filter(plugins__contains=PLUGIN_NAME).select_related("organizer")
    return [e for e in qs if PLUGIN_NAME in e.get_plugins() and not e.presale_has_ended]


def event_labels(event):
    return {"organizer": event.organizer.slug, "event": event.slug}
