"""Costing engine: cost accuracy, immutability of posted cost, and the
layer/ledger invariant that keeps inventory tied to COGS.

The scenario these are built around is a product bought at several prices
over time, sold at several prices, and scrapped or charged to an employee —
with the valuation method switched partway and a historic voucher deleted.
"""

from decimal import Decimal

import pytest

from shared.extensions import db
from shared import costing
from shared.costing import NegativeStockError
from shared.models.stock_ledger import StockLedger
from shared.models.stock_layer import StockLayer, LayerConsumption


def buy(qty, unit_cost, n=1):
    return costing.record_in(1, "PI", n, f"PI-{n:05d}", qty=qty, unit_cost=unit_cost)


def issue(qty, n=1, vtype="SI", **kw):
    return costing.record_out(1, vtype, n, f"{vtype}-{n:05d}", qty=qty, **kw)


def book_value():
    _qty, cost, _avg = StockLedger.get_running_balance(1)
    return Decimal(str(cost))


def assert_ties(msg=""):
    """Layers must always back the ledger; drift is money invented or lost."""
    ok, layer_value, running_cost = costing.assert_invariant(1)
    assert ok, (f"{msg}: layers value {layer_value} != ledger running_cost "
                f"{running_cost} — inventory no longer ties to COGS")


# ─────────────────────────────────────────────
# Cost accuracy across multiple prices
# ─────────────────────────────────────────────

def test_weighted_average_issues_at_running_average(settings, product):
    buy(10, 10, n=1)          # 100
    buy(10, 20, n=2)          # 200 -> 20 units / 300 / avg 15
    unit, total = issue(10)
    assert unit == Decimal("15.0000")
    assert total == Decimal("150.00")
    assert book_value() == Decimal("150.0000")
    assert_ties("after WA issue")


def test_weighted_average_reaverages_on_each_receipt(settings, product):
    buy(10, 10, n=1)
    assert costing.current_unit_cost(1) == Decimal("10.0000")
    buy(30, 20, n=2)          # 40 units / 700 -> avg 17.50
    assert costing.current_unit_cost(1) == Decimal("17.5000")
    # One pool under weighted average, never a queue of layers.
    assert len(costing.layers_remaining(1)) == 1
    assert_ties("after re-average")


def test_fifo_issues_oldest_layer_first(settings, product):
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    unit, total = issue(10)
    assert unit == Decimal("10.0000"), "FIFO must take the oldest layer"
    assert total == Decimal("100.00")
    assert costing.layers_remaining(1) == [(Decimal("20.0000"), Decimal("10.0000"))]
    assert_ties("after FIFO issue")


def test_fifo_issue_spanning_layers_blends_cost(settings, product):
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    unit, total = issue(15)   # 10 @ 10 + 5 @ 20 = 200 over 15 units
    assert total == Decimal("200.00")
    assert unit == Decimal("13.3333")
    assert_ties("after spanning issue")


def test_scrap_and_consumption_issue_at_historic_cost(settings, product):
    buy(10, 10, n=1)
    buy(10, 20, n=2)          # avg 15
    unit, total = issue(4, n=1, vtype="SCRAP")
    assert unit == Decimal("15.0000")
    assert total == Decimal("60.00")
    unit, total = issue(4, n=1, vtype="CONS")
    assert unit == Decimal("15.0000")
    assert_ties("after scrap + consumption")


# ─────────────────────────────────────────────
# Switching valuation method
# ─────────────────────────────────────────────

