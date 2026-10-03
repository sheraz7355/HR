from collections import defaultdict
from decimal import Decimal
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from shared.extensions import db
from shared.tenancy import scoped_get
from shared.models.stock_ledger import StockLedger
from ..models.product import InvProduct
from ..models.stock_movement import InvStockMovement

inv_reports_bp = Blueprint("inv_reports", __name__, url_prefix="/inventory/reports")


@inv_reports_bp.route("/stock-ledger", methods=["GET"])
@login_required
def stock_ledger_report():
    product_id = request.args.get("product_id", type=int)
    products = InvProduct.query.filter_by(is_active=True).order_by(InvProduct.name).all()

    if product_id:
        # Document-date order: a back-dated document sits where it belongs.
        entries = (StockLedger.query.filter_by(product_id=product_id)
                   .order_by(StockLedger.txn_date, StockLedger.id).all())
        product = scoped_get(InvProduct, product_id)
    else:
        entries = []
        product = None

    return render_template("reports/stock_ledger.html",
                           products=products, product=product,
                           entries=entries, selected_id=product_id)


@inv_reports_bp.route("/valuation", methods=["GET"])
@login_required
def valuation_report():
    """Stock valuation at any date, with movement since a start date and a
    reconciliation to the inventory accounts in the general ledger.

    Everything is read from the stock ledger by DOCUMENT date, so a back-dated
    purchase shows up in the period it belongs to, and a re-costed issue shows
    its corrected cost. Opening + in - out = closing per product, and the
    closing total is compared against the GL inventory balance at the same
    date — any gap is named, not hidden.
    """
    from datetime import date, datetime, timedelta
    from shared.posting_helpers import parse_doc_date, DocumentDateError

    def _date(arg, default):
        try:
            return parse_doc_date(request.args.get(arg), fallback=default).date()
        except DocumentDateError:
            return default

    as_of = _date("as_of", date.today())
    start = _date("from", as_of.replace(day=1))
    if start > as_of:
        start = as_of
    opening_cut = start - timedelta(days=1)

    rows = []
    totals = {"open_qty": Decimal("0"), "open_val": Decimal("0"),
              "in_val": Decimal("0"), "out_val": Decimal("0"),
              "close_val": Decimal("0")}
    ledger = (StockLedger.query.filter(StockLedger.txn_date <= as_of)
              .order_by(StockLedger.product_id).all())
    by_product = defaultdict(list)
    for r in ledger:
        by_product[r.product_id].append(r)
    products = {p.id: p for p in InvProduct.query.all()}
    for pid, entries in by_product.items():
        p = products.get(pid)
        oq = ov = iq = iv = outq = outv = Decimal("0")
        for e in entries:
            q, v = Decimal(str(e.quantity or 0)), Decimal(str(e.total_cost or 0))
            inbound = e.transaction_type == "IN"
            if e.txn_date and e.txn_date <= opening_cut:
                oq += q if inbound else -q
                ov += v if inbound else -v
            elif inbound:
                iq += q
                iv += v
            else:
                outq += q
                outv += v
        cq, cv = oq + iq - outq, ov + iv - outv
        if not (oq or iq or outq or cv):
            continue
        rows.append({
            "id": pid, "sku": p.sku if p else "", "name": p.name if p else f"#{pid}",
            "unit": p.unit if p else "",
            "open_qty": oq, "open_val": ov, "in_qty": iq, "in_val": iv,
            "out_qty": outq, "out_val": outv, "close_qty": cq, "close_val": cv,
            "avg": (cv / cq) if cq > 0 else Decimal("0"),
        })
        totals["open_val"] += ov
        totals["in_val"] += iv
        totals["out_val"] += outv
        totals["close_val"] += cv
    rows.sort(key=lambda r: r["name"].lower())

    gl_balance = _gl_inventory_balance(as_of)
    return render_template("reports/valuation.html", rows=rows, totals=totals,
                           total_val=totals["close_val"], gl_balance=gl_balance,
                           difference=totals["close_val"] - gl_balance,
                           as_of=as_of.isoformat(), start=start.isoformat())


def _gl_inventory_balance(as_of):
    """Posted inventory-account balance (the Inventories subtree) at ``as_of``."""
    from datetime import datetime, time
    from shared.models.ledger import ChartOfAccount, JournalEntry, JournalLine
    from shared.ledger_utils import posting_account
    ids = {a.id for a in ChartOfAccount.query.all()
           if (a.code or "").startswith("1-01-04")}
    try:
        ids.add(posting_account("inventory").id)
    except Exception:
        pass
    if not ids:
        return Decimal("0")
    dr, cr = (db.session.query(
        db.func.coalesce(db.func.sum(JournalLine.debit), 0),
        db.func.coalesce(db.func.sum(JournalLine.credit), 0))
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .filter(JournalEntry.is_posted == True,  # noqa: E712
                JournalEntry.entry_date <= datetime.combine(as_of, time.max),
                JournalLine.account_id.in_(ids)).one())
    return Decimal(str(dr)) - Decimal(str(cr))


@inv_reports_bp.route("/low-stock", methods=["GET"])
@login_required
def low_stock_report():
    products = InvProduct.query.filter(
        InvProduct.is_active == True,
        InvProduct.current_stock <= InvProduct.reorder_level
    ).order_by(InvProduct.current_stock).all()
    return render_template("reports/low_stock.html", products=products)


@inv_reports_bp.route("/api/stock-ledger-json")
@login_required
def stock_ledger_json():
    product_id = request.args.get("product_id", type=int)
    if not product_id:
        return jsonify([])
    entries = (StockLedger.query.filter_by(product_id=product_id)
               .order_by(StockLedger.txn_date, StockLedger.id).all())
    data = []
    for e in entries:
        data.append({
            "id": e.id,
            "voucher_type": e.voucher_type,
            "voucher_number": e.voucher_number,
            "transaction_type": e.transaction_type,
            "quantity": float(e.quantity),
            "unit_cost": float(e.unit_cost),
            "running_qty": float(e.running_qty),
            "running_value": float(e.running_cost),
            "running_avg_cost": float(e.running_avg),
            "date": (e.txn_date.strftime("%Y-%m-%d") if e.txn_date else
                     e.created_at.strftime("%Y-%m-%d") if e.created_at else ""),
            "notes": e.notes or "",
        })
    return jsonify(data)
