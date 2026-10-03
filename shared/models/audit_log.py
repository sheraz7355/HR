from datetime import datetime

from shared.extensions import db


class AuditLog(db.Model):
    """Append-only audit trail: who did what, to which record, and when.

    Written automatically for every tracked document (shared/audit.py hooks
    the session), plus explicit events such as sign-in, failed sign-in and
    refused postings. Nothing in the app updates or deletes these rows.

    ``company_id`` is set explicitly (NULL for platform events like a super
    admin signing in), so the table is in tenancy.GLOBAL_TABLES and every
    reader filters by company itself.
    """

    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True,
                           nullable=False)
    user_id = db.Column(db.Integer, index=True)
    user_name = db.Column(db.String(200))
    # create / update / delete / approve / unapprove / post / unpost /
    # login / login_failed / logout / refused ...
    action = db.Column(db.String(30), nullable=False, index=True)
    module = db.Column(db.String(30), index=True)
    entity_type = db.Column(db.String(60), index=True)
    entity_id = db.Column(db.Integer, index=True)
    reference = db.Column(db.String(120), index=True)
    summary = db.Column(db.String(500))
    # JSON: [{"field": ..., "old": ..., "new": ...}] for updates, or a
    # snapshot of key fields for creates/deletes.
    changes = db.Column(db.Text)
    ip_address = db.Column(db.String(64))
    path = db.Column(db.String(300))
