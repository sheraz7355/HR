"""The reporting table (gl_daily_balances) follows the ledger exactly.

Every way a journal can change — post, edit an amount, move a line to another
account or label, change the date, unpost, delete, bulk delete — is made
through the ORM, and after each the table must equal the posted journal
lines summed per (account, label, day). Reports read only this table, so this
is the guarantee that a fast report is also a right one.
"""
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), "erp_gl_reporting.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
os.environ["DATABASE_URL"] = (os.environ.get("TEST_DATABASE_URL")
                              or "sqlite:///" + _TMP_DB.replace("\\", "/"))

from app import app as flask_app  # noqa: E402
from shared.extensions import db  # noqa: E402


@pytest.fixture(scope="module")
def ctx():
    flask_app.test_client().get("/")
    from hr_app.models.user import User
    from shared.models.company import CompanyMembership
    from shared.models.ledger import ChartOfAccount
    from shared.tenancy import set_current_company, unscoped
    with flask_app.app_context():
        u = User.query.filter_by(is_super_admin=True).order_by(User.id).first()
        with unscoped():
            m = CompanyMembership.query.filter_by(user_id=u.id).order_by(CompanyMembership.id).first()
        set_current_company(m.company_id)
        accts = [a.id for a in ChartOfAccount.query.filter(ChartOfAccount.level >= 5)
                 .order_by(ChartOfAccount.id).limit(3).all()]
        return {"cid": m.company_id, "uid": u.id, "a": accts}


def _app(ctx):
    from shared.tenancy import set_current_company
    c = flask_app.app_context()
    c.push()
    set_current_company(ctx["cid"])
    return c


def _assert_matches():
    from shared.models.gl_balance import GLDailyBalance as G
    from shared.models.ledger import JournalEntry, JournalLine
    src = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for l, e in (db.session.query(JournalLine, JournalEntry)
                 .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
                 .filter(JournalEntry.is_posted == True).all()):  # noqa: E712
        k = (l.account_id, l.label_id or 0, e.entry_date.date())
        src[k][0] += Decimal(str(l.debit or 0))
        src[k][1] += Decimal(str(l.credit or 0))
    summ = {(r.account_id, r.label_id, r.day): [Decimal(str(r.debit)), Decimal(str(r.credit))]
            for r in G.query.all()}
    src = {k: v for k, v in src.items() if v != [0, 0]}
    summ = {k: v for k, v in summ.items() if v != [0, 0]}
    assert summ == src


def _entry(ctx, when, amt, label=None):
    from shared.models.ledger import JournalEntry, JournalLine
    e = JournalEntry(voucher_type="JV", voucher_id=0, voucher_number="GLR",
                     description="gl reporting", entry_date=when,
                     created_by=ctx["uid"], is_posted=True)
    db.session.add(e)
    db.session.flush()
    db.session.add_all([
        JournalLine(journal_entry_id=e.id, account_id=ctx["a"][0], debit=Decimal(amt),
                    credit=Decimal(0), label_id=label),
        JournalLine(journal_entry_id=e.id, account_id=ctx["a"][1], debit=Decimal(0),
                    credit=Decimal(amt), label_id=label)])
    db.session.commit()
    return e.id


def test_every_change_keeps_the_table_equal_to_the_ledger(ctx):
    from shared.models.ledger import JournalEntry, JournalLine
    c = _app(ctx)
    try:
        day = datetime(2026, 3, 10, 14, 30)
        e1 = _entry(ctx, day, 500)
        _entry(ctx, day, 250)                      # same key, second entry
        _assert_matches()
        # Edit an amount.
        ln = JournalLine.query.filter_by(journal_entry_id=e1, account_id=ctx["a"][0]).one()
        ln.debit = Decimal(800)
        JournalLine.query.filter_by(journal_entry_id=e1, account_id=ctx["a"][1]).one().credit = Decimal(800)
        db.session.commit()
        _assert_matches()
        # Move a line to another account.
        ln = JournalLine.query.filter_by(journal_entry_id=e1, account_id=ctx["a"][0]).one()
        ln.account_id = ctx["a"][2]
        db.session.commit()
        _assert_matches()
        # Back-date the entry.
        db.session.get(JournalEntry, e1).entry_date = day - timedelta(days=40)
        db.session.commit()
        _assert_matches()
        # Unpost, repost.
        db.session.get(JournalEntry, e1).is_posted = False
        db.session.commit()
        _assert_matches()
        db.session.get(JournalEntry, e1).is_posted = True
        db.session.commit()
        _assert_matches()
        # Delete a line, then the whole entry.
        db.session.delete(JournalLine.query.filter_by(journal_entry_id=e1, account_id=ctx["a"][2]).one())
        db.session.commit()
        _assert_matches()
        db.session.delete(db.session.get(JournalEntry, e1))
        db.session.commit()
        _assert_matches()
        # Bulk delete bypasses the flush; the table follows anyway.
        e3 = _entry(ctx, day + timedelta(days=1), 90)
        JournalLine.query.filter_by(journal_entry_id=e3).delete(synchronize_session=False)
        db.session.commit()
        _assert_matches()
    finally:
        c.pop()


def test_reports_read_the_table_and_agree_with_the_ledger(ctx):
    """The trial balance totals (now from the table) equal the raw ledger."""
    from finance_app.routes.reports import _all_account_balances
    from shared.models.ledger import JournalEntry, JournalLine
    c = _app(ctx)
    try:
        rows = _all_account_balances()
        tb_dr = sum(Decimal(str(r.dr)) for r in rows)
        tb_cr = sum(Decimal(str(r.cr)) for r in rows)
        dr, cr = (db.session.query(db.func.coalesce(db.func.sum(JournalLine.debit), 0),
                                   db.func.coalesce(db.func.sum(JournalLine.credit), 0))
                  .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
                  .filter(JournalEntry.is_posted == True).one())  # noqa: E712
        assert tb_dr == Decimal(str(dr)) and tb_cr == Decimal(str(cr))
        from shared import integrity
        chk = integrity.reporting_table()
        assert chk["ok"], chk
    finally:
        c.pop()


def test_rebuild_reproduces_the_table(ctx):
    from shared.gl_summary import rebuild
    c = _app(ctx)
    try:
        rebuild(db.session.connection(), company_id=ctx["cid"])
        db.session.commit()
        _assert_matches()
    finally:
        c.pop()
