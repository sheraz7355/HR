"""General-ledger side of a stock re-costing.

When a back-dated document, or the reversal of an earlier one, re-sequences a
product's history, issues after it can draw from different layers and their
cost moves (shared/costing.py: _replay). The stock ledger row is re-costed in
place; this module posts the difference so the general ledger follows:

    issue cost up     Dr <account the issue charged>   Cr Inventory
    issue cost down   Dr Inventory                     Cr <account the issue charged>

"The account the issue charged" is the one its own voucher debited — COGS for
a sale, the charge account of a consumption or scrap, the adjustment account
of a stock adjustment, the asset for a capitalisation — so each P&L line and
each receivable carries the true cost, not just the inventory control account.

A sales return (an IN that mirrors a sale) moves the other way round: its
cost up means Dr Inventory, Cr COGS.

Each adjustment is dated in the issue's own period while that is open, so the
period's gross margin is right. If the issue's period is closed its figures
are final, and the adjustment lands in the current open period instead —
visible, and with the same net effect on the balance sheet.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from shared.extensions import db
from shared.tenancy import scoped_get

TWO = Decimal("0.01")


def _q2(v):
    return Decimal(str(v or 0)).quantize(TWO)


def _counter_account(row):
    """(account_id, label_id) the voucher behind ``row`` charged its cost to."""
    from shared.ledger_utils import posting_account, get_or_create_account
    vt, vid = row.voucher_type, row.voucher_id

    if vt in ("SI", "SRV"):
        label_id = None
        try:
            if vt == "SI":
                from inventory_app.models.invoice import InvInvoiceItem
                item = (InvInvoiceItem.query
                        .filter_by(invoice_id=vid, product_id=row.product_id)
                        .first())
                label_id = item.label_id if item else None
        except Exception:
            label_id = None
        return posting_account("cogs").id, label_id

    if vt in ("CONS", "SCRAP"):
        from shared.models.vouchers import ConsumptionVoucher, ScrapVoucher
        model = ConsumptionVoucher if vt == "CONS" else ScrapVoucher
        v = scoped_get(model, vid)
        if v is not None and v.charge_account_id:
            return v.charge_account_id, getattr(v, "label_id", None)
        if vt == "CONS":
            return get_or_create_account("5700", "Consumption Expense", "expense").id, None
        return get_or_create_account("5800", "Scrap/Write-off", "expense").id, None

    if vt == "ADJ":
        from shared.models.vouchers import StockAdjustmentVoucher
        v = scoped_get(StockAdjustmentVoucher, vid)
        return (get_or_create_account("5900", "Inventory Adjustment", "expense").id,
                getattr(v, "label_id", None) if v else None)

    if vt == "FA-CAP":
        from shared.models.asset_transfer import AssetTransfer
        t = scoped_get(AssetTransfer, vid)
        if t is not None:
            from fixed_assets_app.models.asset import FixedAsset
            asset = scoped_get(FixedAsset, t.asset_id)
            if asset is not None and asset.fixed_asset_account_id:
                return asset.fixed_asset_account_id, getattr(asset, "label_id", None)

    return posting_account("inventory_variance").id, None


def _inventory_account(row):
    """The stock account the voucher behind ``row`` moved."""
    from shared.ledger_utils import posting_account, create_entity_account
    if row.voucher_type == "FA-CAP":
        from inventory_app.models.product import InvProduct
        p = scoped_get(InvProduct, row.product_id)
        if p is not None:
            return create_entity_account("product", p.id, p.name).id
    return posting_account("inventory").id


def _follow_documents(row, new_total):
    """Keep the source document's own cost figures in step with the ledger."""
    vt, vid = row.voucher_type, row.voucher_id
    if vt == "FA-CAP":
        from shared.models.asset_transfer import AssetTransfer
        from fixed_assets_app.models.asset import FixedAsset
        t = scoped_get(AssetTransfer, vid)
        asset = scoped_get(FixedAsset, t.asset_id) if t else None
        if asset is not None:
            asset.purchase_cost = float(new_total)
            t.transfer_amount = float(new_total)
            asset.recalculate()
        return
    model = None
    if vt in ("CONS", "SCRAP", "ADJ"):
        from shared.models.vouchers import (ConsumptionItem, ScrapItem,
                                            StockAdjustmentItem)
        model = {"CONS": ConsumptionItem, "SCRAP": ScrapItem,
                 "ADJ": StockAdjustmentItem}[vt]
    if model is None:
        return
    item = model.query.filter_by(voucher_id=vid, product_id=row.product_id).first()
    if item is not None:
        item.total_cost = new_total
        qty = Decimal(str(row.quantity or 0))
        if qty:
            item.unit_cost = (Decimal(str(new_total)) / qty).quantize(Decimal("0.0001"))


