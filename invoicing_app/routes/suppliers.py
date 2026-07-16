from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from inventory_app.extensions import db
from inventory_app.models.supplier import InvSupplier
from shared.ledger_utils import create_entity_account
from shared.permissions import deny_page

inv_sup_bp = Blueprint("inv_suppliers", __name__, url_prefix="/inventory/suppliers")


@inv_sup_bp.route("/")
@login_required
def list_suppliers():
    q = request.args.get("q", "")
    query = InvSupplier.query
    if q:
        query = query.filter(
            InvSupplier.name.ilike(f"%{q}%") | InvSupplier.city.ilike(f"%{q}%")
        )
    suppliers = query.order_by(InvSupplier.name).all()
    return render_template("suppliers/list_inv.html", suppliers=suppliers)


@inv_sup_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_supplier():
    if deny_page("suppliers", "create"):
        return redirect(url_for("inv_suppliers.list_suppliers"))
    if request.method == "POST":
        s = InvSupplier(
            name=request.form["name"],
            contact_person=request.form.get("contact_person", ""),
            email=request.form.get("email", ""),
            phone=request.form.get("phone", ""),
            mobile=request.form.get("mobile", ""),
            address=request.form.get("address", ""),
            city=request.form.get("city", ""),
            tax_id=request.form.get("tax_id", ""),
            payment_terms=request.form.get("payment_terms", ""),
            website=request.form.get("website", ""),
            notes=request.form.get("notes", ""),
        )
        db.session.add(s)
        db.session.flush()
        create_entity_account("supplier", s.id, s.name)
        db.session.commit()
        flash(f"Supplier created — ledger account '{s.name}' added under Trade Creditors", "success")
        return redirect(url_for("inv_suppliers.list_suppliers"))
    return render_template("suppliers/form_inv.html", supplier=None)


@inv_sup_bp.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_supplier(id):
    if deny_page("suppliers", "edit"):
        return redirect(url_for("inv_suppliers.list_suppliers"))
    s = InvSupplier.query.get_or_404(id)
    if request.method == "POST":
        s.name = request.form["name"]
        s.contact_person = request.form.get("contact_person", "")
        s.email = request.form.get("email", "")
        s.phone = request.form.get("phone", "")
        s.mobile = request.form.get("mobile", "")
        s.address = request.form.get("address", "")
        s.city = request.form.get("city", "")
        s.tax_id = request.form.get("tax_id", "")
        s.payment_terms = request.form.get("payment_terms", "")
        s.website = request.form.get("website", "")
        s.notes = request.form.get("notes", "")
        s.is_active = request.form.get("is_active") == "on"
        create_entity_account("supplier", s.id, s.name)
        db.session.commit()
        flash("Supplier updated", "success")
        return redirect(url_for("inv_suppliers.list_suppliers"))
    return render_template("suppliers/form_inv.html", supplier=s)


@inv_sup_bp.route("/delete/<int:id>")
@login_required
def delete_supplier(id):
    if deny_page("suppliers", "delete"):
        return redirect(url_for("inv_suppliers.list_suppliers"))
    s = InvSupplier.query.get_or_404(id)
    if s.purchase_orders.count() > 0:
        flash("Cannot delete supplier with purchase orders", "error")
    else:
        db.session.delete(s)
        db.session.commit()
        flash("Supplier deleted", "success")
    return redirect(url_for("inv_suppliers.list_suppliers"))
