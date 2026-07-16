from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import date, datetime
from inventory_app.extensions import db
from inventory_app.models.purchase_order import InvPurchaseOrder, InvPurchaseOrderItem
from inventory_app.models.supplier import InvSupplier
from inventory_app.models.product import InvProduct
from inventory_app.models.stock_movement import InvStockMovement
from shared.permissions import deny_page

inv_pur_bp = Blueprint("inv_purchases", __name__, url_prefix="/inventory/purchases")


def next_po_number():
    last = InvPurchaseOrder.query.order_by(InvPurchaseOrder.id.desc()).first()
    num = (last.id + 1) if last else 1
    return f"PO-{datetime.utcnow():%Y%m}-{num:04d}"


@inv_pur_bp.route("/")
@login_required
def list_purchases():
    status = request.args.get("status", "")
    query = InvPurchaseOrder.query
    if status:
        query = query.filter_by(status=status)
    orders = query.order_by(InvPurchaseOrder.id.desc()).all()
    return render_template("purchases/list_inv.html", orders=orders)


@inv_pur_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_purchase():
    if deny_page("purchase_orders", "create"):
        return redirect(url_for("inv_purchases.list_purchases"))
    if request.method == "POST":
        po = InvPurchaseOrder(
            po_number=next_po_number(),
            supplier_id=request.form.get("supplier_id", type=int),
            order_date=date.today(),
            expected_date=datetime.strptime(request.form["expected_date"], "%Y-%m-%d").date()
            if request.form.get("expected_date") else None,
            status="unapproved",
            notes=request.form.get("notes", ""),
            created_by=current_user.id,
        )
        db.session.add(po)
        db.session.flush()

        product_ids = request.form.getlist("product_id[]")
        quantities = request.form.getlist("quantity[]")
        prices = request.form.getlist("unit_price[]")
        total = 0
        for pid, qty, price in zip(product_ids, quantities, prices):
            if not pid or not qty:
                continue
            item = InvPurchaseOrderItem(
                po_id=po.id, product_id=int(pid),
                quantity=int(qty), unit_price=float(price),
                total_price=int(qty) * float(price),
            )
            db.session.add(item)
            total += item.total_price

        po.total_amount = total
        db.session.commit()
        flash(f"Purchase Order {po.po_number} created", "success")
        return redirect(url_for("inv_purchases.list_purchases"))

    suppliers = InvSupplier.query.filter_by(is_active=True).all()
    products = InvProduct.query.filter_by(is_active=True).all()
    return render_template(
        "purchases/form_inv.html", order=None,
        suppliers=suppliers, products=[{
            "id": p.id, "name": p.name, "sku": p.sku,
            "unit_price": p.unit_price, "current_stock": p.current_stock,
        } for p in products]
    )


@inv_pur_bp.route("/receive/<int:id>")
@login_required
def receive_purchase(id):
    if deny_page("purchase_orders", "approve"):
        return redirect(url_for("inv_purchases.list_purchases"))
    po = InvPurchaseOrder.query.get_or_404(id)
    if po.status in ("received", "cancelled"):
        flash("Order already received or cancelled", "error")
    else:
        for item in po.items.all():
            prod = InvProduct.query.get(item.product_id)
            if prod:
                prod.current_stock += item.quantity
                InvStockMovement(
                    product_id=prod.id, type="purchase_in",
                    quantity=item.quantity,
                    reference_type="purchase_order",
                    reference_id=po.id,
                    notes=f"Received from PO {po.po_number}",
                    created_by=current_user.id,
                )
        po.status = "received"
        db.session.commit()
        flash(f"PO {po.po_number} received", "success")
    return redirect(url_for("inv_purchases.list_purchases"))


@inv_pur_bp.route("/cancel/<int:id>")
@login_required
def cancel_purchase(id):
    if deny_page("purchase_orders", "edit"):
        return redirect(url_for("inv_purchases.list_purchases"))
    po = InvPurchaseOrder.query.get_or_404(id)
    po.status = "cancelled"
    db.session.commit()
    flash(f"PO {po.po_number} cancelled", "warning")
    return redirect(url_for("inv_purchases.list_purchases"))


@inv_pur_bp.route("/delete/<int:id>")
@login_required
def delete_purchase(id):
    if deny_page("purchase_orders", "delete"):
        return redirect(url_for("inv_purchases.list_purchases"))
    po = InvPurchaseOrder.query.get_or_404(id)
    if po.status == "received":
        flash("Cannot delete received PO", "error")
    else:
        db.session.delete(po)
        db.session.commit()
        flash("PO deleted", "success")
    return redirect(url_for("inv_purchases.list_purchases"))


@inv_pur_bp.route("/api/products")
@login_required
def api_products():
    products = InvProduct.query.filter_by(is_active=True).all()
    return jsonify([{
        "id": p.id, "name": p.name, "sku": p.sku,
        "unit_price": p.unit_price, "current_stock": p.current_stock
    } for p in products])