def test_method_switch_preserves_book_value(settings, product):
    """The original defect: buy at two prices, sell under WA, switch to FIFO.

    The old engine re-derived FIFO layers by replaying OUT quantities against
    IN rows, so it "saw" the untouched 10 @ 20 layer (value 200) even though
    the books said 150 — then charged 200 to COGS, expensing 350 against
    purchases of 300.
    """
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    _u, first_cogs = issue(10)                 # WA: 10 @ 15 = 150
    assert first_cogs == Decimal("150.00")
    assert book_value() == Decimal("150.0000")

    costing.revalue_for_method_change("fifo")
    settings.valuation_method = "fifo"
    db.session.commit()

    assert costing.stock_value(1) == Decimal("150.0000"), \
        "revaluation must carry stock at book value, not re-derive it"
    assert_ties("immediately after switch to FIFO")

    _u, second_cogs = issue(10, n=2)
    assert second_cogs == Decimal("150.00"), \
        "the remaining 10 units are worth 150, whatever the method"

    purchases = Decimal("300.00")
    assert first_cogs + second_cogs == purchases, \
        "total COGS must equal total purchases once stock is exhausted"
    assert costing.on_hand(1) == 0
    assert book_value() == 0


def test_method_switch_does_not_change_already_posted_costs(settings, product):
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    issue(10)
    posted = [(r.id, r.unit_cost, r.total_cost)
              for r in StockLedger.query.order_by(StockLedger.id).all()]

    costing.revalue_for_method_change("fifo")
    settings.valuation_method = "fifo"
    db.session.commit()

    after = [(r.id, r.unit_cost, r.total_cost)
             for r in StockLedger.query.order_by(StockLedger.id).all()]
    assert after == posted, "a method switch must never restate a posted cost"


def test_fifo_to_weighted_average_collapses_layers_at_book_value(settings, product):
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    assert len(costing.layers_remaining(1)) == 2

    costing.revalue_for_method_change("weighted_average")
    settings.valuation_method = "weighted_average"
    db.session.commit()

    layers = costing.layers_remaining(1)
    assert len(layers) == 1, "weighted average holds a single pool"
    assert layers[0] == (Decimal("15.0000"), Decimal("20.0000"))
    assert_ties("after FIFO -> WA collapse")


def test_ledger_rows_record_the_method_that_priced_them(settings, product):
    buy(10, 10, n=1)
    issue(5)
    costing.revalue_for_method_change("fifo")
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 20, n=2)
    issue(5, n=2)

    rows = StockLedger.query.order_by(StockLedger.id).all()
    assert [r.valuation_method for r in rows] == [
        "weighted_average", "weighted_average", "fifo", "fifo"]


# ─────────────────────────────────────────────
# Immutability of a posted charge
# ─────────────────────────────────────────────

def test_employee_receivable_survives_later_activity(settings, product):
    """Charge an employee for a damaged unit, then keep trading the product.

    The agreed receivable must never move: it was conveyed to a person.
    """
    buy(10, 10, n=1)
    charged_unit, charged_total = issue(1, n=1, vtype="SCRAP")
    assert charged_total == Decimal("10.00")

    scrap_row = StockLedger.query.filter_by(voucher_type="SCRAP").one()

    buy(50, 99, n=2)          # wildly different price
    issue(20, n=2)
    costing.revalue_for_method_change("fifo")
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(5, 3, n=3)
    issue(2, n=3, vtype="CONS")

    db.session.refresh(scrap_row)
    assert scrap_row.unit_cost == charged_unit
    assert scrap_row.total_cost == charged_total, \
        "the employee's agreed receivable moved after later activity"


def test_consumption_records_which_purchases_backed_the_charge(settings, product):
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    issue(15, n=1, vtype="CONS")   # eats all of layer 1 and half of layer 2

    out_row = StockLedger.query.filter_by(voucher_type="CONS").one()
    cons = LayerConsumption.query.filter_by(out_ledger_id=out_row.id).all()
    assert len(cons) == 2, "an issue spanning two layers records both"
    assert sum(c.total_cost for c in cons) == out_row.total_cost, \
        "the audit trail must add up to the posted cost"


# ─────────────────────────────────────────────
# Negative stock
# ─────────────────────────────────────────────

def test_issuing_more_than_on_hand_is_refused(settings, product):
    buy(5, 10, n=1)
    with pytest.raises(NegativeStockError, match="only"):
        issue(10)
    assert costing.on_hand(1) == 5, "the refused issue must not move stock"
    assert_ties("after refused issue")


