from django.utils.translation import gettext_lazy

from . import __version__

try:
    from pretix.base.plugins import PluginConfig
except ImportError:  # pragma: no cover
    raise RuntimeError("Please use pretix 2025.1 or above to run this plugin!")


class PluginApp(PluginConfig):
    default = True
    name = "pretix_more_metrics"
    verbose_name = "More metrics"

    class PretixPluginMeta:
        name = gettext_lazy("More metrics")
        author = "Luca Eichler"
        description = gettext_lazy(
            "Adds quota availability, visitor counts, shop funnel, PostgreSQL, Redis and host metrics "
            "to pretix's built-in Prometheus endpoint (/metrics). Enable it on every event whose "
            "quotas and orders should show up in the metrics."
        )
        visible = True
        version = __version__
        category = "INTEGRATION"
        compatibility = "pretix>=2025.1.0"

    def ready(self):
        from . import signals  # NOQA
        from .exporter import install

        install()