def adjustment_date(issue_date):
    """The issue's own date when its period is open, else today."""
    from shared.periods import is_closed
    d = issue_date or date.today()
    if is_closed(d):
        return date.today()
    return d


def post_adjustments(adjustments, trigger, created_by=1):
    """Journal every re-costed row in ``adjustments`` [(row, old, new)].

    One journal per (entry date, voucher), keyed ``CADJ-<voucher type>`` /
    ``<voucher id>`` so the adjustments BELONG to the voucher they re-cost:
    reversing that voucher later un-posts them with it
    (``reverse_adjustments``) instead of leaving its old cost difference
    stranded in the inventory account.
    """
    from shared.ledger_utils import post_journal_entry
    from shared.models.stock_layer import StockCostAdjustment

    by_date = defaultdict(list)
    for row, old, new in adjustments:
        delta = _q2(new) - _q2(old)
        if not delta:
            continue
        key = (adjustment_date(row.txn_date), row.voucher_type, row.voucher_id)
        by_date[key].append((row, _q2(old), _q2(new), delta))

    entries = []
    for key in sorted(by_date, key=lambda k: (k[0], k[1], k[2])):
        when, vtype, vid = key
        lines, records = [], []
        for row, old, new, delta in by_date[key]:
            counter, label_id = _counter_account(row)
            stock = _inventory_account(row)
            amount = abs(delta)
            # For an issue, more cost is a further charge to the counter
            # account. For a receipt that mirrors an issue (a sales return)
            # more cost is more stock.
            more_charge = (delta > 0) == (row.transaction_type == "OUT")
            dr, cr = (counter, stock) if more_charge else (stock, counter)
            text = (f"Cost adjustment {row.voucher_number}: "
                    f"{old} -> {new} ({trigger})")
            lines.append({"account_id": dr, "debit": amount, "credit": 0,
                          "label_id": label_id, "description": text})
            lines.append({"account_id": cr, "debit": 0, "credit": amount,
                          "label_id": label_id, "description": text})
            records.append(StockCostAdjustment(
                product_id=row.product_id, ledger_id=row.id,
                voucher_type=row.voucher_type, voucher_id=row.voucher_id,
                voucher_number=row.voucher_number, old_cost=old,
                new_cost=new, delta=delta, trigger=(trigger or "")[:120],
                entry_date=when))
            _follow_documents(row, new)
        if not lines:
            continue
        number = by_date[key][0][0].voucher_number
        je = post_journal_entry(
            voucher_type=f"CADJ-{vtype}", voucher_id=vid,
            voucher_number=f"CADJ-{number}"[:50],
            description=f"Inventory cost adjustment of {number} — {trigger}",
            lines=lines, entry_date=when, created_by=created_by)
        for rec in records:
            rec.journal_entry_id = je.id
            db.session.add(rec)
        entries.append(je)
    db.session.flush()
    return entries


def reverse_adjustments(voucher_type, voucher_id, created_by=1):
    """Un-post every cost adjustment that re-costed this voucher.

    Called when the voucher itself is reversed: its own journal is un-posted,
    so the corrections to that journal must go with it, or the inventory
    account keeps a difference for a document that no longer exists.
    """
    from shared.ledger_utils import reverse_journal_entry
    reverse_journal_entry(f"CADJ-{voucher_type}", voucher_id, created_by=created_by)
