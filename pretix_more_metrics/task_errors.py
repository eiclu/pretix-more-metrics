"""
Maps a failed cart/checkout task's exception to the key of the error message pretix used,
e.g. ``in_part_listed`` when a product sold out while it was being added to the cart.

pretix raises ``CartError(error_messages[key])`` (identity check works) or
``CartError(error_messages[key] % args)`` (a formatted, translated string). For the latter
we match against a pattern built from each message in every configured language.
"""
import functools
import re

from django.conf import settings
from django.utils import translation

PLACEHOLDER = re.compile(r"%(?:\([^)]*\))?[-#0 +]*\d*(?:\.\d+)?[sdifr]")

TASK_MODULES = {
    "pretix.base.services.cart": ("pretix.base.services.cart", "CartError"),
    "pretix.base.services.orders": ("pretix.base.services.orders", "OrderError"),
}


def _module_and_name(task_name):
    module, _, short = task_name.rpartition(".")
    return module, short


def is_shop_task(task_name):
    return _module_and_name(task_name)[0] in TASK_MODULES


@functools.lru_cache(maxsize=None)
def _messages(module):
    import importlib

    mod = importlib.import_module(module)
    return mod.error_messages, getattr(mod, TASK_MODULES[module][1])


def _regex(text):
    parts = PLACEHOLDER.split(text.replace("%%", "\0"))
    return re.compile(".*?".join(re.escape(p).replace("\0", "%") for p in parts), re.DOTALL)


@functools.lru_cache(maxsize=None)
def _patterns(module):
    messages, _ = _messages(module)
    patterns = []
    for code, _name in settings.LANGUAGES:
        with translation.override(code):
            for key, msg in messages.items():
                try:
                    text = str(msg)
                except Exception:  # e.g. ngettext_lazy without a number
                    continue
                literal_len = len(PLACEHOLDER.sub("", text))
                patterns.append((literal_len, key, _regex(text)))
    # Prefer the most specific message if several match.
    patterns.sort(key=lambda p: -p[0])
    return [(key, rx) for _, key, rx in patterns]


def classify(task_name, exc):
    module, _ = _module_and_name(task_name)
    if module not in TASK_MODULES:
        return None
    messages, error_class = _messages(module)
    if not isinstance(exc, error_class):
        return "exception"
    if not exc.args:
        return "other"
    raw = exc.args[0]
    for key, msg in messages.items():
        if raw is msg:
            return key
    try:
        text = str(raw)
    except Exception:
        return "other"
    for key, rx in _patterns(module):
        if rx.fullmatch(text):
            return key
    return "other"


def short_task_name(task_name):
    return _module_and_name(task_name)[1]
