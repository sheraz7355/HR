"""Reporting table gl_daily_balances + journal indexes, backfilled.

Revision ID: 0003_gl_reporting
Revises: 0002_money_numeric
Create Date: 2026-10-05

create_all() has already created gl_daily_balances (and, on a fresh
database, the journal indexes). On a live database this adds the indexes
the reports filter by and fills the reporting table from the posted ledger
once; from then on shared/gl_summary.py keeps it in step.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_gl_reporting"
down_revision = "0002_money_numeric"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_journal_entries_company_posted_date", "journal_entries", "company_id, is_posted, entry_date"),
    ("ix_journal_entries_voucher", "journal_entries", "voucher_type, voucher_id"),
    ("ix_journal_lines_entry", "journal_lines", "journal_entry_id"),
    ("ix_journal_lines_account_entry", "journal_lines", "account_id, journal_entry_id"),
]


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())
    for name, table, cols in INDEXES:
        if table in tables:
            conn.execute(sa.text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))
    if "gl_daily_balances" in tables:
        has_rows = conn.execute(sa.text("SELECT 1 FROM gl_daily_balances LIMIT 1")).first()
        if not has_rows:
            from shared.gl_summary import rebuild
            rebuild(conn)


def downgrade():
    conn = op.get_bind()
    for name, _t, _c in INDEXES:
        conn.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
