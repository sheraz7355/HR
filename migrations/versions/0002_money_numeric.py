"""Document amounts: DOUBLE PRECISION -> NUMERIC(20, 6) on Postgres.

Revision ID: 0002_money_numeric
Revises: 0001_baseline
Create Date: 2026-10-05

The models now declare these columns with shared.models.money.Money; a fresh
database already gets NUMERIC from create_all(), so only columns still
holding a binary float are altered. One ALTER TABLE per table keeps it to a
single table rewrite each. SQLite is left alone: its column type is only an
affinity and cannot be altered in place.

The column list is frozen here on purpose (not read from the live models),
so later model changes cannot change what this revision did.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_money_numeric"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

TARGET = "NUMERIC(20, 6)"

MONEY_COLUMNS = {
    "additional_charges": ["amount"],
    "asset_depreciation": [
        "amount", "accumulated_after", "net_book_value_after",
    ],
    "asset_transfers": ["transfer_amount"],
    "fa_categories": ["default_salvage_value_pct"],
    "fixed_assets": [
        "purchase_cost", "salvage_value", "accumulated_depreciation",
        "current_book_value",
    ],
    "income_tax_slabs": [
        "min_income", "max_income", "rate_pct", "fixed_amount",
    ],
    "inv_customers": ["credit_limit"],
    "inv_invoice_items": [
        "quantity", "unit_price", "discount_pct", "discount_amount",
        "delivery", "installation", "sales_tax_pct", "total_before_discount",
        "total_after_discount",
    ],
    "inv_invoices": [
        "global_discount_pct", "global_discount_value", "global_delivery",
        "global_installation", "global_sales_tax_pct", "further_tax_pct",
        "withholding_tax_pct", "subtotal", "total_discount", "total_charges",
        "total_tax", "total_further_tax", "total_withholding_tax",
        "total_amount", "paid_amount",
    ],
    "inv_products": ["unit_price", "cost_price", "weight"],
    "inv_purchase_invoice_items": [
        "quantity", "unit_price", "discount_pct", "discount_amount",
        "commission", "freight", "loading_unloading", "sales_tax_pct",
        "withholding_tax_pct", "total_before_discount",
        "total_after_discount",
    ],
    "inv_purchase_invoices": [
        "global_discount_pct", "global_discount_value", "global_commission",
        "global_freight", "global_loading", "global_sales_tax_pct",
        "global_withholding_tax_pct", "further_tax_pct", "subtotal",
        "total_discount", "total_expenses", "total_tax", "total_further_tax",
        "total_withholding_tax", "net_payable", "total_amount", "paid_amount",
    ],
    "inv_purchase_order_items": [
        "quantity", "invoiced_qty", "unit_price", "sales_tax_pct",
        "total_before_discount", "total_after_discount", "total_price",
    ],
    "inv_purchase_orders": [
        "global_sales_tax_pct", "subtotal", "total_tax", "total_amount",
    ],
    "inv_purchase_return_items": [
        "original_quantity", "previously_returned_qty", "max_returnable_qty",
        "current_return_qty", "unit_price", "discount_pct", "discount_amount",
        "commission", "freight", "loading_unloading", "sales_tax_pct",
        "withholding_tax_pct", "total_before_discount",
        "total_after_discount", "proportional_discount",
        "proportional_sales_tax", "proportional_withholding_tax",
        "proportional_commission", "proportional_freight",
        "proportional_loading", "net_return_value",
    ],
    "inv_purchase_returns": [
        "gross_return_value", "total_discount", "total_expenses", "total_tax",
        "net_return_amount",
    ],
    "inv_sales_order_items": [
        "quantity", "invoiced_qty", "unit_price", "sales_tax_pct",
        "total_before_discount", "total_after_discount", "total_price",
    ],
    "inv_sales_orders": [
        "global_sales_tax_pct", "subtotal", "total_tax", "total_amount",
    ],
    "inv_sales_return_items": [
        "original_quantity", "previously_returned_qty", "max_returnable_qty",
        "current_return_qty", "unit_price", "discount_pct", "discount_amount",
        "delivery", "installation", "sales_tax_pct", "total_before_discount",
        "total_after_discount", "proportional_discount",
        "proportional_sales_tax", "proportional_delivery",
        "proportional_installation", "net_return_value", "cost_basis",
        "total_cost_returned",
    ],
    "inv_sales_returns": [
        "gross_return_value", "total_discount", "total_charges", "total_tax",
        "net_return_amount", "total_cost_returned",
    ],
    "invoice_settings": [
        "default_sales_tax_pct", "default_further_tax_pct",
        "default_withholding_tax_pct", "default_discount_pct",
        "over_invoice_tolerance_pct",
    ],
    "leave_requests": ["total_days"],
    "loan_advance_requests": [
        "amount", "monthly_installment", "remaining_amount",
    ],
    "loan_repayments": ["amount"],
    "payroll_components": ["value"],
    "payroll_profiles": ["basic_salary"],
    "payroll_runs": ["total_gross", "total_deductions", "total_net"],
    "payroll_slips": [
        "basic_salary", "allowances", "deductions", "gross_pay",
        "total_deductions", "net_pay",
    ],
    "pf_config": [
        "employee_contribution_pct", "employer_contribution_pct",
        "max_loan_percentage", "interest_rate",
    ],
    "pf_contributions": ["employee_amount", "employer_amount", "total_amount"],
    "pf_ledger": ["debit", "credit", "balance"],
    "pf_loan_requests": ["amount", "monthly_installment", "remaining_amount"],
    "pf_profit_distributions": ["total_profit"],
    "pf_settlements": [
        "total_employee_contrib", "total_employer_contrib",
        "total_profit_distributed", "outstanding_loan", "net_settlement",
    ],
    "pf_withdrawal_requests": ["amount"],
    "salary_revisions": ["previous_basic", "new_basic"],
    "tax_rate_accounts": ["rate_pct"],
}


def _float_columns(conn):
    rows = conn.execute(sa.text(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        "AND data_type IN ('double precision', 'real')")).all()
    return {(t, c) for t, c in rows}


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    floats = _float_columns(conn)
    for table, cols in MONEY_COLUMNS.items():
        todo = [c for c in cols if (table, c) in floats]
        if not todo:
            continue
        clauses = ", ".join(
            f'ALTER COLUMN "{c}" TYPE {TARGET} USING round("{c}"::numeric, 6)'
            for c in todo)
        conn.execute(sa.text(f'ALTER TABLE "{table}" {clauses}'))


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    for table, cols in MONEY_COLUMNS.items():
        clauses = ", ".join(
            f'ALTER COLUMN "{c}" TYPE DOUBLE PRECISION' for c in cols)
        conn.execute(sa.text(f'ALTER TABLE "{table}" {clauses}'))
