"""The aging chart's bar geometry.

``_scale_buckets`` exists because the dashboard draws the receivable and the
payable bar for one aging bucket in the same row, under one label, with a
legend naming both — every cue tells the reader to compare them. The number
that used to drive the bar width, ``share``, is a percentage of *its own
side's* total, so the comparison the chart invited was one it could not
answer: a huge receivable and a trivial payable both rendered full-width.

These tests pin the fix at the level the bug lived at — the geometry, not the
pixels — because a template is the one place in this codebase nothing can
test (UI_V2_GUIDE.md §6).
"""

from shared.executive_reports import _scale_buckets


def side(*amounts):
    """A minimal side summary: just the buckets _scale_buckets touches."""
    return {"buckets": [{"key": f"b{i}", "label": f"b{i}", "amount": a,
                         "share": 0.0}
                        for i, a in enumerate(amounts)]}


def widths(s):
    return [b["width"] for b in s["buckets"]]


def test_one_pixel_means_the_same_amount_on_both_sides():
    """The regression itself: unequal amounts must not draw equal bars."""
    recv, pay = side(725_000.0, 0.0), side(200.0, 0.0)
    _scale_buckets(recv, pay)

    assert widths(recv)[0] == 100.0          # the peak bucket anchors the scale
    assert widths(pay)[0] < 1.0              # 200 against 725,000 is a sliver
    assert widths(pay)[0] != widths(recv)[0]


def test_the_peak_bucket_may_sit_on_either_side():
    """The scale is taken across both sides, not from the receivable side."""
    recv, pay = side(100.0), side(400.0)
    _scale_buckets(recv, pay)

    assert widths(pay) == [100.0]
    assert widths(recv) == [25.0]
    assert recv["peak"] == pay["peak"] == 400.0


def test_widths_are_proportional_to_amount():
    recv, pay = side(1000.0, 500.0, 250.0, 0.0), side(0.0, 0.0, 0.0, 0.0)
    _scale_buckets(recv, pay)

    assert widths(recv) == [100.0, 50.0, 25.0, 0.0]


def test_an_empty_scope_does_not_divide_by_zero():
    """Both sides flat is the state a freshly configured company is in."""
    recv, pay = side(0.0, 0.0), side(0.0, 0.0)
    _scale_buckets(recv, pay)

    assert widths(recv) == [0.0, 0.0]
    assert widths(pay) == [0.0, 0.0]
    assert recv["peak"] == 0.0


def test_share_is_left_alone():
    """``share`` is still the right number to *print* — it is per-side, and the
    dashboard labels it as such. Only the drawing changed."""
    recv, pay = side(300.0), side(100.0)
    recv["buckets"][0]["share"] = 75.0
    _scale_buckets(recv, pay)

    assert recv["buckets"][0]["share"] == 75.0
    assert recv["buckets"][0]["width"] == 100.0


def test_every_bucket_gets_a_width_key():
    """The template reads bucket["width"] unconditionally."""
    recv, pay = side(1.0, 2.0, 3.0, 4.0), side(0.0, 0.0, 0.0, 0.0)
    _scale_buckets(recv, pay)

    for s in (recv, pay):
        assert all("width" in b for b in s["buckets"])
        assert "peak" in s