def test_negative_stock_allowed_when_configured(settings, product):
    settings.allow_negative_stock = True
    db.session.commit()
    buy(5, 10, n=1)
    unit, total = issue(10)
    assert unit == Decimal("10.0000"), "uncovered units fall back to last cost"
    assert costing.on_hand(1) == -5
    assert_ties("after an over-issue with negative stock allowed")


def test_over_issue_carries_its_cost_as_a_short_layer(settings, product):
    """The uncovered value used to be dropped: the ledger kept the 30 of cost
    posted for stock that was never bought, while the pool lost it — every
    later receipt then built on a diverged base."""
    settings.allow_negative_stock = True
    db.session.commit()
    buy(5, 10, n=1)
    issue(8, n=1)                     # 5 covered + 3 @ 10 uncovered
    assert_ties("after an over-issue")

    costing.reverse_voucher_stock("SI", 1)
    db.session.commit()
    assert costing.on_hand(1) == 5
    assert_ties("after reversing the over-issue")


@pytest.mark.parametrize("method", ["weighted_average", "fifo"])
def test_receipt_covers_an_open_short_before_opening_stock(settings, product, method):
    """A receipt after an over-issue must first fill the short. Otherwise the
    positive layers hold more units than the ledger has on hand: a later issue
    is costed against phantom stock, the negative-stock guard stops seeing the
    deficit, and emptying the ledger strands the short's value on the layers.
    """
    settings.valuation_method = method
    settings.allow_negative_stock = True
    db.session.commit()
    buy(5, 10, n=1)
    issue(8, n=1)                     # 3 short @ 10 -> ledger -3 / -30
    buy(10, 12, n=2)                  # ledger 7 / 90
    assert_ties("after a receipt over a short")
    assert sum(q for _c, q in costing.layers_remaining(1)) == costing.on_hand(1) == 7

    settings.allow_negative_stock = False
    db.session.commit()
    with pytest.raises(NegativeStockError):
        issue(8, n=2)                 # only 7 on hand, guard must still hold

    issue(7, n=3)                     # empty the ledger exactly
    assert costing.on_hand(1) == 0
    assert_ties("after emptying stock that once covered a short")


@pytest.mark.parametrize("method", ["weighted_average", "fifo"])
def test_reversing_a_receipt_that_covered_a_short_reopens_it(settings, product, method):
    """Three of the ten received units filled an issue already posted, so a
    plain reversal is refused like any consumed receipt; forced through with
    a variance, the short reopens and the pool still ties."""
    settings.valuation_method = method
    settings.allow_negative_stock = True
    db.session.commit()
    buy(2, 10, n=1)
    issue(5, n=1)                     # 3 short @ 10
    buy(10, 12, n=2)
    with pytest.raises(costing.ConsumedLayerError):
        costing.reverse_voucher_stock("PI", 2)

    costing.reverse_voucher_stock("PI", 2, allow_variance=True)
    db.session.commit()
    assert costing.on_hand(1) == -3
    assert sum(q for _c, q in costing.layers_remaining(1)) == 0
    assert_ties("after reversing the covering receipt")

    buy(4, 10, n=3)                   # the reopened short is covered again
    assert costing.on_hand(1) == 1
    assert sum(q for _c, q in costing.layers_remaining(1)) == 1
    assert_ties("after re-covering the short")


def test_reversing_an_over_issue_after_its_short_was_covered(settings, product):
    settings.valuation_method = "fifo"
    settings.allow_negative_stock = True
    db.session.commit()
    buy(2, 10, n=1)
    issue(5, n=1)                     # 3 short @ 10
    buy(10, 12, n=2)                  # covers 3, 7 reach the shelf
    costing.reverse_voucher_stock("SI", 1)
    db.session.commit()
    assert costing.on_hand(1) == 12
    assert sum(q for _c, q in costing.layers_remaining(1)) == 12
    assert_ties("after reversing the issue that opened the short")
    # No layer may point at the deleted issue row.
    assert StockLayer.query.filter(StockLayer.source_ledger_id.notin_(
        [r.id for r in StockLedger.query.all()])).count() == 0


