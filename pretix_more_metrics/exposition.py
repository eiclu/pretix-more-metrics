"""
Helpers to put samples into the dict structure pretix's ``metric_values()`` returns:

    {"metric_name": {'{label="value"}': 1.0, ...}, ...}

pretix's view turns every entry into one ``name{labels} value`` line.
"""


def escape_label_value(value) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def format_labels(labels) -> str:
    if not labels:
        return ""
    return "{" + ",".join('{}="{}"'.format(k, escape_label_value(v)) for k, v in labels.items()) + "}"


def format_value(value):
    if isinstance(value, bool):
        return int(value)
    return value


def add_samples(metrics, samples):
    """
    Adds an iterable of ``(name, labels, value)`` tuples to ``metrics``.
    """
    for name, labels, value in samples:
        if value is None:
            continue
        metrics.setdefault(name, {})[format_labels(labels)] = format_value(value)
