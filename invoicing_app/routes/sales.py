from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import date, datetime
from inventory_app.extensions import db
from inventory_app.models.sales_order import InvSalesOrder, InvSalesOrderItem
from inventory_app.models.customer import InvCustomer
from inventory_app.models.product import InvProduct
from inventory_app.models.stock_movement import InvStockMovement
from inventory_app.models.invoice import InvInvoice
from shared.permissions import deny_page

inv_sale_bp = Blueprint("inv_sales", __name__, url_prefix="/inventory/sales")


def next_so_number():
    last = InvSalesOrder.query.order_by(InvSalesOrder.id.desc()).first()
    num = (last.id + 1) if last else 1
    return f"SO-{datetime.utcnow():%Y%m}-{num:04d}"


@inv_sale_bp.route("/")
@login_required
def list_sales():
    status = request.args.get("status", "")
    query = InvSalesOrder.query
    if status:
        query = query.filter_by(status=status)
    orders = query.order_by(InvSalesOrder.id.desc()).all()
    return render_template("sales/list_inv.html", orders=orders)


@inv_sale_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_sale():
    if deny_page("sales_orders", "create"):
        return redirect(url_for("inv_sales.list_sales"))
    if request.method == "POST":
        so = InvSalesOrder(
            so_number=next_so_number(),
            customer_id=request.form.get("customer_id", type=int),
            order_date=date.today(),
            status="unapproved",
            notes=request.form.get("notes", ""),
            created_by=current_user.id,
        )
        db.session.add(so)
        db.session.flush()

        product_ids = request.form.getlist("product_id[]")
        quantities = request.form.getlist("quantity[]")
        prices = request.form.getlist("unit_price[]")
        total = 0
        for pid, qty, price in zip(product_ids, quantities, prices):
            if not pid or not qty:
                continue
            item = InvSalesOrderItem(
                so_id=so.id, product_id=int(pid),
                quantity=int(qty), unit_price=float(price),
                total_price=int(qty) * float(price),
            )
            db.session.add(item)
            total += item.total_price

        so.total_amount = total
        db.session.commit()
        flash(f"Sales Order {so.so_number} created", "success")
        return redirect(url_for("inv_sales.list_sales"))

    customers = InvCustomer.query.filter_by(is_active=True).all()
    products = InvProduct.query.filter_by(is_active=True).all()
    return render_template(
        "sales/form_inv.html", order=None,
        customers=customers, products=[{
            "id": p.id, "name": p.name, "sku": p.sku,
            "unit_price": p.unit_price, "current_stock": p.current_stock,
        } for p in products]
    )


@inv_sale_bp.route("/deliver/<int:id>")
@login_required
def deliver_sale(id):
    if deny_page("sales_orders", "approve"):
        return redirect(url_for("inv_sales.list_sales"))
    so = InvSalesOrder.query.get_or_404(id)
    if so.status in ("delivered", "cancelled"):
        flash("Order already delivered or cancelled", "error")
        return redirect(url_for("inv_sales.list_sales"))

    # Check stock
    insufficient = []
    for item in so.items.all():
        prod = InvProduct.query.get(item.product_id)
        if prod and prod.current_stock < item.quantity:
            insufficient.append(f"{prod.name} (have {prod.current_stock}, need {item.quantity})")

    if insufficient:
        flash(f"Insufficient stock: {', '.join(insufficient)}", "error")
        return redirect(url_for("inv_sales.list_sales"))

    for item in so.items.all():
        prod = InvProduct.query.get(item.product_id)
        if prod:
            prod.current_stock -= item.quantity
            InvStockMovement(
                product_id=prod.id, type="sale_out",
                quantity=item.quantity,
                reference_type="sales_order",
                reference_id=so.id,
                notes=f"Delivered via SO {so.so_number}",
                created_by=current_user.id,
            )

    so.status = "delivered"
    db.session.commit()

    # Auto-create invoice
    inv_num = f"INV-{so.so_number}"
    if not InvInvoice.query.filter_by(invoice_number=inv_num).first():
        inv = InvInvoice(
            invoice_number=inv_num,
            sales_order_id=so.id,
            customer_id=so.customer_id,
            invoice_date=date.today(),
            due_date=date.today(),
            status="unpaid",
            total_amount=so.total_amount,
        )
        db.session.add(inv)
        db.session.commit()

    flash(f"SO {so.so_number} delivered", "success")
    return redirect(url_for("inv_sales.list_sales"))


@inv_sale_bp.route("/cancel/<int:id>")
@login_required
def cancel_sale(id):
    if deny_page("sales_orders", "edit"):
        return redirect(url_for("inv_sales.list_sales"))
    so = InvSalesOrder.query.get_or_404(id)
    so.status = "cancelled"
    db.session.commit()
    flash(f"SO {so.so_number} cancelled", "warning")
    return redirect(url_for("inv_sales.list_sales"))


@inv_sale_bp.route("/delete/<int:id>")
@login_required
def delete_sale(id):
    if deny_page("sales_orders", "delete"):
        return redirect(url_for("inv_sales.list_sales"))
    so = InvSalesOrder.query.get_or_404(id)
    if so.status == "delivered":
        flash("Cannot delete delivered SO", "error")
    else:
        db.session.delete(so)
        db.session.commit()
        flash("SO deleted", "success")
    return redirect(url_for("inv_sales.list_sales"))


@inv_sale_bp.route("/api/products")
@login_required
def api_products():
    products = InvProduct.query.filter_by(is_active=True).all()
    return jsonify([{
        "id": p.id, "name": p.name, "sku": p.sku,
        "unit_price": p.unit_price, "current_stock": p.current_stock
    } for p in products])
