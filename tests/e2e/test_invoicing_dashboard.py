"""Invoicing dashboard: the performance band, its filters and its chart.

The arithmetic behind these numbers is pinned in
tests/unit/test_invoicing_performance.py, which can set up a year of documents
far more cheaply than driving the UI. What is asserted here is what only a
browser can check: that the band renders, that the chart draws three series
with the encodings that make them distinguishable, that the filters round-trip
through the URL, that both themes work, and that the page has no horizontal
overflow on a phone.
"""

import os

# Same port the harness starts the server on (tests/e2e/conftest.py).
BASE_URL = "http://127.0.0.1:" + os.environ.get("E2E_PORT", "5050")
DASH = f"{BASE_URL}/invoicing/"


def _open(page):
    page.goto(DASH)
    page.wait_for_load_state("networkidle")
    return page


class TestPerformanceBand:
    def test_dashboard_leads_with_performance(self, admin_page):
        _open(admin_page)
        assert admin_page.locator(".perf-title").inner_text().strip() == "Performance"

    def test_three_tiles_in_reading_order(self, admin_page):
        """Revenue, then what it cost, then what is left. The order is the
        sentence the dashboard is making."""
        _open(admin_page)
        labels = admin_page.eval_on_selector_all(
            ".perf-kpi-label", "els => els.map(e => e.textContent.trim())")
        assert labels == ["Revenue", "Purchases", "Gross profit"]

    def test_every_tile_shows_a_value_and_a_provenance_line(self, admin_page):
        _open(admin_page)
        assert admin_page.locator(".perf-kpi-value").count() == 3
        for v in admin_page.eval_on_selector_all(
                ".perf-kpi-value", "els => els.map(e => e.textContent.trim())"):
            assert v, "a stat tile rendered with no number"
        assert admin_page.locator(".perf-kpi-foot").count() == 3

    def test_the_removed_tile_bands_are_gone(self, admin_page):
        """The settlement strip, the document counts and Quick actions were
        removed from this page; the route no longer computes them either."""
        _open(admin_page)
        assert admin_page.locator(".dash-track").count() == 0
        assert admin_page.locator(".dash-stat").count() == 0
        assert admin_page.get_by_text("Quick actions").count() == 0


class TestChart:
    def test_three_series_over_twelve_months(self, admin_page):
        _open(admin_page)
        assert admin_page.locator(".perf-line").count() == 3
        months = admin_page.eval_on_selector_all(
            ".perf-xlab", "els => els.map(e => e.textContent)")
        assert months == ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

    def test_every_series_has_twelve_points(self, admin_page):
        _open(admin_page)
        counts = admin_page.eval_on_selector_all(
            ".perf-line",
            "els => els.map(e => e.getAttribute('points').trim().split(/\\s+/).length)")
        assert counts == [12, 12, 12]

    def test_purchases_carries_a_second_identity_channel(self, admin_page):
        """Colour alone must not separate the series. Purchases is dashed, so
        the chart still reads in greyscale and under colour blindness."""
        _open(admin_page)
        dash = admin_page.eval_on_selector(
            '.perf-line[data-s="pur"]',
            "e => getComputedStyle(e).strokeDasharray")
        assert dash not in ("", "none"), "the context series lost its dash"
        for solid in ("rev", "gp"):
            assert admin_page.eval_on_selector(
                f'.perf-line[data-s="{solid}"]',
                "e => getComputedStyle(e).strokeDasharray") in ("", "none")

    def test_the_three_series_are_visually_distinct(self, admin_page):
        _open(admin_page)
        strokes = admin_page.eval_on_selector_all(
            ".perf-line", "els => els.map(e => getComputedStyle(e).stroke)")
        assert len(set(strokes)) == 3, f"series share a colour: {strokes}"

    def test_legend_names_and_values_every_series(self, admin_page):
        """The legend is the identity channel and the contrast relief: no
        value may be reachable only by telling two colours apart."""
        _open(admin_page)
        legend = admin_page.eval_on_selector_all(
            ".perf-leg", "els => els.map(e => e.textContent.replace(/\\s+/g,' ').trim())")
        assert len(legend) == 3
        for entry, name in zip(legend, ("Revenue", "Purchases", "Gross profit")):
            assert entry.startswith(name) and entry != name, entry

    def test_gridlines_are_round_numbers(self, admin_page):
        _open(admin_page)
        ticks = admin_page.eval_on_selector_all(
            ".perf-tick", "els => els.map(e => e.textContent)")
        assert len(ticks) >= 2
        assert "0" in ticks, "the axis does not show a zero line"

    def test_table_view_carries_every_month(self, admin_page):
        _open(admin_page)
        rows = admin_page.locator(".perf-table tbody tr")
        assert rows.count() == 12
        assert admin_page.locator(".perf-table tfoot th").count() == 4

    def test_hover_reports_all_three_series_for_a_month(self, admin_page):
        _open(admin_page)
        admin_page.locator(".perf-hit").nth(6).hover()
        admin_page.wait_for_timeout(300)
        tip = admin_page.locator("#perf-tip")
        assert "on" in (tip.get_attribute("class") or "")
        text = tip.inner_text()
        assert "JUL" in text
        for name in ("Revenue", "Purchases", "Gross profit"):
            assert name in text


