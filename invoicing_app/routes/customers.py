from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from inventory_app.extensions import db
from inventory_app.models.customer import InvCustomer
from shared.ledger_utils import create_entity_account
from shared.permissions import deny_page

inv_cust_bp = Blueprint("inv_customers", __name__, url_prefix="/inventory/customers")


@inv_cust_bp.route("/")
@login_required
def list_customers():
    q = request.args.get("q", "")
    query = InvCustomer.query
    if q:
        query = query.filter(
            InvCustomer.name.ilike(f"%{q}%") | InvCustomer.city.ilike(f"%{q}%")
        )
    customers = query.order_by(InvCustomer.name).all()
    return render_template("customers/list_inv.html", customers=customers)


@inv_cust_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_customer():
    if deny_page("customers", "create"):
        return redirect(url_for("inv_customers.list_customers"))
    if request.method == "POST":
        c = InvCustomer(
            name=request.form["name"],
            contact_person=request.form.get("contact_person", ""),
            email=request.form.get("email", ""),
            phone=request.form.get("phone", ""),
            mobile=request.form.get("mobile", ""),
            address=request.form.get("address", ""),
            city=request.form.get("city", ""),
            tax_id=request.form.get("tax_id", ""),
            payment_terms=request.form.get("payment_terms", ""),
            credit_limit=request.form.get("credit_limit", 0, type=float),
            website=request.form.get("website", ""),
            notes=request.form.get("notes", ""),
        )
        db.session.add(c)
        db.session.flush()
        create_entity_account("customer", c.id, c.name)
        db.session.commit()
        flash(f"Customer created — ledger account '{c.name}' added under Trade Debtors", "success")
        return redirect(url_for("inv_customers.list_customers"))
    return render_template("customers/form_inv.html", customer=None)


@inv_cust_bp.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_customer(id):
    if deny_page("customers", "edit"):
        return redirect(url_for("inv_customers.list_customers"))
    c = InvCustomer.query.get_or_404(id)
    if request.method == "POST":
        c.name = request.form["name"]
        c.contact_person = request.form.get("contact_person", "")
        c.email = request.form.get("email", "")
        c.phone = request.form.get("phone", "")
        c.mobile = request.form.get("mobile", "")
        c.address = request.form.get("address", "")
        c.city = request.form.get("city", "")
        c.tax_id = request.form.get("tax_id", "")
        c.payment_terms = request.form.get("payment_terms", "")
        c.credit_limit = request.form.get("credit_limit", 0, type=float)
        c.website = request.form.get("website", "")
        c.notes = request.form.get("notes", "")
        c.is_active = request.form.get("is_active") == "on"
        create_entity_account("customer", c.id, c.name)
        db.session.commit()
        flash("Customer updated", "success")
        return redirect(url_for("inv_customers.list_customers"))
    return render_template("customers/form_inv.html", customer=c)


@inv_cust_bp.route("/delete/<int:id>")
@login_required
def delete_customer(id):
    c = InvCustomer.query.get_or_404(id)
    if c.sales_orders.count() > 0 or c.invoices.count() > 0:
        flash("Cannot delete customer with sales history", "error")
    else:
        db.session.delete(c)
        db.session.commit()
        flash("Customer deleted", "success")
    return redirect(url_for("inv_customers.list_customers"))
