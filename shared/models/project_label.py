from datetime import datetime
from shared.extensions import db


class ProjectLabel(db.Model):
    """Company-scoped project label used to tag journal lines.

    Two kinds exist (``kind``): "voucher" labels are used on cash/bank
    vouchers (the header pick tags the settlement line, per-line picks tag
    the economic lines); "invoice" labels are used on sales/purchase invoices
    (the party pick tags the AR/AP line, per-item picks tag the economic
    lines). Line labels inherit the header label by default unless changed
    manually, and the single company default (``is_default``) fills every
    slot that stays untouched. A label is archived (``is_active=False``)
    rather than deleted, because historical journal lines may still reference
    it; the reporting filter keeps offering archived labels so old postings
    stay reachable.
    """
    __tablename__ = "project_labels"
    __table_args__ = (
        db.UniqueConstraint("company_id", "name",
                            name="uq_project_labels_company_name"),
    )
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(10), default="voucher",
                     nullable=False)  # voucher | invoice
    is_active = db.Column(db.Boolean, default=True)
    # Company-wide default: vouchers / invoices saved without an explicit
    # label get this one automatically. Deactivated defaults are ignored
    # (see default()), so an archive can never keep auto-assigning.
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def default(cls):
        """The active default label for the current company, or None."""
        return (cls.query.filter_by(is_default=True, is_active=True)
                .order_by(cls.id).first())
