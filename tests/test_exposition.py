from pretix_more_metrics.exposition import add_samples, format_labels


def test_label_escaping():
    assert format_labels({"quota": 'A "B" \\ C\nD'}) == '{quota="A \\"B\\" \\\\ C\\nD"}'


def test_no_labels():
    assert format_labels({}) == ""


def test_add_samples_skips_none_and_converts_bool():
    m = {}
    add_samples(m, [("a", {}, None), ("b", {"x": "1"}, True), ("b", {"x": "2"}, 3.5)])
    assert m == {"b": {'{x="1"}': 1, '{x="2"}': 3.5}}
