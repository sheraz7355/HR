from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from decimal import Decimal
from ..extensions import db
from ..models.purchase_invoice import InvPurchaseInvoice, InvPurchaseInvoiceItem
from ..models.supplier import InvSupplier
from ..models.product import InvProduct
from ..models.stock_movement import InvStockMovement
from shared.models.vouchers import ConsumptionItem as ConsItem, ScrapItem, StockAdjustmentItem as AdjItem
from shared.ledger_utils import post_journal_entry, reverse_journal_entry, get_or_create_account
from shared.models.ledger import ChartOfAccount

inv_pinv_bp = Blueprint("inv_purchase_invoice", __name__,
                         url_prefix="/inventory/purchase-invoice")


def next_voucher():
    last = InvPurchaseInvoice.query.order_by(InvPurchaseInvoice.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f"VCH-{datetime.utcnow():%Y%m}-{n:04d}"


def next_invoice_num(supplier_id=None):
    last = InvPurchaseInvoice.query.order_by(InvPurchaseInvoice.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f"PINV-{datetime.utcnow():%Y%m}-{n:04d}"


@inv_pinv_bp.route("/", defaults={"id": None})
@inv_pinv_bp.route("/<int:id>")
@login_required
def invoice_form(id):
    invoice = InvPurchaseInvoice.query.get(id) if id else None
    suppliers = InvSupplier.query.filter_by(is_active=True).order_by(InvSupplier.name).all()
    products = InvProduct.query.filter_by(is_active=True).order_by(InvProduct.name).all()
    invoice_items = []
    if invoice:
        for it in invoice.items.all():
            invoice_items.append({
                "product_id": it.product_id,
                "product": {"sku": it.product.sku if it.product else ""},
                "description": it.description,
                "quantity": it.quantity,
                "unit": it.unit,
                "unit_price": it.unit_price,
                "discount_pct": it.discount_pct,
                "discount_amount": it.discount_amount,
                "commission": it.commission,
                "freight": it.freight,
                "loading_unloading": it.loading_unloading,
                "sales_tax_pct": it.sales_tax_pct,
                "total_before_discount": it.total_before_discount,
                "total_after_discount": it.total_after_discount,
            })
    return render_template("purchase_invoice/form_inv.html",
                           invoice=invoice,
                           invoice_items=invoice_items,
                           suppliers=suppliers,
                           products=products,
                           now=datetime.utcnow())


def validate_approve(data):
    errors = []
    if not data.get("supplier_id"):
        errors.append("Supplier is required")
    items = data.get("items", [])
    if not items:
        errors.append("At least one item is required")
    else:
        for i, row in enumerate(items):
            if not row.get("product_id"):
                errors.append(f"Row {i+1}: Product is required")
            qty = float(row.get("quantity", 0))
            if qty <= 0:
                errors.append(f"Row {i+1}: Quantity must be greater than 0")
    return errors


@inv_pinv_bp.route("/save", methods=["POST"])
@login_required
def save_invoice():
    data = request.get_json(force=True)
    inv_id = data.get("id")
    action = data.get("action", "save")

    if inv_id:
        inv = InvPurchaseInvoice.query.get_or_404(inv_id)
        if inv.status == "approved":
            return jsonify({"ok": False, "error": "Cannot modify approved invoice"}), 400
    else:
        inv = InvPurchaseInvoice(
            voucher_number=next_voucher(),
            invoice_number=data.get("invoice_number") or next_invoice_num(),
            created_by=current_user.id,
        )
        db.session.add(inv)

    if action == "approve":
        validation_errors = validate_approve(data)
        if validation_errors:
            return jsonify({"ok": False, "error": "; ".join(validation_errors)}), 400

    inv.supplier_id = data.get("supplier_id")
    inv.driver_name = data.get("driver_name", "")
    inv.driver_contact = data.get("driver_contact", "")
    inv.vehicle_number = data.get("vehicle_number", "")
    inv.gate_pass = data.get("gate_pass", "")
    inv.discount_mode = data.get("discount_mode", "general")
    inv.expenses_mode = data.get("expenses_mode", "general")
    inv.tax_mode = data.get("tax_mode", "general")

    inv.global_discount_pct = float(data.get("global_discount_pct", 0))
    inv.global_discount_value = float(data.get("global_discount_value", 0))
    inv.global_commission = float(data.get("global_commission", 0))
    inv.global_freight = float(data.get("global_freight", 0))
    inv.global_loading = float(data.get("global_loading", 0))
    inv.global_sales_tax_pct = float(data.get("global_sales_tax_pct", 0))
    inv.global_withholding_tax_pct = float(data.get("global_withholding_tax_pct", 0))
    inv.notes = data.get("notes", "")
    inv.subtotal = float(data.get("subtotal", 0))
    inv.total_discount = float(data.get("total_discount", 0))
    inv.total_expenses = float(data.get("total_expenses", 0))
    inv.total_tax = float(data.get("total_tax", 0))
    inv.net_payable = float(data.get("net_payable", 0))

    if action == "approve":
        inv.status = "approved"
        inv.approved_by = current_user.id
        inv.approved_at = datetime.utcnow()
    elif inv.status == "new":
        inv.status = "unapproved"

    db.session.flush()

    InvPurchaseInvoiceItem.query.filter_by(invoice_id=inv.id).delete()
    for row in data.get("items", []):
        item = InvPurchaseInvoiceItem(
            invoice_id=inv.id,
            product_id=row.get("product_id"),
            description=row.get("description", ""),
            quantity=float(row.get("quantity", 1)),
            unit=row.get("unit", "pcs"),
            unit_price=float(row.get("unit_price", 0)),
            discount_pct=float(row.get("discount_pct", 0)),
            discount_amount=float(row.get("discount_amount", 0)),
            commission=float(row.get("commission", 0)),
            freight=float(row.get("freight", 0)),
            loading_unloading=float(row.get("loading_unloading", 0)),
            sales_tax_pct=float(row.get("sales_tax_pct", 0)),
            withholding_tax_pct=float(row.get("withholding_tax_pct", 0)),
            total_before_discount=float(row.get("total_before_discount", 0)),
            total_after_discount=float(row.get("total_after_discount", 0)),
            comments=row.get("comments", ""),
        )
        db.session.add(item)

        if action == "approve" and item.product_id:
            prod = InvProduct.query.get(item.product_id)
            if prod:
                old_stock = prod.current_stock or 0
                old_cost = prod.cost_price or 0
                new_qty = item.quantity
                new_cost = item.unit_price or 0
                if old_stock + new_qty > 0:
                    prod.cost_price = round(((old_stock * old_cost) + (new_qty * new_cost)) / (old_stock + new_qty), 4)
                prod.current_stock = old_stock + new_qty
                db.session.add(InvStockMovement(
                    product_id=item.product_id, type="purchase_in",
                    quantity=item.quantity,
                    reference_type="purchase_invoice",
                    reference_id=inv.id,
                    notes=f"Approved invoice {inv.invoice_number}",
                    created_by=current_user.id,
                ))

    if action == "approve":
        inv_acc = ChartOfAccount.query.filter_by(code="113").first()
        ap_acc = ChartOfAccount.query.filter_by(code="211").first()
        if inv_acc and ap_acc:
            # Goods value (subtotal net of discount, plus capitalised expenses)
            # is debited to Inventory; recoverable input sales tax is debited to
            # its own asset; any withholding deducted from the payable is
            # credited to WHT Payable so the entry still balances:
            #   Dr Inventory (goods) + Dr Input Tax (sales tax)
            #   Cr Accounts Payable (net_payable) + Cr WHT Payable (residual)
            net_payable = float(inv.net_payable or 0)
            input_tax = float(inv.total_tax or 0)
            goods = round(float(inv.subtotal or 0) - float(inv.total_discount or 0)
                          + float(inv.total_expenses or 0), 2)
            wht = round(goods + input_tax - net_payable, 2)
            lines = [
                {"account_id": inv_acc.id, "debit": goods, "credit": 0,
                 "description": f"Inventory - {inv.invoice_number}"},
            ]
            if input_tax > 0:
                in_tax_acc = get_or_create_account("114", "Input Tax Recoverable", "asset", "11")
                lines.append(
                    {"account_id": in_tax_acc.id, "debit": input_tax, "credit": 0,
                     "description": f"Input Tax - {inv.invoice_number}"},
                )
            lines.append(
                {"account_id": ap_acc.id, "debit": 0, "credit": net_payable,
                 "description": f"AP - {inv.invoice_number}"},
            )
            if abs(wht) > 0.005:
                wht_acc = get_or_create_account("214", "Withholding Tax Payable", "liability", "21")
                lines.append(
                    {"account_id": wht_acc.id, "debit": 0, "credit": wht,
                     "description": f"WHT - {inv.invoice_number}"},
                )
            post_journal_entry(
                voucher_type="PI",
                voucher_id=inv.id,
                voucher_number=inv.voucher_number,
                description=f"Purchase Invoice {inv.invoice_number} - {inv.supplier.name if inv.supplier else ''}",
                lines=lines,
                entry_date=datetime.utcnow(),
                created_by=current_user.id,
            )

    db.session.commit()
    if action == "approve":
        msg = "approved and locked"
    elif inv_id:
        msg = "changes saved"
    else:
        msg = "saved as unapproved"
    return jsonify({"ok": True, "id": inv.id, "status": inv.status,
                    "voucher": inv.voucher_number, "message": f"Invoice {msg}"})


@inv_pinv_bp.route("/unapprove/<int:id>", methods=["POST"])
@login_required
def unapprove_invoice(id):
    inv = InvPurchaseInvoice.query.get_or_404(id)
    if inv.status != "approved":
        return jsonify({"ok": False, "error": "Only approved invoices can be unapproved"}), 400

    # Dependency check: has any item been consumed/sold/adjusted?
    product_ids = [item.product_id for item in inv.items.all() if item.product_id]
    if product_ids:
        cons = ConsItem.query.filter(
            ConsItem.product_id.in_(product_ids)
        ).first()
        if cons:
            return jsonify({"ok": False, "error": "Cannot unapprove: Items already consumed"}), 400
        scrap = ScrapItem.query.filter(
            ScrapItem.product_id.in_(product_ids)
        ).first()
        if scrap:
            return jsonify({"ok": False, "error": "Cannot unapprove: Items already scrapped"}), 400
        adj = AdjItem.query.filter(
            AdjItem.product_id.in_(product_ids)
        ).first()
        if adj:
            return jsonify({"ok": False, "error": "Cannot unapprove: Items already adjusted"}), 400

    reverse_journal_entry("PI", inv.id, current_user.id)

    inv.status = "unapproved"
    inv.approved_by = None
    inv.approved_at = None

    InvStockMovement.query.filter_by(
        reference_type="purchase_invoice", reference_id=inv.id
    ).delete()

    for item in inv.items.all():
        if item.product_id:
            prod = InvProduct.query.get(item.product_id)
            if prod:
                prod.current_stock -= item.quantity

    db.session.commit()
    return jsonify({"ok": True, "status": "unapproved",
                    "message": "Invoice has been unapproved and unlocked for editing"})


@inv_pinv_bp.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete_invoice(id):
    inv = InvPurchaseInvoice.query.get_or_404(id)
    if inv.status == "approved":
        return jsonify({"ok": False, "error": "Cannot delete an approved invoice. Unapprove it first."}), 400
    try:
        InvPurchaseInvoiceItem.query.filter_by(invoice_id=inv.id).delete()
        db.session.delete(inv)
        db.session.commit()
        return jsonify({"ok": True, "message": "Invoice deleted successfully"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500


@inv_pinv_bp.route("/list")
@login_required
def list_invoices():
    invoices = InvPurchaseInvoice.query.order_by(InvPurchaseInvoice.id.desc()).all()
    return render_template("purchase_invoice/list_inv.html", invoices=invoices)


@inv_pinv_bp.route("/api/products")
@login_required
def api_products():
    q = request.args.get("q", "").strip()
    query = InvProduct.query.filter_by(is_active=True)
    if q:
        query = query.filter(
            db.or_(
                InvProduct.name.ilike(f"%{q}%"),
                InvProduct.sku.ilike(f"%{q}%"),
            )
        )
    products = query.order_by(InvProduct.name).limit(20).all()
    return jsonify([{
        "id": p.id, "name": p.name, "sku": p.sku,
        "unit_price": p.unit_price, "current_stock": p.current_stock,
        "unit": p.unit,
    } for p in products])


@inv_pinv_bp.route("/api/suppliers")
@login_required
def api_suppliers():
    q = request.args.get("q", "").strip()
    query = InvSupplier.query.filter_by(is_active=True)
    if q:
        query = query.filter(InvSupplier.name.ilike(f"%{q}%"))
    suppliers = query.order_by(InvSupplier.name).limit(20).all()
    return jsonify([{
        "id": s.id, "name": s.name, "city": s.city or "",
        "phone": s.phone or "", "address": s.address or "",
    } for s in suppliers])


@inv_pinv_bp.route("/api/new-product", methods=["POST"])
@login_required
def api_new_product():
    data = request.get_json(force=True)
    sku = data.get("sku", "").strip()
    name = data.get("name", "").strip()
    if not sku or not name:
        return jsonify({"ok": False, "error": "SKU and Name required"}), 400
    if InvProduct.query.filter_by(sku=sku).first():
        return jsonify({"ok": False, "error": "SKU already exists"}), 400
    p = InvProduct(
        sku=sku, name=name,
        unit_price=float(data.get("unit_price", 0)),
        cost_price=float(data.get("cost_price", 0)),
        unit=data.get("unit", "pcs"),
        current_stock=0,
    )
    db.session.add(p)
    db.session.commit()
    return jsonify({"ok": True, "product": {
        "id": p.id, "name": p.name, "sku": p.sku,
        "unit_price": p.unit_price, "current_stock": p.current_stock,
        "unit": p.unit,
    }})
