"""Back-dated documents, deletions and edits: costing by document date.

Every scenario keys documents out of date order — the way they really arrive —
and checks three things: the issue costs that result, that the layers still tie
to the stock ledger, and that every re-costed issue was journalled for the
exact difference (so the general ledger follows the stock valuation).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from shared.extensions import db
from shared import costing
from shared.costing import NegativeStockError
from shared.models.ledger import JournalEntry, JournalLine
from shared.models.stock_ledger import StockLedger
from shared.models.stock_layer import StockCostAdjustment

TODAY = date.today()


def day(n):
    """``n`` days ago."""
    return TODAY - timedelta(days=n)


def buy(qty, cost, n, when):
    return costing.record_in(1, "PI", n, f"PI-{n:05d}", qty=qty, unit_cost=cost,
                             txn_date=when)


def sell(qty, n, when, vtype="SI"):
    return costing.record_out(1, vtype, n, f"{vtype}-{n:05d}", qty=qty,
                              txn_date=when)


def cost_of(vtype, n):
    return StockLedger.query.filter_by(voucher_type=vtype, voucher_id=n).one().total_cost


def ties():
    ok, layers, ledger = costing.assert_invariant(1)
    assert ok, f"layers {layers} != ledger {ledger}"


def adjustment_journal_total():
    """Net debit the cost-adjustment journals put on the counter accounts."""
    total = Decimal("0")
    for adj in StockCostAdjustment.query.all():
        total += Decimal(str(adj.delta))
        je = db.session.get(JournalEntry, adj.journal_entry_id)
        assert je is not None and je.is_posted
        dr = sum(Decimal(str(l.debit)) for l in je.lines)
        cr = sum(Decimal(str(l.credit)) for l in je.lines)
        assert dr == cr, "adjustment journal must balance"
    return total


@pytest.fixture
def fifo(settings):
    settings.valuation_method = "fifo"
    db.session.commit()
    return settings


# ─────────────────────────────────────────────
# Back-dated additions
# ─────────────────────────────────────────────

def test_rows_carry_their_document_date(settings, product):
    buy(10, 10, 1, day(30))
    assert StockLedger.query.one().txn_date == day(30)


def test_backdated_purchase_recosts_later_fifo_sale(fifo, product):
    """Buy 10 @ 20 on day -10, sell 10 on day -5 (cost 200). A purchase of
    10 @ 10 dated day -20 is keyed afterwards. In date order the sale takes the
    older, cheaper layer: its cost is re-stated to 100 and journalled."""
    buy(10, 20, 2, day(10))
    _u, cogs = sell(10, 1, day(5))
    assert cogs == Decimal("200.00")

    buy(10, 10, 1, day(20))
    db.session.commit()

    assert cost_of("SI", 1) == Decimal("100.00")
    assert costing.layers_remaining(1) == [(Decimal("20.0000"), Decimal("10.0000"))]
    assert costing.stock_value(1) == Decimal("200.00")
    ties()
    assert adjustment_journal_total() == Decimal("-100.00")


def test_backdated_purchase_reaverages_later_wa_sale(settings, product):
    """WA: buy 10 @ 20, sell 5 (cost 100). A purchase of 10 @ 10 dated
    before the sale makes the pool 20 @ 15 at the sale: cost 75."""
    buy(10, 20, 1, day(10))
    _u, cogs = sell(5, 1, day(5))
    assert cogs == Decimal("100.00")

    buy(10, 10, 2, day(7))
    db.session.commit()

    assert cost_of("SI", 1) == Decimal("75.00")
    assert costing.on_hand(1) == 15
    assert costing.stock_value(1) == Decimal("225.00")
    ties()


def test_backdated_purchase_after_every_sale_changes_nothing(fifo, product):
    buy(10, 10, 1, day(10))
    sell(5, 1, day(5))
    buy(10, 30, 2, day(1))        # after the sale in date order
    assert cost_of("SI", 1) == Decimal("50.00")
    assert StockCostAdjustment.query.count() == 0
    ties()


def test_backdated_sale_is_costed_at_its_own_date(fifo, product):
    """Buy 10 @ 10 (day -20), buy 10 @ 30 (day -5), sell 10 today -> cost
    100 (oldest layer). Now a sale of 10 dated day -10 is keyed: on its date
    only the 10 @ 10 layer existed, so it costs 100 and today's sale is
    re-costed to the 30 layer (300)."""
    buy(10, 10, 1, day(20))
    buy(10, 30, 2, day(5))
    sell(10, 2, day(0))
    assert cost_of("SI", 2) == Decimal("100.00")

    _u, cogs = sell(10, 1, day(10))
    db.session.commit()

    assert cogs == Decimal("100.00"), "the back-dated sale draws what existed then"
    assert cost_of("SI", 2) == Decimal("300.00")
    assert costing.on_hand(1) == 0
    assert costing.stock_value(1) == 0
    ties()
    assert adjustment_journal_total() == Decimal("200.00")


def test_backdated_sale_refused_when_stock_was_not_on_hand_then(fifo, product):
    """Stock is on hand today, but it arrived after the sale's date."""
    buy(10, 10, 1, day(5))
    with pytest.raises(NegativeStockError, match="on hand at that date"):
        sell(3, 1, day(10))
    db.session.rollback()


