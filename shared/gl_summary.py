"""Keeps ``gl_daily_balances`` (shared/models/gl_balance.py) in step with the
general ledger, inside the same transaction as every posting.

How it stays exact without trusting any caller:

- ``before_flush`` notes every journal entry whose lines or posted state are
  about to change, and reads the (company, account, label, day) keys those
  entries cover in the database *before* the change.
- ``after_flush`` reads the keys they cover *after* the change, and
  recomputes each affected key from journal_lines — delete the summary rows,
  insert the fresh sums. Old keys matter: moving a line to another account
  or date, unposting, or deleting must empty the key it left.
- A bulk ``query.update()`` / ``query.delete()`` on the journal tables
  bypasses the flush, so ``do_orm_execute`` rebuilds the active company's
  summary after such a statement.

Writes go through the session's Core connection, so they neither re-enter
the ORM hooks nor touch the audit trail, and they commit or roll back with
the posting itself.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import and_, bindparam, event, select, text

from shared.extensions import db
from shared.models.gl_balance import GLDailyBalance
from shared.models.ledger import JournalEntry, JournalLine

T = GLDailyBalance.__table__
JE = JournalEntry.__table__
JL = JournalLine.__table__
ZERO = Decimal("0")


def _day(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and v:
        return datetime.fromisoformat(v[:19]).date() if len(v) > 10 else date.fromisoformat(v)
    return None


def _keys_for_entries(conn, entry_ids):
    """(company, account, label, day) keys the entries' lines cover now."""
    keys = set()
    ids = list(entry_ids)
    for i in range(0, len(ids), 500):
        rows = conn.execute(
            select(JL.c.company_id, JE.c.company_id, JL.c.account_id,
                   JL.c.label_id, JE.c.entry_date)
            .select_from(JL.join(JE, JL.c.journal_entry_id == JE.c.id))
            .where(JE.c.id.in_(ids[i:i + 500]))).all()
        for lc, ec, acc, lab, d in rows:
            day = _day(d)
            if day is not None and acc is not None:
                keys.add((lc if lc is not None else ec, acc, lab or 0, day))
    return keys


def recompute(conn, keys):
    """Rewrite the summary rows for exactly these keys from journal_lines."""
    keys = {k for k in keys if k[0] is not None}
    if not keys:
        return
    accounts = sorted({k[1] for k in keys})
    days = [k[3] for k in keys]
    lo = datetime.combine(min(days), time.min)
    hi = datetime.combine(max(days) + timedelta(days=1), time.min)
    agg = defaultdict(lambda: [ZERO, ZERO, 0])
    for i in range(0, len(accounts), 500):
        rows = conn.execute(
            select(JL.c.company_id, JE.c.company_id, JL.c.account_id, JL.c.label_id,
                   JE.c.entry_date, JL.c.debit, JL.c.credit)
            .select_from(JL.join(JE, JL.c.journal_entry_id == JE.c.id))
            .where(JE.c.is_posted == True,  # noqa: E712
                   JL.c.account_id.in_(accounts[i:i + 500]),
                   JE.c.entry_date >= lo, JE.c.entry_date < hi)).all()
        for lc, ec, acc, lab, d, dr, cr in rows:
            k = (lc if lc is not None else ec, acc, lab or 0, _day(d))
            if k in keys:
                a = agg[k]
                a[0] += Decimal(str(dr or 0))
                a[1] += Decimal(str(cr or 0))
                a[2] += 1
    conn.execute(
        T.delete().where(and_(T.c.company_id == bindparam("k_c"), T.c.account_id == bindparam("k_a"),
                              T.c.label_id == bindparam("k_l"), T.c.day == bindparam("k_d"))),
        [{"k_c": c, "k_a": a, "k_l": l, "k_d": d} for c, a, l, d in keys])
    rows = [{"company_id": c, "account_id": a, "label_id": l, "day": d,
             "debit": v[0], "credit": v[1], "line_count": v[2]}
            for (c, a, l, d), v in agg.items() if v[2]]
    if rows:
        conn.execute(T.insert(), rows)


def rebuild(conn, company_id=None):
    """Recompute the whole summary (one company, or all) from journal_lines."""
    dialect = conn.dialect.name
    day = "CAST(e.entry_date AS DATE)" if dialect == "postgresql" else "date(e.entry_date)"
    comp = "COALESCE(jl.company_id, e.company_id)"
    where = "e.is_posted = :posted"
    params = {"posted": True}
    if company_id is not None:
        where += f" AND {comp} = :cid"
        params["cid"] = company_id
        conn.execute(T.delete().where(T.c.company_id == company_id))
    else:
        conn.execute(T.delete())
    conn.execute(text(
        "INSERT INTO gl_daily_balances (company_id, account_id, label_id, day, debit, credit, line_count) "
        f"SELECT {comp}, jl.account_id, COALESCE(jl.label_id, 0), {day}, "
        "COALESCE(SUM(jl.debit), 0), COALESCE(SUM(jl.credit), 0), COUNT(*) "
        "FROM journal_lines jl JOIN journal_entries e ON jl.journal_entry_id = e.id "
        f"WHERE {where} AND {comp} IS NOT NULL "
        f"GROUP BY {comp}, jl.account_id, COALESCE(jl.label_id, 0), {day}"), params)


# ── session hooks ───────────────────────────────────────────────────────

def _touched_entry_ids(objs):
    ids, new = set(), []
    for o in objs:
        if isinstance(o, JournalLine):
            if o.journal_entry_id:
                ids.add(o.journal_entry_id)
            else:
                new.append(o)
        elif isinstance(o, JournalEntry):
            if o.id:
                ids.add(o.id)
            else:
                new.append(o)
    return ids, new


@event.listens_for(db.session, "before_flush")
def _gl_before_flush(session, flush_context, instances):
    ids, new = _touched_entry_ids(list(session.new) + list(session.dirty) + list(session.deleted))
    if not ids and not new:
        return
    pend = session.info.setdefault("gl_summary", {"old": set(), "ids": set(), "new": []})
    if ids:
        pend["old"] |= _keys_for_entries(session.connection(), ids)
        pend["ids"] |= ids
    pend["new"].extend(new)


@event.listens_for(db.session, "after_flush")
def _gl_after_flush(session, flush_context):
    pend = session.info.pop("gl_summary", None)
    if not pend:
        return
    ids = set(pend["ids"])
    for o in pend["new"]:
        eid = o.journal_entry_id if isinstance(o, JournalLine) else o.id
        if eid:
            ids.add(eid)
    conn = session.connection()
    keys = set(pend["old"])
    if ids:
        keys |= _keys_for_entries(conn, ids)
    recompute(conn, keys)


@event.listens_for(db.session, "after_rollback")
def _gl_after_rollback(session):
    session.info.pop("gl_summary", None)


@event.listens_for(db.session, "do_orm_execute")
def _gl_bulk(state):
    if not (state.is_update or state.is_delete):
        return None
    mapper = state.bind_arguments.get("mapper")
    if mapper is None or mapper.class_ not in (JournalLine, JournalEntry):
        return None
    result = state.invoke_statement()
    from shared.tenancy import current_company_id
    rebuild(state.session.connection(), company_id=current_company_id())
    return result
