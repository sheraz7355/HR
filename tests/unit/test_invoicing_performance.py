"""The invoicing dashboard's revenue / purchases / gross-profit engine.

These cover the arithmetic the dashboard prints, which is the part a reader
would never catch being wrong: the figures look plausible whatever the basis
is. The rules being pinned are the ones stated in
``shared/invoicing_performance.py`` — net of tax, net of approved returns,
drafts excluded, returns inheriting their invoice's label — plus the chart
geometry, because a y-scale that silently clips a series is also a wrong
number, just drawn instead of printed.
"""

from datetime import datetime

import pytest

from shared.extensions import db
from shared import invoicing_performance as perf

# These imports must happen at MODULE level, not inside the fixture. Importing
# invoicing_performance above already puts the two invoice tables on the shared
# metadata, and the conftest's app fixture runs create_all() before any fixture
# of ours gets a turn — so if project_labels is not registered by then, the
# label_id foreign key has no target and create_all dies with
# NoReferencedTableError before a single test runs.
import shared.models.project_label  # noqa: E402,F401
import inventory_app.models.sales_return  # noqa: E402,F401
import inventory_app.models.purchase_return  # noqa: E402,F401


@pytest.fixture
def docs(app):
    """Create the invoicing document tables on the unit-test app.

    The shared unit conftest builds a deliberately small app for the costing
    engine and creates only the tables it registers; re-running create_all
    once the modules above are imported adds the four document tables and the
    label pool without disturbing what is already there.
    """
    db.create_all()
    return app


def _sale(month, subtotal, discount=0.0, charges=0.0, tax=0.0,
          status="approved", label_id=None, year=2026, n=[0]):
    from inventory_app.models.invoice import InvInvoice
    n[0] += 1
    row = InvInvoice(invoice_number=f"S{n[0]}", voucher_number=f"VS{n[0]}",
                     customer_id=1, label_id=label_id,
                     invoice_date=datetime(year, month, 15),
                     voucher_status=status, subtotal=subtotal,
                     total_discount=discount, total_charges=charges,
                     total_tax=tax, total_amount=subtotal + tax)
    db.session.add(row)
    db.session.commit()
    return row


def _purchase(month, subtotal, discount=0.0, expenses=0.0, tax=0.0,
              status="approved", label_id=None, year=2026, n=[0]):
    from inventory_app.models.purchase_invoice import InvPurchaseInvoice
    n[0] += 1
    row = InvPurchaseInvoice(invoice_number=f"P{n[0]}", voucher_number=f"VP{n[0]}",
                             supplier_id=1, label_id=label_id,
                             invoice_date=datetime(year, month, 10),
                             status=status, subtotal=subtotal,
                             total_discount=discount, total_expenses=expenses,
                             total_tax=tax, total_amount=subtotal + tax)
    db.session.add(row)
    db.session.commit()
    return row


def _sales_return(month, gross, invoice_id, discount=0.0, charges=0.0,
                  status="approved", year=2026, n=[0]):
    from inventory_app.models.sales_return import InvSalesReturn
    n[0] += 1
    row = InvSalesReturn(return_number=f"SR{n[0]}", original_invoice_id=invoice_id,
                         customer_id=1, return_date=datetime(year, month, 20),
                         status=status, gross_return_value=gross,
                         total_discount=discount, total_charges=charges)
    db.session.add(row)
    db.session.commit()
    return row


# ── Basis ───────────────────────────────────────────────────────────────────

