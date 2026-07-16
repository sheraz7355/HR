from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from ..extensions import db
from ..models.product import InvProduct
from ..models.category import InvCategory
from ..models.stock_movement import InvStockMovement
from shared.ledger_utils import create_entity_account
from shared.permissions import deny_page

inv_prod_bp = Blueprint("inv_products", __name__, url_prefix="/inventory/products")


@inv_prod_bp.route("/")
@login_required
def list_products():
    q = request.args.get("q", "")
    cat_id = request.args.get("category_id", type=int)
    query = InvProduct.query
    if q:
        query = query.filter(InvProduct.name.ilike(f"%{q}%") | InvProduct.sku.ilike(f"%{q}%"))
    if cat_id:
        query = query.filter_by(category_id=cat_id)
    products = query.order_by(InvProduct.name).all()
    categories = InvCategory.query.filter_by(is_active=True).all()
    return render_template("products/list_inv.html", products=products, categories=categories)


@inv_prod_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_product():
    if deny_page("products", "create"):
        return redirect(url_for("inv_products.list_products"))
    if request.method == "POST":
        prod = InvProduct(
            sku=request.form["sku"],
            name=request.form["name"],
            description=request.form.get("description", ""),
            category_id=request.form.get("category_id", type=int) or None,
            unit_price=request.form.get("unit_price", 0, type=float),
            cost_price=request.form.get("cost_price", 0, type=float),
            reorder_level=request.form.get("reorder_level", 0, type=int),
            current_stock=request.form.get("current_stock", 0, type=int),
            unit=request.form.get("unit", "pcs"),
        )
        db.session.add(prod)
        db.session.flush()
        create_entity_account("product", prod.id, f"{prod.name} ({prod.sku})")
        db.session.commit()
        flash(f"Product created — ledger account '{prod.name} ({prod.sku})' added under Inventory", "success")
        return redirect(url_for("inv_products.list_products"))
    categories = InvCategory.query.filter_by(is_active=True).all()
    return render_template("products/form_inv.html", product=None, categories=categories)


@inv_prod_bp.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_product(id):
    if deny_page("products", "edit"):
        return redirect(url_for("inv_products.list_products"))
    prod = InvProduct.query.get_or_404(id)
    if request.method == "POST":
        prod.sku = request.form["sku"]
        prod.name = request.form["name"]
        prod.description = request.form.get("description", "")
        prod.category_id = request.form.get("category_id", type=int) or None
        prod.unit_price = request.form.get("unit_price", 0, type=float)
        prod.cost_price = request.form.get("cost_price", 0, type=float)
        prod.reorder_level = request.form.get("reorder_level", 0, type=int)
        prod.unit = request.form.get("unit", "pcs")
        prod.is_active = request.form.get("is_active") == "on"
        create_entity_account("product", prod.id, f"{prod.name} ({prod.sku})")
        db.session.commit()
        flash("Product updated", "success")
        return redirect(url_for("inv_products.list_products"))
    categories = InvCategory.query.filter_by(is_active=True).all()
    return render_template("products/form_inv.html", product=prod, categories=categories)


@inv_prod_bp.route("/delete/<int:id>")
@login_required
def delete_product(id):
    if deny_page("products", "delete"):
        return redirect(url_for("inv_products.list_products"))
    prod = InvProduct.query.get_or_404(id)
    if prod.po_items.count() > 0 or prod.so_items.count() > 0:
        flash("Cannot delete product with order history", "error")
    else:
        db.session.delete(prod)
        db.session.commit()
        flash("Product deleted", "success")
    return redirect(url_for("inv_products.list_products"))


@inv_prod_bp.route("/adjust-stock/<int:id>", methods=["GET", "POST"])
@login_required
def adjust_stock(id):
    prod = InvProduct.query.get_or_404(id)
    if request.method == "POST":
        qty = request.form.get("quantity", 0, type=int)
        note = request.form.get("notes", "")
        if qty == 0:
            flash("Quantity must be non-zero", "error")
        else:
            mtype = "adjustment_in" if qty > 0 else "adjustment_out"
            prod.current_stock += qty
            InvStockMovement(
                product_id=prod.id, type=mtype, quantity=abs(qty),
                notes=note or f"Manual adjustment of {qty}",
                created_by=current_user.id  # noqa
            )
            db.session.add(prod)
            db.session.commit()
            flash(f"Stock adjusted by {qty}. New stock: {prod.current_stock}", "success")
            return redirect(url_for("inv_products.list_products"))
    return render_template("products/adjust_stock_inv.html", product=prod)
