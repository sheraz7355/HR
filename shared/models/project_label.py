from datetime import datetime
from shared.extensions import db


class ProjectLabel(db.Model):
    """Company-scoped project label used to tag journal lines.

    One shared pool serves every document class: cash/bank vouchers (the
    header pick tags the settlement line, per-line picks tag the economic
    lines) and sales/purchase invoices (the party pick tags the AR/AP line,
    per-item picks tag the item lines). Line labels inherit the header/party
    label by default unless changed manually; each document class keeps its
    own default (InventorySettings.default_voucher_label_id /
    default_invoice_label_id) that fills every slot saved without a pick.
    A label is archived (``is_active=False``) rather than deleted, because
    historical journal lines may still reference it; the reporting filter
    keeps offering archived labels so old postings stay reachable.
    """
    __tablename__ = "project_labels"
    __table_args__ = (
        db.UniqueConstraint("company_id", "name",
                            name="uq_project_labels_company_name"),
    )
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)