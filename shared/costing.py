"""Inventory costing engine.

Single source of truth for what a unit of stock COSTS at any point in time.
Every document that moves stock (purchase invoice, sales invoice, purchase
return, consumption, scrap, adjustment, stock take) must go through
``record_in`` / ``record_out`` so the StockLedger holds a complete history:

    IN  rows carry the actual acquisition cost (landed purchase cost).
    OUT rows carry the cost COMPUTED by the valuation method at issue time —
        weighted average or FIFO per InventorySettings — never a price typed
        by the user and never the product's static cost_price.

That computed cost is what the calling voucher posts to the general ledger
(COGS, scrap loss, an employee's receivable account, ...), so receivables/
payables always reflect true historic cost.
"""

from decimal import Decimal

from shared.extensions import db
from shared.models.stock_ledger import StockLedger
from shared.models.inventory_settings import InventorySettings

ZERO = Decimal("0")


def _q(value, places=4):
    return Decimal(str(value or 0)).quantize(Decimal("0." + "0" * places))


def _settings():
    return InventorySettings.get()


def on_hand(product_id):
    qty, _cost, _avg = StockLedger.get_running_balance(product_id)
    return Decimal(str(qty or 0))


def fifo_layers_remaining(product_id):
    """Remaining (unit_cost, qty) purchase layers, oldest first.

    Layers are derived by replay: total OUT quantity so far consumes the
    earliest IN rows first, so no per-layer consumption bookkeeping is needed
    and the result is always consistent with the ledger.
    """
    rows = StockLedger.query.filter_by(product_id=product_id).order_by(StockLedger.id.asc()).all()
    consumed = sum((Decimal(str(r.quantity)) for r in rows if r.transaction_type == "OUT"), ZERO)
    layers = []
    for r in rows:
        if r.transaction_type != "IN":
            continue
        qty = Decimal(str(r.quantity))
        if consumed >= qty:
            consumed -= qty
            continue
        layers.append((Decimal(str(r.unit_cost)), qty - consumed))
        consumed = ZERO
    return layers


def current_unit_cost(product_id):
    """Unit cost of stock on hand under the configured valuation method."""
    qty, cost, avg = StockLedger.get_running_balance(product_id)
    qty = Decimal(str(qty or 0))
    if qty <= 0:
        # Nothing on hand — fall back to the most recent known cost so
        # vouchers over empty stock still carry a sensible value.
        last_in = StockLedger.query.filter_by(
            product_id=product_id, transaction_type="IN"
        ).order_by(StockLedger.id.desc()).first()
        return Decimal(str(last_in.unit_cost)) if last_in else ZERO
    if _settings().is_fifo():
        layers = fifo_layers_remaining(product_id)
        total = sum((c * q for c, q in layers), ZERO)
        lqty = sum((q for _c, q in layers), ZERO)
        return _q(total / lqty) if lqty > 0 else Decimal(str(avg))
    return Decimal(str(avg or 0))


def cost_of_issue(product_id, qty):
    """(unit_cost, total_cost) that issuing ``qty`` units would carry NOW.

    Weighted average: qty x running average.
    FIFO: consume remaining layers oldest-first; if the requested quantity
    exceeds stock on hand, the uncovered remainder is costed at the last
    known layer cost so the ledger never books free stock.
    """
    qty = Decimal(str(qty))
    if qty <= 0:
        return ZERO, ZERO
    if not _settings().is_fifo():
        unit = current_unit_cost(product_id)
        return unit, _q(qty * unit, 2)
    layers = fifo_layers_remaining(product_id)
    remaining, total, last_cost = qty, ZERO, ZERO
    for unit_cost, layer_qty in layers:
        take = min(layer_qty, remaining)
        total += take * unit_cost
        last_cost = unit_cost
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        if last_cost == ZERO:
            last_cost = current_unit_cost(product_id)
        total += remaining * last_cost
    unit = _q(total / qty) if qty else ZERO
    return unit, _q(total, 2)


def _sync_product_stock(product_id):
    from inventory_app.models.product import InvProduct
    p = InvProduct.query.get(product_id)
    if p is not None:
        qty = on_hand(product_id)
        p.current_stock = int(qty)
        # Keep the legacy static field in step with the engine so any old
        # display code shows the current valuation cost.
        unit = current_unit_cost(product_id)
        if unit > 0:
            p.cost_price = float(unit)