def test_record_in_refuses_non_positive_quantities(settings, product):
    with pytest.raises(ValueError, match="must be positive"):
        costing.record_in(1, "PI", 1, "PI-00001", qty=0, unit_cost=10)
    with pytest.raises(ValueError, match="must be positive"):
        costing.record_in(1, "PI", 1, "PI-00001", qty=-5, unit_cost=10)
    assert_ties("after refused receipts")


def test_wa_receipt_reversal_refuses_stranded_posted_value(settings, product):
    """Weighted average, default method: buy 10 @ 10 and 10 @ 20, sell 10 at
    the 15 average, then delete the 10 @ 20 purchase. Enough units remain, so
    the quantity guard passes — but 150 of posted COGS would be left backed
    by only 100 of surviving purchases. Refuse; allow_variance stays the way
    out."""
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    issue(10, n=1)                    # COGS 150

    with pytest.raises(costing.ConsumedLayerError, match="already been issued"):
        costing.reverse_voucher_stock("PI", 2)

    assert costing.on_hand(1) == 10, "the refused reversal must not move stock"
    assert_ties("after refused WA reversal")


# ─────────────────────────────────────────────
# Reversal
# ─────────────────────────────────────────────

def test_reversing_an_issue_gives_back_the_layer_quantity(settings, product):
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    issue(10, n=1)
    assert costing.layers_remaining(1) == [(Decimal("20.0000"), Decimal("10.0000"))]

    costing.reverse_voucher_stock("SI", 1)
    db.session.commit()

    assert costing.layers_remaining(1) == [(Decimal("10.0000"), Decimal("10.0000")),
                                           (Decimal("20.0000"), Decimal("10.0000"))]
    assert costing.on_hand(1) == 20
    assert_ties("after reversing an issue")
    assert LayerConsumption.query.count() == 0


def test_reversing_a_receipt_withdraws_its_layer(settings, product):
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)

    costing.reverse_voucher_stock("PI", 2)
    db.session.commit()

    assert costing.layers_remaining(1) == [(Decimal("10.0000"), Decimal("10.0000"))]
    assert costing.on_hand(1) == 10
    assert_ties("after reversing a receipt")


def test_reversing_a_consumed_receipt_is_refused(settings, product):
    """Deleting a purchase whose stock was already issued.

    The issue posted a COGS of 100 drawn from this receipt. Withdrawing the
    receipt would leave that frozen 100 backed by a purchase that no longer
    exists, with the quantity silently re-drawn from the 20-cost layer. The
    old engine allowed it and drove running_cost to -200 on 0 units.
    """
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    issue(10, n=1)            # eats layer 1 entirely

    with pytest.raises(costing.ConsumedLayerError, match="already been issued"):
        costing.reverse_voucher_stock("PI", 1)

    assert costing.on_hand(1) == 10, "the refused reversal must not move stock"
    assert_ties("after refused reversal")


def test_consumed_receipt_reversible_once_its_issue_is_reversed(settings, product):
    """The documented way out: reverse the dependent issue, then the receipt."""
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    issue(10, n=1)

    costing.reverse_voucher_stock("SI", 1)     # give the quantity back first
    db.session.commit()
    costing.reverse_voucher_stock("PI", 1)     # now the layer is untouched
    db.session.commit()

    assert costing.layers_remaining(1) == [(Decimal("20.0000"), Decimal("10.0000"))]
    assert costing.on_hand(1) == 10
    assert_ties("after reversing issue then receipt")


def test_reversing_a_merged_weighted_average_receipt_ties(settings, product):
    """Weighted-average receipts merge into the pool instead of opening a layer.

    Reversal has no layer to withdraw by source_ledger_id, so the pool has to
    be re-pointed at the ledger — otherwise the ledger drops the value and the
    layer keeps it (a reversed 10 @ 20 left a layer worth 300 against a
    ledger of 100).
    """
    buy(10, 10, n=1)
    buy(10, 20, n=2)          # merges -> one pool of 20 @ 15
    assert len(costing.layers_remaining(1)) == 1

    costing.reverse_voucher_stock("PI", 2)
    db.session.commit()

    assert costing.on_hand(1) == 10
    assert costing.layers_remaining(1) == [(Decimal("10.0000"), Decimal("10.0000"))], \
        "the pool must fall back to the surviving receipt's cost"
    assert_ties("after reversing a merged WA receipt")