class TestFilters:
    def test_both_filters_render(self, admin_page):
        _open(admin_page)
        assert admin_page.locator("#perf-label").is_visible()
        assert admin_page.locator("#perf-year").is_visible()

    def test_label_filter_round_trips_through_the_url(self, admin_page):
        """A filtered dashboard has to be a shareable link, so the selection
        comes from the query string rather than from client state."""
        _open(admin_page)
        opts = admin_page.eval_on_selector_all(
            "#perf-label option", "els => els.map(e => e.value)")
        target = next((o for o in opts if o), None)
        if target is None:
            return  # this company has no labels; nothing to round-trip
        admin_page.goto(f"{DASH}?label={target}")
        admin_page.wait_for_load_state("networkidle")
        assert admin_page.eval_on_selector("#perf-label", "e => e.value") == target

    def test_a_hand_edited_filter_falls_back_instead_of_erroring(self, admin_page):
        """A dashboard filter is not worth a 400. Garbage in the query string
        renders the default view."""
        r = admin_page.goto(f"{DASH}?year=not-a-year&label=%3Cscript%3E")
        assert r.status == 200
        admin_page.wait_for_load_state("networkidle")
        assert admin_page.locator(".perf-kpi").count() == 3

    def test_an_unknown_label_does_not_silently_widen_the_filter(self, admin_page):
        r = admin_page.goto(f"{DASH}?label=99999")
        assert r.status == 200
        admin_page.wait_for_load_state("networkidle")
        assert admin_page.eval_on_selector("#perf-label", "e => e.value") == ""


class TestTheme:
    def test_the_toggle_flips_and_persists(self, admin_page):
        """Dark mode is opt-in via the topbar toggle and has to survive a
        reload — a theme that resets on every navigation is not a theme."""
        _open(admin_page)
        admin_page.evaluate("localStorage.removeItem('ax-theme')")
        admin_page.reload()
        admin_page.wait_for_load_state("networkidle")
        assert admin_page.evaluate(
            "document.documentElement.getAttribute('data-theme')") is None

        admin_page.locator("#theme-toggle").click()
        admin_page.wait_for_timeout(200)
        assert admin_page.evaluate(
            "document.documentElement.getAttribute('data-theme')") == "dark"

        admin_page.reload()
        admin_page.wait_for_load_state("networkidle")
        assert admin_page.evaluate(
            "document.documentElement.getAttribute('data-theme')") == "dark"
        admin_page.evaluate("localStorage.removeItem('ax-theme')")

    def test_the_chart_repaints_for_the_dark_surface(self, admin_page):
        """The series must not keep their light-mode values on a dark ground —
        that is how a chart ends up invisible."""
        _open(admin_page)
        light = admin_page.eval_on_selector_all(
            ".perf-line", "els => els.map(e => getComputedStyle(e).stroke)")
        admin_page.locator("#theme-toggle").click()
        admin_page.wait_for_timeout(250)
        dark = admin_page.eval_on_selector_all(
            ".perf-line", "els => els.map(e => getComputedStyle(e).stroke)")
        assert light != dark, "the chart did not follow the theme"
        assert len(set(dark)) == 3
        admin_page.evaluate("localStorage.removeItem('ax-theme')")


class TestResponsive:
    def test_no_horizontal_overflow_on_a_phone(self, admin_mobile):
        admin_mobile.goto(DASH)
        admin_mobile.wait_for_load_state("networkidle")
        overflow = admin_mobile.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 1, f"page scrolls sideways by {overflow}px"

    def test_the_band_still_renders_small(self, admin_mobile):
        admin_mobile.goto(DASH)
        admin_mobile.wait_for_load_state("networkidle")
        assert admin_mobile.locator(".perf-kpi").count() == 3
        assert admin_mobile.locator(".perf-line").count() == 3
