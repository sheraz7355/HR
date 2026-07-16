from flask import Blueprint, render_template
from flask_login import login_required

from inventory_app.models.invoice import InvInvoice
from inventory_app.models.purchase_invoice import InvPurchaseInvoice
from inventory_app.models.purchase_return import InvPurchaseReturn
from inventory_app.models.supplier import InvSupplier
from inventory_app.models.customer import InvCustomer
from inventory_app.models.purchase_order import InvPurchaseOrder
from inventory_app.models.sales_order import InvSalesOrder

invoicing_bp = Blueprint("invoicing", __name__, url_prefix="/invoicing")


@invoicing_bp.route("/")
@login_required
def dashboard():
    supplier_total = InvSupplier.query.count()
    customer_total = InvCustomer.query.count()
    po_pending = InvPurchaseOrder.query.filter(
        InvPurchaseOrder.status.in_(["unapproved", "pending"])
    ).count()
    so_pending = InvSalesOrder.query.filter(
        InvSalesOrder.status.in_(["unapproved", "confirmed"])
    ).count()
    sales_total = InvInvoice.query.count()
    sales_unapproved = InvInvoice.query.filter_by(voucher_status="unapproved").count()
    sales_unpaid = InvInvoice.query.filter(
        InvInvoice.voucher_status == "approved",
        InvInvoice.payment_status != "paid",
    ).count()
    purchase_total = InvPurchaseInvoice.query.count()
    return_total = InvPurchaseReturn.query.count()
    return render_template(
        "dashboard/index_invoicing.html",
        supplier_total=supplier_total,
        customer_total=customer_total,
        po_pending=po_pending,
        so_pending=so_pending,
        sales_total=sales_total,
        sales_unapproved=sales_unapproved,
        sales_unpaid=sales_unpaid,
        purchase_total=purchase_total,
        return_total=return_total,
    )