def test_reversing_a_consumed_weighted_average_receipt_is_refused(settings, product):
    """WA stock is fungible, so no layer records who consumed the receipt.

    Withdrawing more than remains on hand necessarily takes back units already
    issued at a now-frozen cost. Unrefused, this drove stock to -5.
    """
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    issue(15, n=1)            # 5 left on hand; PI-2 brought in 10

    with pytest.raises(costing.ConsumedLayerError, match="remain on hand"):
        costing.reverse_voucher_stock("PI", 2)

    assert costing.on_hand(1) == 5, "the refused reversal must not move stock"
    assert_ties("after refused WA reversal")


def test_reversing_an_issue_under_weighted_average_ties(settings, product):
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    issue(8, n=1)

    costing.reverse_voucher_stock("SI", 1)
    db.session.commit()

    assert costing.on_hand(1) == 20
    assert costing.layers_remaining(1) == [(Decimal("15.0000"), Decimal("20.0000"))]
    assert_ties("after reversing a WA issue")


# ─────────────────────────────────────────────
# Sales returns: goods coming back from a customer
# ─────────────────────────────────────────────

def test_original_issue_cost_reads_the_frozen_cost(settings, product):
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    _u, cogs = issue(10, n=1)

    assert costing.original_issue_cost("SI", 1, 1) == Decimal("10.0000")
    assert costing.original_issue_cost("SI", 1, 1) * 10 == cogs
    # Today's valuation has moved on; a return must not use it.
    assert costing.current_unit_cost(1) == Decimal("20.0000")


def test_original_issue_cost_is_none_for_a_voucher_that_issued_nothing(settings, product):
    buy(10, 10, n=1)
    assert costing.original_issue_cost("SI", 99, 1) is None


def test_sell_then_return_is_value_neutral(settings, product):
    """The round trip must change nothing.

    Returning at today's valuation (20) rather than the cost it sold at (10)
    would put 200 back for stock that left at 100 — inventing 100 of inventory
    from a sale and its own reversal.
    """
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    _u, cogs = issue(10, n=1)

    basis = costing.original_issue_cost("SI", 1, 1)
    costing.record_in(1, "SRV", 1, "CN-000001", qty=10, unit_cost=basis)
    db.session.commit()

    assert costing.on_hand(1) == 20
    assert costing.stock_value(1) == Decimal("300.0000"), \
        "purchases were 300; a sale and its return must net to zero"
    assert_ties("after sell + return")


def test_returned_goods_form_a_new_layer_at_the_sold_cost(settings, product):
    """A return is a RECEIPT priced at the original cost, not an un-sale.

    It opens a new layer dated now rather than reinstating the layer the sale
    consumed, so later FIFO issues take the older purchase first. This is what
    SAP and NetSuite do: the goods are back in stock as of today, and the
    system cannot know they are the same physical units.
    """
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    issue(10, n=1)                      # eats the 10-cost layer
    basis = costing.original_issue_cost("SI", 1, 1)
    costing.record_in(1, "SRV", 1, "CN-000001", qty=10, unit_cost=basis)
    db.session.commit()

    assert costing.layers_remaining(1) == [(Decimal("20.0000"), Decimal("10.0000")),
                                           (Decimal("10.0000"), Decimal("10.0000"))]
    _u, next_cogs = issue(10, n=2)
    assert next_cogs == Decimal("200.00"), \
        "the 20-cost purchase is older, so FIFO issues it before the return"
    assert_ties("after re-selling")


