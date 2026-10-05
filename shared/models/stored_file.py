"""Uploaded file bytes, kept in the database.

Vercel's filesystem is read-only except /tmp, and /tmp belongs to one
short-lived instance: a file written there by one request is gone for the
next. Postgres (Neon) is the only storage every instance shares, so uploads
(profile pictures, employee documents) live here. See shared/file_store.py.

Tenant-scoped through company_id like any other business table: one
company can never read another's files.
"""
from datetime import datetime

from shared.extensions import db


class StoredFile(db.Model):
    __tablename__ = "stored_files"
    __table_args__ = (db.UniqueConstraint("company_id", "key",
                                          name="uq_stored_files_company_key"),)

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, index=True)
    # Path-like name inside the company, e.g. "avatars/avatar_3_1700000.png"
    # or "<user_id>/<uuid>.pdf" — the same layout uploads/<company_id>/ had.
    key = db.Column(db.String(300), nullable=False)
    content_type = db.Column(db.String(120))
    size = db.Column(db.Integer, nullable=False, default=0)
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
