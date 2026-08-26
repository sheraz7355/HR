"""Month windows and deltas behind the executive profitability band.

The money arithmetic is deliberately not retested here — ``_pl_figures`` calls
the same ``_pl_by_section`` the Profit & Loss statement renders from, and
``tests/unit/test_comparative_pl.py`` already pins that. What is new, and what
these cover, is the part that had to be written from scratch: walking back over
month boundaries, and refusing to print a percentage that would be a lie.
"""

from datetime import date

from shared.executive_reports import _delta, _month_end, _month_starts


class TestMonthWindows:
    def test_walks_back_across_a_year_boundary(self):
        got = _month_starts(date(2026, 2, 17), 4)
        assert got == [date(2025, 11, 1), date(2025, 12, 1),
                       date(2026, 1, 1), date(2026, 2, 1)]

    def test_is_oldest_first_because_a_chart_reads_left_to_right(self):
        got = _month_starts(date(2026, 8, 26), 12)
        assert got == sorted(got)
        assert got[-1] == date(2026, 8, 1)
        assert len(got) == 12

    def test_a_single_month_window_is_the_month_you_are_in(self):
        assert _month_starts(date(2026, 8, 26), 1) == [date(2026, 8, 1)]

    def test_month_end_handles_every_length(self):
        assert _month_end(date(2026, 1, 9)) == date(2026, 1, 31)
        assert _month_end(date(2026, 4, 1)) == date(2026, 4, 30)
        assert _month_end(date(2026, 12, 25)) == date(2026, 12, 31)

    def test_month_end_handles_february_in_a_leap_year(self):
        assert _month_end(date(2024, 2, 1)) == date(2024, 2, 29)
        assert _month_end(date(2026, 2, 1)) == date(2026, 2, 28)


class TestDelta:
    def test_ordinary_growth(self):
        assert _delta(150.0, 100.0) == 50.0

    def test_a_fall_is_negative(self):
        assert _delta(75.0, 100.0) == -25.0

    def test_growth_from_zero_is_undefined_not_infinite(self):
        """A percentage needs a base. Zero gives none, so the tile says '—'."""
        assert _delta(500.0, 0.0) is None

    def test_growth_from_a_loss_has_no_readable_sign(self):
        """Up from -100 to -50 is an improvement; up from -100 to 0 is too.
        A percentage of a negative base flips meaning, so it is not shown."""
        assert _delta(-50.0, -100.0) is None

    def test_a_missing_prior_period_is_not_a_delta(self):
        assert _delta(100.0, None) is None