class TestBasis:
    def test_revenue_is_net_of_tax(self, docs):
        """Sales tax is the revenue authority's money, never income."""
        _sale(3, subtotal=1000.0, tax=170.0)
        d = perf.performance(year=2026)
        assert d["totals"]["revenue"] == 1000.0

    def test_revenue_is_net_of_discount_and_carries_charges(self, docs):
        _sale(3, subtotal=1000.0, discount=100.0, charges=50.0, tax=170.0)
        d = perf.performance(year=2026)
        assert d["totals"]["revenue"] == 950.0

    def test_purchases_net_of_discount_and_carry_expenses(self, docs):
        """Freight/loading are absorbed into what the goods cost."""
        _purchase(3, subtotal=600.0, discount=50.0, expenses=25.0, tax=102.0)
        d = perf.performance(year=2026)
        assert d["totals"]["purchases"] == 575.0

    def test_gross_profit_is_revenue_less_purchases(self, docs):
        _sale(4, subtotal=1000.0)
        _purchase(4, subtotal=400.0)
        d = perf.performance(year=2026)
        assert d["totals"]["gross"] == 600.0
        assert d["months"][3]["gross"] == 600.0

    def test_drafts_are_excluded(self, docs):
        """An unapproved invoice posts no journal, so it is not performance."""
        _sale(5, subtotal=1000.0, status="unapproved")
        _purchase(5, subtotal=400.0, status="unapproved")
        d = perf.performance(year=2026)
        assert d["totals"]["revenue"] == 0.0
        assert d["totals"]["purchases"] == 0.0

    def test_approved_return_comes_off_revenue(self, docs):
        inv = _sale(6, subtotal=1000.0)
        _sales_return(6, gross=250.0, invoice_id=inv.id)
        d = perf.performance(year=2026)
        assert d["totals"]["revenue"] == 750.0

    def test_unapproved_return_does_not(self, docs):
        inv = _sale(6, subtotal=1000.0)
        _sales_return(6, gross=250.0, invoice_id=inv.id, status="unapproved")
        d = perf.performance(year=2026)
        assert d["totals"]["revenue"] == 1000.0

    def test_a_return_lands_in_its_own_month(self, docs):
        """A January sale returned in March dents March, not January."""
        inv = _sale(1, subtotal=1000.0)
        _sales_return(3, gross=400.0, invoice_id=inv.id)
        d = perf.performance(year=2026)
        assert d["months"][0]["revenue"] == 1000.0
        assert d["months"][2]["revenue"] == -400.0


# ── Margin, deltas, years ───────────────────────────────────────────────────

class TestHeadlines:
    def test_margin_is_a_percentage_of_revenue(self, docs):
        _sale(2, subtotal=1000.0)
        _purchase(2, subtotal=400.0)
        assert perf.performance(year=2026)["totals"]["margin"] == 60.0

    def test_no_revenue_means_no_margin_rather_than_zero(self, docs):
        """Dividing by zero revenue would print a number that means nothing."""
        _purchase(2, subtotal=400.0)
        assert perf.performance(year=2026)["totals"]["margin"] is None

    def test_delta_compares_against_the_prior_year(self, docs):
        _sale(5, subtotal=1000.0, year=2025)
        _sale(5, subtotal=1500.0, year=2026)
        d = perf.performance(year=2026)
        assert d["prev"]["revenue"] == 1000.0
        assert d["deltas"]["revenue"] == pytest.approx(50.0)

    def test_growth_from_nothing_has_no_percentage(self, docs):
        _sale(5, subtotal=1500.0, year=2026)
        assert perf.performance(year=2026)["deltas"]["revenue"] is None

    def test_available_years_lists_only_years_with_approved_docs(self, docs):
        _sale(1, subtotal=100.0, year=2024)
        _sale(1, subtotal=100.0, year=2026, status="unapproved")
        _purchase(1, subtotal=100.0, year=2025)
        assert perf.available_years() == [2025, 2024]

    def test_year_defaults_to_the_most_recent_with_data(self, docs):
        _sale(1, subtotal=100.0, year=2024)
        _sale(1, subtotal=300.0, year=2025)
        assert perf.performance()["year"] == 2025

    def test_empty_company_still_returns_a_full_year(self, docs):
        d = perf.performance(year=2026)
        assert len(d["months"]) == 12
        assert d["totals"]["revenue"] == 0.0


# ── Label filter ────────────────────────────────────────────────────────────