def test_weighted_average_return_reaverages_at_the_sold_cost(settings, product):
    buy(10, 10, n=1)
    buy(10, 20, n=2)                    # pool 20 @ 15
    _u, cogs = issue(10, n=1)           # 10 @ 15 = 150; pool 10 @ 15
    assert cogs == Decimal("150.00")

    basis = costing.original_issue_cost("SI", 1, 1)
    assert basis == Decimal("15.0000")
    costing.record_in(1, "SRV", 1, "CN-000001", qty=10, unit_cost=basis)
    db.session.commit()

    assert costing.on_hand(1) == 20
    assert costing.current_unit_cost(1) == Decimal("15.0000"), \
        "returning at the cost it left at leaves the average untouched"
    assert costing.stock_value(1) == Decimal("300.0000")
    assert_ties("after WA return")


def test_reversing_a_sales_return_withdraws_the_returned_stock(settings, product):
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    issue(10, n=1)
    basis = costing.original_issue_cost("SI", 1, 1)
    costing.record_in(1, "SRV", 1, "CN-000001", qty=10, unit_cost=basis)
    db.session.commit()
    assert costing.on_hand(1) == 10

    costing.reverse_voucher_stock("SRV", 1)
    db.session.commit()

    assert costing.on_hand(1) == 0
    assert costing.stock_value(1) == 0
    assert_ties("after reversing a sales return")


def test_reversing_a_resold_sales_return_is_refused(settings, product):
    """The returned stock was sold again; that sale's cost came from it."""
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    issue(10, n=1)
    basis = costing.original_issue_cost("SI", 1, 1)
    costing.record_in(1, "SRV", 1, "CN-000001", qty=10, unit_cost=basis)
    issue(10, n=2)                      # re-sold the returned goods

    with pytest.raises(costing.ConsumedLayerError):
        costing.reverse_voucher_stock("SRV", 1)


# ─────────────────────────────────────────────
# Variance: deleting a consumed receipt anyway
# ─────────────────────────────────────────────

def test_variance_lets_a_consumed_receipt_be_reversed(settings, product):
    """The case that is refused without allow_variance.

    Buy 10 @ 10 and 10 @ 20, sell 10 (FIFO: COGS 100 from the first layer),
    then delete the 10 @ 10 purchase. It never happened — but 100 was posted
    against it and conveyed. The 10 units sold must now come out of the 20-cost
    layer, which is worth 200, while the posted COGS stays 100. The 100 gap is
    the variance.
    """
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    _u, cogs = issue(10, n=1)
    assert cogs == Decimal("100.00")

    variances = costing.reverse_voucher_stock("PI", 1, allow_variance=True)
    db.session.commit()

    assert variances[1] == Decimal("100.00"), \
        "200 of surviving purchase, 100 expensed, nothing left = 100 unhomed"
    assert costing.on_hand(1) == 0
    assert costing.stock_value(1) == 0
    assert_ties("after reversing a consumed receipt with a variance")

    sale = StockLedger.query.filter_by(voucher_type="SI").one()
    assert sale.total_cost == cogs, "the posted COGS must not be restated"


def test_variance_writes_a_value_only_ledger_row(settings, product):
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    issue(10, n=1)
    costing.reverse_voucher_stock("PI", 1, allow_variance=True)
    db.session.commit()

    var = StockLedger.query.filter_by(voucher_type="VAR").one()
    assert var.quantity == 0, "a variance moves value, not stock"
    assert var.total_cost == Decimal("100.00")
    assert "no remaining purchase" in var.notes


def test_no_variance_when_the_reversed_receipt_was_untouched(settings, product):
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)

    variances = costing.reverse_voucher_stock("PI", 2, allow_variance=True)
    db.session.commit()

    assert variances == {}, "nothing consumed it, so nothing is unaccounted for"
    assert StockLedger.query.filter_by(voucher_type="VAR").count() == 0
    assert_ties("after a clean reversal under allow_variance")


