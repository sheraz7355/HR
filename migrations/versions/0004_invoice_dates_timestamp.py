"""Sales invoice dates: DATE -> TIMESTAMP where a live database still has DATE.

Revision ID: 0004_invoice_dates_timestamp
Revises: 0003_gl_reporting
Create Date: 2026-10-05

The model has declared inv_invoices.invoice_date / due_date as DateTime for a
long time, but databases created before that still hold DATE columns, and
create_all() never changes an existing column. Code that treats the value as
a datetime (``invoice_date.date()`` in the return routes) then failed with a
500 on those databases only. Postgres only; on SQLite the type is an affinity.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_invoice_dates_timestamp"
down_revision = "0003_gl_reporting"
branch_labels = None
depends_on = None

COLUMNS = [("inv_invoices", "invoice_date"), ("inv_invoices", "due_date")]


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    for table, column in COLUMNS:
        dtype = conn.execute(sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c"),
            {"t": table, "c": column}).scalar()
        if dtype == "date":
            conn.execute(sa.text(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
                f'TYPE TIMESTAMP WITHOUT TIME ZONE USING "{column}"::timestamp'))


def downgrade():
    pass
