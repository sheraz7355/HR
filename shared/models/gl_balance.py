"""Reporting table: posted general-ledger activity summed per account, label
and day.

Reports (trial balance, balance sheet, P&L, SOCIE, cash flow, label P&L,
executive balances and aging) read this table instead of summing every
journal line. A financial year is at most ~365 rows per account here, against
every line ever posted in journal_lines.

Only POSTED journals are counted. ``label_id`` is 0 for unlabelled lines (a
real value rather than NULL, so the natural key can be unique).

Kept in step with the ledger by ``shared/gl_summary.py``, inside the same
transaction as the posting; ``shared/integrity.py`` checks it against the
ledger and ``tools/rebuild_gl_summary.py`` rebuilds it.
"""
from shared.extensions import db


class GLDailyBalance(db.Model):
    __tablename__ = "gl_daily_balances"
    __table_args__ = (
        db.UniqueConstraint("company_id", "account_id", "label_id", "day",
                            name="uq_gl_daily_balances_key"),
        db.Index("ix_gl_daily_balances_company_day", "company_id", "day"),
        db.Index("ix_gl_daily_balances_account_day", "account_id", "day"),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, index=True, nullable=False)
    account_id = db.Column(db.Integer, nullable=False)
    label_id = db.Column(db.Integer, nullable=False, default=0)
    day = db.Column(db.Date, nullable=False)
    debit = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    credit = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    line_count = db.Column(db.Integer, nullable=False, default=0)