class TestLabelFilter:
    def _labels(self):
        from shared.models.project_label import ProjectLabel
        a = ProjectLabel(name="Alpha", is_active=True)
        b = ProjectLabel(name="Beta", is_active=True)
        db.session.add_all([a, b])
        db.session.commit()
        return a, b

    def test_filter_selects_only_that_label(self, docs):
        a, b = self._labels()
        _sale(3, subtotal=1000.0, label_id=a.id)
        _sale(3, subtotal=400.0, label_id=b.id)
        assert perf.performance(year=2026, label_id=a.id)["totals"]["revenue"] == 1000.0
        assert perf.performance(year=2026, label_id=b.id)["totals"]["revenue"] == 400.0

    def test_no_filter_is_every_label_plus_the_unlabelled(self, docs):
        a, _b = self._labels()
        _sale(3, subtotal=1000.0, label_id=a.id)
        _sale(3, subtotal=250.0, label_id=None)
        assert perf.performance(year=2026)["totals"]["revenue"] == 1250.0

    def test_a_return_inherits_its_invoices_label(self, docs):
        """Returns carry no label of their own. If the filter missed them a
        labelled view would show the sale but not its credit note, and
        overstate that label's revenue."""
        a, b = self._labels()
        inv = _sale(3, subtotal=1000.0, label_id=a.id)
        _sales_return(4, gross=300.0, invoice_id=inv.id)
        assert perf.performance(year=2026, label_id=a.id)["totals"]["revenue"] == 700.0
        assert perf.performance(year=2026, label_id=b.id)["totals"]["revenue"] == 0.0


# ── Chart geometry ──────────────────────────────────────────────────────────

class TestChartGeometry:
    def test_twelve_points_per_series_spanning_the_plot(self, docs):
        geo = perf.chart(perf.performance(year=2026))
        assert len(geo["series"]) == 3
        for s in geo["series"]:
            xs = [float(p.split(",")[0]) for p in s["points"].split()]
            assert len(xs) == 12
            assert xs[0] == pytest.approx(geo["pad_l"])
            assert xs[-1] == pytest.approx(geo["plot_r"])

    def test_the_tallest_value_stays_inside_the_plot(self, docs):
        """A point above the box is a number the chart is lying about."""
        _sale(7, subtotal=987654.0)
        geo = perf.chart(perf.performance(year=2026))
        for s in geo["series"]:
            ys = [float(p.split(",")[1]) for p in s["points"].split()]
            assert min(ys) >= geo["pad_t"] - 0.01
            assert max(ys) <= geo["plot_b"] + 0.01

    def test_axis_ticks_are_round_numbers(self, docs):
        _sale(7, subtotal=987654.0)
        geo = perf.chart(perf.performance(year=2026))
        steps = {round(geo["ticks"][i + 1]["v"] - geo["ticks"][i]["v"], 6)
                 for i in range(len(geo["ticks"]) - 1)}
        assert len(steps) == 1, "gridlines must be evenly spaced"
        step = steps.pop()
        assert step > 0
        # 1/2/2.5/5 x a power of ten — the numbers a reader can subtract.
        mantissa = step / (10 ** (len(str(int(step))) - 1))
        assert mantissa in (1.0, 2.0, 2.5, 5.0), f"ugly step {step}"

    def test_a_loss_month_puts_the_zero_line_inside_the_plot(self, docs):
        """Purchases above revenue is a real month; the axis has to show it."""
        _purchase(8, subtotal=5000.0)
        _sale(8, subtotal=1000.0)
        d = perf.performance(year=2026)
        assert d["months"][7]["gross"] == -4000.0
        geo = perf.chart(d)
        assert geo["pad_t"] < geo["zero_y"] < geo["plot_b"]

    def test_every_series_has_a_css_variable(self, docs):
        geo = perf.chart(perf.performance(year=2026))
        assert [s["var"] for s in geo["series"]] == ["rev", "pur", "gp"]

    def test_tooltip_payload_carries_formatted_values(self, docs):
        _sale(9, subtotal=1234567.0)
        d = perf.performance(year=2026)
        geo = perf.chart(d)
        from shared.formatting import format_amount
        payload = perf.chart_json(d, geo, format_amount)
        assert len(payload["cols"]) == 12
        sept = payload["series"][0]["dots"][8]
        assert "," in sept["text"], "the tooltip prints unformatted numbers"
