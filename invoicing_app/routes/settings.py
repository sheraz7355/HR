from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from inventory_app.extensions import db
from shared.models.inventory_settings import InventorySettings

inv_settings_bp = Blueprint("inv_settings", __name__,
                            url_prefix="/invoicing/settings")


@inv_settings_bp.route("/", methods=["GET", "POST"])
@login_required
def settings_page():
    s = InventorySettings.get()
    if request.method == "POST":
        s.valuation_method = request.form.get("valuation_method", "weighted_average")
        s.allow_negative_stock = request.form.get("allow_negative_stock") == "on"
        s.decimal_places = int(request.form.get("decimal_places", 4))
        s.purchase_flow = request.form.get("purchase_flow", "with_po")
        s.sales_flow = request.form.get("sales_flow", "with_so")
        db.session.commit()
        flash("Settings saved", "success")
        return redirect(url_for("inv_settings.settings_page"))
    return render_template("settings/form.html", s=s)