def test_backdated_sale_refused_when_it_would_strip_a_later_sale(fifo, product):
    """Buy 10 (day -20), sell 8 (day -5). A sale of 5 dated day -10 fits on its
    own date, but then the day -5 sale would be left 3 short."""
    buy(10, 10, 1, day(20))
    sell(8, 2, day(5))
    with pytest.raises(NegativeStockError, match="would be left"):
        sell(5, 1, day(10))
    db.session.rollback()


def test_backdated_sale_allowed_short_when_negative_stock_enabled(fifo, product):
    fifo.allow_negative_stock = True
    db.session.commit()
    buy(10, 10, 1, day(5))
    _u, cogs = sell(3, 1, day(10))
    assert cogs == Decimal("30.00"), "short units carry the last known cost"
    assert costing.on_hand(1) == 7
    ties()


# ─────────────────────────────────────────────
# Deletions (reversals) in the middle of history
# ─────────────────────────────────────────────

def test_deleting_a_middle_sale_recosts_the_later_one(fifo, product):
    """Buy 10 @ 10, buy 10 @ 20, sell 10 (100), sell 10 (200). Deleting the
    first sale lets the second take the cheap layer: 200 -> 100."""
    buy(10, 10, 1, day(30))
    buy(10, 20, 2, day(25))
    sell(10, 1, day(20))
    sell(10, 2, day(10))
    assert cost_of("SI", 2) == Decimal("200.00")

    costing.reverse_voucher_stock("SI", 1)
    db.session.commit()

    assert cost_of("SI", 2) == Decimal("100.00")
    assert costing.layers_remaining(1) == [(Decimal("20.0000"), Decimal("10.0000"))]
    ties()
    assert adjustment_journal_total() == Decimal("-100.00")


def test_deleting_the_latest_document_touches_nothing_else(fifo, product):
    buy(10, 10, 1, day(30))
    sell(4, 1, day(20))
    sell(3, 2, day(10))
    costing.reverse_voucher_stock("SI", 2)
    assert cost_of("SI", 1) == Decimal("40.00")
    assert StockCostAdjustment.query.count() == 0
    assert costing.on_hand(1) == 6
    ties()


def test_deleting_a_receipt_a_later_sale_needs_is_refused(fifo, product):
    buy(10, 10, 1, day(30))
    sell(5, 1, day(10))
    with pytest.raises(costing.ConsumedLayerError):
        costing.reverse_voucher_stock("PI", 1)


# ─────────────────────────────────────────────
# Edits: unapprove -> change -> re-approve on the original date
# ─────────────────────────────────────────────

