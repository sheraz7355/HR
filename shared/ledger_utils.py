from decimal import Decimal
from shared.extensions import db
from shared.models.ledger import JournalEntry, JournalLine, ChartOfAccount


# ── Canonical posting accounts ───────────────────────────────────────────────
# Postings must never hardcode a chart-of-accounts *code*, because different
# databases were seeded with different numbering schemes (production uses the
# flat 1000-series; a fresh install of the current seed uses the 111-series).
# Map each semantic ROLE to a canonical code plus any legacy alternates, and
# resolve at posting time — creating the account only if none exist. This keeps
# invoice/voucher postings working regardless of which COA a DB happens to have.
# role -> (canonical_code, name, type, [alternate_codes])
POSTING_ACCOUNTS = {
    "cash":              ("1000", "Cash & Bank", "asset", ["111"]),
    "ar":                ("1100", "Accounts Receivable", "asset", ["112"]),
    "inventory":         ("1200", "Inventory", "asset", ["113"]),
    "fixed_assets":      ("1300", "Fixed Assets", "asset", ["121"]),
    "input_tax":         ("1400", "Input Tax Recoverable", "asset", ["114"]),
    "ap":                ("2000", "Accounts Payable", "liability", ["211"]),
    "accrued":           ("2100", "Accrued Expenses", "liability", ["212"]),
    "loans":             ("2200", "Loans Payable", "liability", ["221"]),
    "wht_payable":       ("6400", "Withholding Tax Payable", "liability", ["214"]),
    "sales_tax_payable": ("6500", "Sales Tax Payable", "liability", ["213"]),
    "revenue":           ("4000", "Sales Revenue", "revenue", ["411"]),
    "cogs":              ("5000", "Cost of Goods Sold", "expense", ["511"]),
}


def posting_account(role):
    """Resolve a semantic posting role to a ChartOfAccount, creating it if the
    canonical and all legacy codes are absent. Never returns None."""
    code, name, type_, alts = POSTING_ACCOUNTS[role]
    acct = ChartOfAccount.query.filter_by(code=code).first()
    if acct:
        return acct
    for alt in alts:
        acct = ChartOfAccount.query.filter_by(code=alt).first()
        if acct:
            return acct
    return get_or_create_account(code, name, type_)


def post_journal_entry(voucher_type, voucher_id, voucher_number, description,
                       lines, entry_date=None, created_by=1):
    from datetime import datetime
    # Defence in depth: a double-entry system must never persist an unbalanced
    # journal. Refuse rather than corrupt the ledger (this is what let an
    # unbalanced cash/bank voucher through before).
    total_debit = sum(Decimal(str(l.get("debit", 0) or 0)) for l in lines)
    total_credit = sum(Decimal(str(l.get("credit", 0) or 0)) for l in lines)
    if abs(total_debit - total_credit) > Decimal("0.01"):
        raise ValueError(
            f"Unbalanced journal for {voucher_number}: "
            f"debits {total_debit} != credits {total_credit}"
        )
    je = JournalEntry(
        voucher_type=voucher_type,
        voucher_id=voucher_id,
        voucher_number=voucher_number,
        description=description,
        entry_date=entry_date or datetime.utcnow(),
        created_by=created_by
    )
    db.session.add(je)
    db.session.flush()

    for line in lines:
        jl = JournalLine(
            journal_entry_id=je.id,
            account_id=line["account_id"],
            debit=Decimal(str(line.get("debit", 0))),
            credit=Decimal(str(line.get("credit", 0))),
            description=line.get("description", "")
        )
        db.session.add(jl)
    db.session.flush()
    return je


def reverse_journal_entry(voucher_type, voucher_id, created_by=1):
    """Un-post the active journal entries for a voucher (used on unapprove).

    Every balance/ledger query filters ``is_posted == True``, so flipping the
    flag removes the entry's effect and returns the affected account balances to
    zero. The rows are retained (not deleted) as an audit trail.

    The previous implementation ALSO created an equal-and-opposite reversal
    entry with ``is_posted=True``. Because the original was simultaneously set
    ``is_posted=False`` (i.e. excluded from every report), only the reversal was
    counted — which *inverted* each affected account's balance instead of
    cancelling it. Marking the original un-posted is sufficient and correct.

    ``created_by`` is accepted for call-site compatibility; it is unused now
    that no new entry is created.
    """
    entries = JournalEntry.query.filter_by(
        voucher_type=voucher_type, voucher_id=voucher_id, is_posted=True
    ).all()
    for entry in entries:
        entry.is_posted = False
    db.session.flush()


def get_account_by_code(code):
    return ChartOfAccount.query.filter_by(code=code).first()


def get_or_create_account(code, name, type_, parent_code=None):
    acct = ChartOfAccount.query.filter_by(code=str(code)).first()
    if not acct:
        parent = None
        if parent_code:
            parent = ChartOfAccount.query.filter_by(code=str(parent_code)).first()
        if not parent:
            # Auto-discover parent by type hierarchy
            coa_type_map = {"asset": "Assets", "liability": "Liabilities", "equity": "Equity",
                            "revenue": "Revenue", "expense": "Expense", "contra-expense": "Expense"}
            l1_name = coa_type_map.get(type_)
            if l1_name:
                l1 = ChartOfAccount.query.filter_by(name=l1_name, level=1).first()
                if l1:
                    l2 = ChartOfAccount.query.filter_by(parent_id=l1.id, level=2).first()
                    if l2:
                        parent = ChartOfAccount.query.filter_by(parent_id=l2.id, level=3).first()
        acct = ChartOfAccount(code=str(code), name=name, type=type_,
                              parent_id=parent.id if parent else None,
                              level=4)
        db.session.add(acct)
        db.session.flush()
    return acct
