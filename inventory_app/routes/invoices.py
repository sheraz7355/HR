from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal
from ..extensions import db
from ..models.invoice import InvInvoice, InvInvoiceItem
from ..models.customer import InvCustomer
from ..models.product import InvProduct
from ..models.stock_movement import InvStockMovement
from ..models.sales_order import InvSalesOrder
from shared.ledger_utils import post_journal_entry, reverse_journal_entry, get_or_create_account
from shared.models.ledger import ChartOfAccount

inv_inv_bp = Blueprint("inv_invoices", __name__, url_prefix="/inventory/invoices")


def next_voucher():
    last = InvInvoice.query.order_by(InvInvoice.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f"SI-{datetime.utcnow():%Y%m}-{n:04d}"


def next_invoice_num():
    last = InvInvoice.query.order_by(InvInvoice.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f"INV-{datetime.utcnow():%Y%m}-{n:04d}"


@inv_inv_bp.route("/", defaults={"id": None})
@inv_inv_bp.route("/<int:id>")
@login_required
def invoice_form(id):
    invoice = InvInvoice.query.get(id) if id else None
    customers = InvCustomer.query.filter_by(is_active=True).order_by(InvCustomer.name).all()
    products = InvProduct.query.filter_by(is_active=True).order_by(InvProduct.name).all()
    invoice_items = []
    if invoice:
        for it in invoice.items.all():
            product = it.product
            invoice_items.append({
                "product_id": it.product_id,
                "product": {"sku": product.sku if product else ""},
                "description": it.description,
                "quantity": it.quantity,
                "unit": it.unit,
                "unit_price": it.unit_price,
                "discount_pct": it.discount_pct,
                "discount_amount": it.discount_amount,
                "delivery": it.delivery,
                "installation": it.installation,
                "sales_tax_pct": it.sales_tax_pct,
                "total_before_discount": it.total_before_discount,
                "total_after_discount": it.total_after_discount,
            })
    return render_template("invoices/form_inv.html",
                           invoice=invoice, invoice_items=invoice_items,
                           customers=customers,
                           products=products, now=datetime.utcnow())


@inv_inv_bp.route("/list")
@login_required
def list_invoices():
    status = request.args.get("status", "")
    query = InvInvoice.query
    if status:
        query = query.filter_by(voucher_status=status)
    invoices = query.order_by(InvInvoice.id.desc()).all()
    return render_template("invoices/list_inv.html", invoices=invoices)


def validate_invoice(data):
    errors = []
    if not data.get("customer_id"):
        errors.append("Customer is required")
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


@inv_inv_bp.route("/save", methods=["POST"])
@login_required
def save_invoice():
    data = request.get_json(force=True)
    inv_id = data.get("id")
    action = data.get("action", "save")

    if inv_id:
        inv = InvInvoice.query.get_or_404(inv_id)
        if inv.voucher_status == "approved":
            return jsonify({"ok": False, "error": "Cannot modify approved invoice"}), 400
    else:
        inv = InvInvoice(
            voucher_number=next_voucher(),
            invoice_number=data.get("invoice_number") or next_invoice_num(),
            created_by=current_user.id,
        )
        db.session.add(inv)

    if action == "approve":
        validation_errors = validate_invoice(data)
        if validation_errors:
            return jsonify({"ok": False, "error": "; ".join(validation_errors)}), 400

    inv.customer_id = data.get("customer_id")
    inv.due_date = datetime.strptime(data.get("due_date"), "%Y-%m-%d") if data.get("due_date") else None
    inv.discount_mode = data.get("discount_mode", "general")
    inv.charges_mode = data.get("charges_mode", "general")
    inv.tax_mode = data.get("tax_mode", "general")

    inv.global_discount_pct = float(data.get("global_discount_pct", 0))
    inv.global_discount_value = float(data.get("global_discount_value", 0))
    inv.global_delivery = float(data.get("global_delivery", 0))
    inv.global_installation = float(data.get("global_installation", 0))
    inv.global_sales_tax_pct = float(data.get("global_sales_tax_pct", 0))
    inv.notes = data.get("notes", "")
    inv.subtotal = float(data.get("subtotal", 0))
    inv.total_discount = float(data.get("total_discount", 0))
    inv.total_charges = float(data.get("total_charges", 0))
    inv.total_tax = float(data.get("total_tax", 0))
    inv.total_amount = float(data.get("total_amount", 0))

    if action == "approve":
        inv.voucher_status = "approved"
        inv.approved_by = current_user.id
        inv.approved_at = datetime.utcnow()
    elif inv.voucher_status != "approved":
        inv.voucher_status = "unapproved"

    db.session.flush()

    InvInvoiceItem.query.filter_by(invoice_id=inv.id).delete()
    for row in data.get("items", []):
        item = InvInvoiceItem(
            invoice_id=inv.id,
            product_id=row.get("product_id"),
            description=row.get("description", ""),
            quantity=float(row.get("quantity", 1)),
            unit=row.get("unit", "pcs"),
            unit_price=float(row.get("unit_price", 0)),
            discount_pct=float(row.get("discount_pct", 0)),
            discount_amount=float(row.get("discount_amount", 0)),
            delivery=float(row.get("delivery", 0)),
            installation=float(row.get("installation", 0)),
            sales_tax_pct=float(row.get("sales_tax_pct", 0)),
            total_before_discount=float(row.get("total_before_discount", 0)),
            total_after_discount=float(row.get("total_after_discount", 0)),
            comments=row.get("comments", ""),
        )
        db.session.add(item)

        if action == "approve" and item.product_id:
            prod = InvProduct.query.get(item.product_id)
            if prod:
                prod.current_stock -= item.quantity
                db.session.add(InvStockMovement(
                    product_id=item.product_id, type="sale_out",
                    quantity=item.quantity,
                    reference_type="sales_invoice",
                    reference_id=inv.id,
                    notes=f"Approved invoice {inv.invoice_number}",
                    created_by=current_user.id,
                ))

    if action == "approve":
        ar_acc = ChartOfAccount.query.filter_by(code="112").first()
        rev_acc = ChartOfAccount.query.filter_by(code="411").first()
        cogs_acc = ChartOfAccount.query.filter_by(code="511").first()
        inv_acc = ChartOfAccount.query.filter_by(code="113").first()
        # Split output sales tax into its own liability so revenue is stated
        # net of tax (Dr Receivable = gross, Cr Revenue = net, Cr Output Tax).
        total = float(inv.total_amount or 0)
        output_tax = float(inv.total_tax or 0)
        revenue = round(total - output_tax, 2)
        lines = [
            {"account_id": ar_acc.id, "debit": total, "credit": 0,
             "description": f"AR - {inv.invoice_number}"},
            {"account_id": rev_acc.id, "debit": 0, "credit": revenue,
             "description": f"Revenue - {inv.invoice_number}"},
        ]
        if output_tax > 0:
            out_tax_acc = get_or_create_account("213", "Sales Tax Payable", "liability", "21")
            lines.append(
                {"account_id": out_tax_acc.id, "debit": 0, "credit": output_tax,
                 "description": f"Output Tax - {inv.invoice_number}"},
            )
        total_cogs = Decimal("0")
        for item in InvInvoiceItem.query.filter_by(invoice_id=inv.id).all():
            if item.product_id:
                prod = InvProduct.query.get(item.product_id)
                if prod and prod.cost_price:
                    cost = Decimal(str(prod.cost_price)) * Decimal(str(item.quantity))
                    total_cogs += cost
        if total_cogs > 0 and cogs_acc and inv_acc:
            lines.append(
                {"account_id": cogs_acc.id, "debit": float(total_cogs), "credit": 0,
                 "description": f"COGS - {inv.invoice_number}"},
            )
            lines.append(
                {"account_id": inv_acc.id, "debit": 0, "credit": float(total_cogs),
                 "description": f"Inventory - {inv.invoice_number}"},
            )
        post_journal_entry(
            voucher_type="SI",
            voucher_id=inv.id,
            voucher_number=inv.voucher_number,
            description=f"Sales Invoice {inv.invoice_number} - {inv.customer.name if inv.customer else ''}",
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
        msg = "saved"
    return jsonify({"ok": True, "id": inv.id, "voucher_status": inv.voucher_status,
                    "payment_status": inv.payment_status,
                    "number": inv.invoice_number, "voucher": inv.voucher_number,
                    "message": f"Invoice {msg}"})


@inv_inv_bp.route("/unapprove/<int:id>", methods=["POST"])
@login_required
def unapprove_invoice(id):
    inv = InvInvoice.query.get_or_404(id)
    if inv.voucher_status != "approved":
        return jsonify({"ok": False, "error": "Only approved invoices can be unapproved"}), 400

    reverse_journal_entry("SI", inv.id, current_user.id)

    inv.voucher_status = "unapproved"
    inv.payment_status = "unpaid"
    inv.approved_by = None
    inv.approved_at = None

    InvStockMovement.query.filter_by(
        reference_type="sales_invoice", reference_id=inv.id
    ).delete()

    for item in inv.items.all():
        if item.product_id:
            prod = InvProduct.query.get(item.product_id)
            if prod:
                prod.current_stock += item.quantity

    db.session.commit()
    return jsonify({"ok": True, "voucher_status": "unapproved",
                    "message": "Invoice unapproved and unlocked"})


@inv_inv_bp.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete_invoice(id):
    inv = InvInvoice.query.get_or_404(id)
    if inv.voucher_status == "approved":
        return jsonify({"ok": False, "error": "Cannot delete an approved invoice. Unapprove it first."}), 400
    try:
        InvInvoiceItem.query.filter_by(invoice_id=inv.id).delete()
        db.session.delete(inv)
        db.session.commit()
        return jsonify({"ok": True, "message": "Invoice deleted successfully"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500


@inv_inv_bp.route("/pay/<int:id>", methods=["POST"])
@login_required
def pay_invoice(id):
    inv = InvInvoice.query.get_or_404(id)
    amount = request.form.get("amount", 0, type=float)
    if amount <= 0:
        flash("Invalid payment amount", "error")
    else:
        inv.paid_amount = (inv.paid_amount or 0) + amount
        if inv.paid_amount >= inv.total_amount:
            inv.payment_status = "paid"
        else:
            inv.payment_status = "partial"
        cash_acc = ChartOfAccount.query.filter_by(code="111").first()
        ar_acc = ChartOfAccount.query.filter_by(code="112").first()
        if cash_acc and ar_acc:
            post_journal_entry(
                voucher_type="PMT",
                voucher_id=inv.id,
                voucher_number=f"PMT-{inv.invoice_number}-{datetime.utcnow():%Y%m%d%H%M%S}",
                description=f"Payment received for {inv.invoice_number} - {inv.customer.name if inv.customer else ''}",
                lines=[
                    {"account_id": cash_acc.id, "debit": amount, "credit": 0,
                     "description": f"Cash - {inv.invoice_number}"},
                    {"account_id": ar_acc.id, "debit": 0, "credit": amount,
                     "description": f"AR - {inv.invoice_number}"},
                ],
                entry_date=datetime.utcnow(),
                created_by=current_user.id,
            )
        db.session.commit()
        flash(f"Payment of {amount} recorded", "success")
    return redirect(url_for("inv_invoices.list_invoices"))


@inv_inv_bp.route("/api/products")
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


@inv_inv_bp.route("/api/customers")
@login_required
def api_customers():
    q = request.args.get("q", "").strip()
    query = InvCustomer.query.filter_by(is_active=True)
    if q:
        query = query.filter(InvCustomer.name.ilike(f"%{q}%"))
    customers = query.order_by(InvCustomer.name).limit(20).all()
    return jsonify([{
        "id": c.id, "name": c.name, "city": c.city or "",
        "phone": c.phone or "", "address": c.address or "",
    } for c in customers])