def test_editing_an_old_purchase_price_flows_to_every_later_issue(fifo, product):
    """A purchase of 10 @ 10 (day -30) fed a sale (day -20) and a consumption
    (day -10). The supplier's invoice was really 15. Unapprove, correct,
    re-approve: both issues are re-costed at 15 and each difference is
    journalled to its own account."""
    buy(10, 10, 1, day(30))
    sell(4, 1, day(20))
    sell(2, 1, day(10), vtype="CONS")

    costing.reverse_voucher_stock("PI", 1, allow_variance=True)
    buy(10, 15, 1, day(30))
    db.session.commit()

    assert cost_of("SI", 1) == Decimal("60.00")
    assert cost_of("CONS", 1) == Decimal("30.00")
    assert costing.stock_value(1) == Decimal("60.00")
    ties()
    assert adjustment_journal_total() == Decimal("30.00")   # +20 sale, +10 cons


def test_editing_an_old_purchase_quantity_below_what_was_issued_is_refused(fifo, product):
    buy(10, 10, 1, day(30))
    sell(8, 1, day(20))
    costing.reverse_voucher_stock("PI", 1, allow_variance=True)
    with pytest.raises(NegativeStockError):
        buy(5, 10, 1, day(30))      # 5 can never have covered the sale of 8
    db.session.rollback()


# ─────────────────────────────────────────────
# Returns follow the sale they reverse
# ─────────────────────────────────────────────

def test_sales_return_follows_its_recosted_sale(fifo, product, monkeypatch):
    buy(10, 20, 2, day(10))
    sell(5, 1, day(5))                                  # cost 100 @ 20
    costing.record_in(1, "SRV", 7, "SRV-00007", qty=2, unit_cost=20,
                      txn_date=day(3))
    monkeypatch.setattr(costing, "_resolve_in_cost",
                        lambda row: costing.original_issue_cost("SI", 1, 1))

    buy(10, 10, 1, day(20))                             # back-dated, cheaper
    db.session.commit()

    assert cost_of("SI", 1) == Decimal("50.00")
    assert cost_of("SRV", 7) == Decimal("20.00"), "returns at the re-costed 10"
    ties()


# ─────────────────────────────────────────────
# Reports by document date
# ─────────────────────────────────────────────

def test_on_hand_and_value_as_of_a_past_date(fifo, product):
    buy(10, 10, 1, day(30))
    sell(4, 1, day(20))
    buy(5, 12, 2, day(10))
    assert costing.on_hand_at(1, day(25)) == 10
    assert costing.value_at(1, day(25)) == Decimal("100.00")
    assert costing.on_hand_at(1, day(15)) == 6
    assert costing.value_at(1, day(15)) == Decimal("60.00")
    assert costing.on_hand_at(1, TODAY) == 11
    assert costing.value_at(1, TODAY) == Decimal("120.00")


# ─────────────────────────────────────────────
# Adjustment dating
# ─────────────────────────────────────────────

def test_adjustment_posts_in_the_issue_period(fifo, product):
    buy(10, 20, 2, day(10))
    sell(10, 1, day(5))
    buy(10, 10, 1, day(20))
    adj = StockCostAdjustment.query.one()
    assert adj.entry_date == day(5)
    je = db.session.get(JournalEntry, adj.journal_entry_id)
    assert je.entry_date.date() == day(5)


def test_adjustment_moves_to_today_when_issue_period_is_closed(fifo, product):
    from shared.models.company_settings import AccountingPeriod
    buy(10, 20, 2, day(40))
    sell(10, 1, day(35))
    closed = AccountingPeriod(fiscal_year="FY", period_name="Closed",
                              start_date=day(36),
                              end_date=day(34), is_closed=True)
    db.session.add(closed)
    db.session.commit()

    buy(10, 10, 1, day(50))
    adj = StockCostAdjustment.query.one()
    assert adj.entry_date == TODAY, "a closed period's figures are final"