def test_weighted_average_absorbs_the_gap_into_the_surviving_units(settings, product):
    """Under WA the pool re-averages rather than writing off.

    Buy 10 @ 10 and 10 @ 20 (pool 20 @ 15), sell 5 at 15, then delete the
    10 @ 10 purchase. 200 was bought and 75 expensed, so the 5 units left carry
    125 — an average of 25. The posted 75 does not move; the future re-prices.
    """
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    _u, cogs = issue(5, n=1)
    assert cogs == Decimal("75.00")

    variances = costing.reverse_voucher_stock("PI", 1, allow_variance=True)
    db.session.commit()

    assert variances == {}, "with units left, WA re-averages instead"
    assert costing.on_hand(1) == 5
    assert costing.current_unit_cost(1) == Decimal("25.0000")
    assert_ties("after WA absorbs the gap")

    sale = StockLedger.query.filter_by(voucher_type="SI").one()
    assert sale.total_cost == cogs, "the posted COGS must not be restated"


def test_weighted_average_writes_off_when_no_units_remain(settings, product):
    """With nothing left to absorb the gap, WA must write it off.

    The qty==0 clamp zeroes running_cost, so a variance computed from
    running_cost would read zero here while 50 is genuinely unaccounted for.
    """
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    issue(10, n=1)            # WA: 10 @ 15 = 150 posted

    variances = costing.reverse_voucher_stock("PI", 1, allow_variance=True)
    db.session.commit()

    assert costing.on_hand(1) == 0
    assert variances[1] == Decimal("50.00"), \
        "200 bought, 150 expensed, nothing on hand = 50 unhomed"
    assert_ties("after WA write-off")


def test_reversal_still_refuses_by_default(settings, product):
    """allow_variance is opt-in: the safe path stays the default."""
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    buy(10, 20, n=2)
    issue(10, n=1)

    with pytest.raises(costing.ConsumedLayerError):
        costing.reverse_voucher_stock("PI", 1)


def test_reversal_names_the_vouchers_that_consumed_the_stock(settings, product):
    settings.valuation_method = "fifo"
    db.session.commit()
    buy(10, 10, n=1)
    issue(4, n=1, vtype="CONS")
    issue(3, n=2, vtype="SCRAP")

    with pytest.raises(costing.ConsumedLayerError) as exc:
        costing.reverse_voucher_stock("PI", 1)
    assert "CONS-00001" in str(exc.value)
    assert "SCRAP-00002" in str(exc.value)
    assert len(exc.value.dependents) == 2


# ─────────────────────────────────────────────
# Rounding drift: layers must not merely round to the ledger
# ─────────────────────────────────────────────

def derived_value():
    """What the layers are worth under the OLD derivation, qty x unit_cost."""
    return sum((Decimal(str(l.qty_remaining)) * Decimal(str(l.unit_cost))
                for l in StockLayer.query.filter(StockLayer.qty_remaining > 0)),
               Decimal("0"))


def test_reaveraging_the_pool_does_not_drift_from_the_ledger(settings, product):
    """The defect ``value_remaining`` exists for.

    A weighted-average pool re-averages on every receipt, and ``unit_cost`` is
    a 4dp column, so the old ``qty_remaining * unit_cost`` reading of the pool
    was off by up to ``qty * 0.00005`` each time — in one direction as often as
    the other, but never cancelling, because each re-average rounds the result
    of the last one. Forty receipts at prices that do not divide evenly is
    enough to push it past the 0.01 the invariant tolerates.
    """
    for n in range(1, 41):
        buy(7, Decimal("10.33") + Decimal(n) / 100, n=n)
        issue(3, n=n)

    _ok, layer_value, running_cost = costing.assert_invariant(1)
    assert layer_value == running_cost, (
        f"the pool carries {layer_value} against a ledger of {running_cost}: "
        f"value must move only in the amounts the ledger moves in")

    stale = derived_value()
    assert stale != running_cost, (
        "qty x unit_cost happened to land exactly on the ledger, so this test "
        "is no longer exercising the drift it was written for — change the "
        "prices until it does not")