def _write_row(product_id, voucher_type, voucher_id, voucher_number,
               transaction_type, qty, unit_cost, total_cost, notes, created_by):
    prev_qty, prev_cost, _prev_avg = StockLedger.get_running_balance(product_id)
    prev_qty = Decimal(str(prev_qty or 0))
    prev_cost = Decimal(str(prev_cost or 0))
    if transaction_type == "IN":
        new_qty = prev_qty + qty
        new_cost = prev_cost + total_cost
    else:
        new_qty = prev_qty - qty
        new_cost = prev_cost - total_cost
    if new_qty == 0:
        new_cost = ZERO
    new_avg = _q(new_cost / new_qty) if new_qty > 0 else ZERO
    row = StockLedger(
        product_id=product_id,
        voucher_type=voucher_type,
        voucher_id=voucher_id,
        voucher_number=voucher_number,
        transaction_type=transaction_type,
        quantity=qty,
        unit_cost=_q(unit_cost),
        total_cost=_q(total_cost, 2),
        running_qty=new_qty,
        running_cost=new_cost,
        running_avg=new_avg,
        notes=notes,
        created_by=created_by,
    )
    db.session.add(row)
    db.session.flush()
    _sync_product_stock(product_id)
    return row


def record_in(product_id, voucher_type, voucher_id, voucher_number,
              qty, unit_cost, notes="", created_by=1):
    """Stock received at an actual acquisition cost (e.g. landed purchase cost)."""
    qty = Decimal(str(qty))
    unit_cost = _q(unit_cost)
    return _write_row(product_id, voucher_type, voucher_id, voucher_number,
                      "IN", qty, unit_cost, _q(qty * unit_cost, 2), notes, created_by)


def record_out(product_id, voucher_type, voucher_id, voucher_number,
               qty, notes="", created_by=1, unit_cost=None):
    """Stock issued; cost computed by the valuation method unless an explicit
    cost basis is passed (purchase returns use the original invoice cost).

    Returns (unit_cost, total_cost) so the caller can post the same value to
    the general ledger.
    """
    qty = Decimal(str(qty))
    if unit_cost is None:
        unit, total = cost_of_issue(product_id, qty)
    else:
        unit = _q(unit_cost)
        total = _q(qty * unit, 2)
    _write_row(product_id, voucher_type, voucher_id, voucher_number,
               "OUT", qty, unit, total, notes, created_by)
    return unit, total


def rebuild_running(product_id):
    """Recompute the running qty/cost/avg columns by replaying the ledger."""
    rows = StockLedger.query.filter_by(product_id=product_id).order_by(StockLedger.id.asc()).all()
    qty = cost = ZERO
    for r in rows:
        rqty = Decimal(str(r.quantity))
        rtotal = Decimal(str(r.total_cost))
        if r.transaction_type == "IN":
            qty += rqty
            cost += rtotal
        else:
            qty -= rqty
            cost -= rtotal
        if qty == 0:
            cost = ZERO
        r.running_qty = qty
        r.running_cost = cost
        r.running_avg = _q(cost / qty) if qty > 0 else ZERO
    db.session.flush()
    _sync_product_stock(product_id)


def reverse_voucher_stock(voucher_type, voucher_id):
    """Remove a voucher's stock rows and rebuild affected products' history.

    Used on unapprove: the voucher's effect disappears from the cost history
    and every later running balance is recomputed from the surviving rows.
    """
    rows = StockLedger.query.filter_by(voucher_type=voucher_type, voucher_id=voucher_id).all()
    product_ids = {r.product_id for r in rows}
    for r in rows:
        db.session.delete(r)
    db.session.flush()
    for pid in product_ids:
        rebuild_running(pid)


def ensure_opening_balances(created_by=1):
    """Give products that pre-date the costing engine an opening cost layer.

    Any product holding stock with no ledger history gets one IN row at its
    static cost_price, so all future issues have a historic cost to draw on.
    No journal entry is posted — the general ledger already carried these
    balances under the old flows.
    """
    from inventory_app.models.product import InvProduct
    for p in InvProduct.query.filter(InvProduct.current_stock > 0).all():
        exists = StockLedger.query.filter_by(product_id=p.id).first()
        if exists:
            continue
        record_in(p.id, "OPENING", p.id, f"OPEN-{p.id:05d}",
                  qty=p.current_stock, unit_cost=p.cost_price or 0,
                  notes="Opening balance (pre-costing-engine stock)",
                  created_by=created_by)