def test_fifo_issues_spanning_layers_do_not_drift(settings, product):
    """Same arithmetic under FIFO, where the rounding is in the issue instead.

    Nothing re-averages here; each issue posts a 2dp cost drawn from layers
    held at 4dp, and the difference used to stay behind on the layer.
    """
    settings.valuation_method = "fifo"
    db.session.commit()

    for n in range(1, 31):
        buy(Decimal("2.5"), Decimal("7.77") + Decimal(n) / 300, n=n)
    for n in range(1, 21):
        issue(Decimal("3.5"), n=n)

    _ok, layer_value, running_cost = costing.assert_invariant(1)
    assert layer_value == running_cost, (
        f"FIFO layers carry {layer_value} against a ledger of {running_cost}")


def test_reversing_an_issue_restores_the_layer_value_exactly(settings, product):
    """A consumption gives back precisely what it took, not a re-derivation.

    The give-back reads ``LayerConsumption.total_cost``, which records the
    value that actually left the layer — so an issue and its reversal are a
    round trip that leaves no residue, however awkward the cost.
    """
    buy(3, Decimal("10.0001"), n=1)
    buy(4, Decimal("13.3333"), n=2)
    before = costing.stock_value(1)

    issue(Decimal("2.5"), n=9)
    costing.reverse_voucher_stock("SI", 9)
    db.session.flush()

    assert costing.stock_value(1) == before, \
        "issuing and reversing must leave the layers exactly where they were"
    assert_ties("after an issue was reversed")


def _pretend_column_is_new():
    """Put the layers back the way the ALTER TABLE hands them over: value 0."""
    for l in StockLayer.query.all():
        l.value_remaining = Decimal("0")
    db.session.flush()


def test_backfill_seeds_layers_that_predate_the_carried_column(settings, product):
    """A database migrated into the column starts with every layer at zero.

    Unseeded, that reads as a warehouse of free stock: stock_value would be 0
    against a ledger holding the real money. The backfill reconstructs each
    layer from qty x unit_cost — the only figure a pre-migration row has —
    and then settles the rounding it inherits against the ledger.
    """
    for n in range(1, 16):
        buy(7, Decimal("10.33") + Decimal(n) / 100, n=n)
        issue(3, n=n)
    running_cost = book_value()
    assert running_cost > 0

    _pretend_column_is_new()
    assert costing.stock_value(1) == 0, "the fixture should start from zero"

    costing.backfill_layer_values()

    assert costing.stock_value(1) == running_cost, \
        "a migrated database must tie to its ledger, not to qty x unit_cost"
    assert_ties("after backfilling a pre-migration database")


def test_backfill_leaves_a_gap_too_large_to_be_rounding(settings, product):
    """A migration closes a rounding residue; it must not paper over a break.

    Silently pulling the layers onto the ledger whatever the distance would
    destroy the evidence of the very thing assert_invariant exists to report.
    """
    buy(10, 10, n=1)
    layer = StockLayer.query.filter(StockLayer.qty_remaining > 0).one()
    _pretend_column_is_new()
    layer.unit_cost = Decimal("4")          # 60 adrift, not a rounding error
    db.session.flush()

    costing.backfill_layer_values()

    assert costing.stock_value(1) == Decimal("40.0000"), \
        "the reconstruction must stand so the break stays visible"
    ok, _layer_value, _running = costing.assert_invariant(1)
    assert not ok, "a 60 gap must still fail the invariant after backfill"


def test_backfill_does_not_quietly_close_a_gap_that_opened_later(settings, product):
    """The backfill runs on every boot, so it must only touch what it seeded.

    A product already carrying its value is out of scope even when it is a
    few cents adrift: that gap opened after the migration, which makes it a
    leak, and closing it on each restart is how a leak stays invisible.
    """
    buy(10, 10, n=1)
    layer = StockLayer.query.filter(StockLayer.qty_remaining > 0).one()
    layer.value_remaining = Decimal("99.60")      # 0.40 adrift, within settling range
    db.session.flush()

    costing.backfill_layer_values()

    assert costing.stock_value(1) == Decimal("99.60"), \
        "a seeded layer must keep its value so the drift stays reportable"
    ok, _layer_value, _running = costing.assert_invariant(1)
    assert not ok, "the gap must still fail the invariant, not be absorbed"
