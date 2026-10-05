"""Executive Reports — receivables and payables, derived from the ledger.

The whole module is a READ of the general ledger. It writes no journal, holds
no balances of its own, and stores nothing but the list of accounts to watch:

* Every figure is recomputed from posted ``JournalLine`` rows on each request.
  Edit a voucher, unapprove it, delete it, and the numbers here follow on the
  next page load — there is no cached total to go stale.
* Which side a party appears on is decided by the sign of its balance, not by
  the account's type. A trade debtor sitting on a credit balance (an advance,
  an over-receipt) belongs in Payables and shows there. When the next voucher
  flips the sign, the party moves on its own.
* Removing every selection, or the whole module, would leave the ledger and
  every other report identical.

"Party" means one posting account: the entity subledger accounts created per
customer, supplier or employee already carry the party's name, so an account
is the finest grain the ledger can answer at.
"""

from datetime import datetime, date, timedelta
import math
from decimal import Decimal, ROUND_HALF_UP

from shared.extensions import db
from shared.models.ledger import ChartOfAccount, JournalEntry, JournalLine
from shared.models.exec_report import ExecAccountSelection

CENT = Decimal("0.01")
# Balances below this are treated as settled: a party whose debits and credits
# cancel is not owed anything and is not a row worth showing.
TOLERANCE = Decimal("0.01")

RECEIVABLE = "receivable"
PAYABLE = "payable"

SIDE_META = {
    RECEIVABLE: {
        "title": "Receivables",
        "noun": "receivable",
        "party_word": "owes us",
        "empty": "No selected account is carrying a debit balance.",
    },
    PAYABLE: {
        "title": "Payables",
        "noun": "payable",
        "party_word": "we owe",
        "empty": "No selected account is carrying a credit balance.",
    },
}


def _q(value):
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _f(value):
    return float(_q(value))


def _eod(dt):
    """End of the given day, so an "as of" date includes that day's postings."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return datetime.combine(dt, datetime.max.time())


# ── Selected accounts ───────────────────────────────────────────────────────

def _children_index():
    """``{parent_id: [child accounts]}`` over the whole chart."""
    index = {}
    for acct in ChartOfAccount.query.all():
        index.setdefault(acct.parent_id, []).append(acct)
    return index


def selections():
    """The raw picks, newest chart order first."""
    rows = (ExecAccountSelection.query
            .join(ChartOfAccount,
                  ExecAccountSelection.account_id == ChartOfAccount.id)
            .order_by(ChartOfAccount.code).all())
    return rows


def scope(as_dict=False):
    """Every account currently in scope, expanded through the tree.

    ``{account_id: (root_account_id, root_name)}`` — the root being the picked
    ancestor, so a row can say which control account it came from.
    """
    picks = selections()
    if not picks:
        return {} if as_dict else set()

    kids = _children_index()
    out = {}
    for pick in picks:
        root = pick.account
        if root is None:
            continue
        label = f"{root.code} · {root.name}"
        stack = [root]
        first = True
        while stack:
            node = stack.pop()
            # The pick itself is always in scope; descendants only when the
            # selection says so.
            if first or pick.include_children:
                out[int(node.id)] = (int(root.id), label)
            if pick.include_children:
                stack.extend(kids.get(node.id, []))
            first = False
    return out if as_dict else set(out)


def _glb_day(d):
    """A report date (date or datetime) as a calendar day, for the reporting
    table (gl_daily_balances)."""
    from datetime import datetime as _dt
    return d.date() if isinstance(d, _dt) else d


def _balances(account_ids, as_of=None):
    """``{account_id: (debit_total, credit_total)}`` from posted journal lines.

    Posted lines only — an unapproved voucher has not moved anything, and a
    reversal is itself a posting, so unapproving a voucher nets its party back
    to zero here without anything having to be recalculated.
    """
    if not account_ids:
        return {}
    # The reporting table (posted activity per account and day), not every
    # journal line.
    from shared.models.gl_balance import GLDailyBalance as G
    q = (db.session.query(
            G.account_id,
            db.func.coalesce(db.func.sum(G.debit), 0).label("dr"),
            db.func.coalesce(db.func.sum(G.credit), 0).label("cr"))
         .filter(G.account_id.in_(list(account_ids))))
    if as_of:
        q = q.filter(G.day <= _glb_day(as_of))
    q = q.group_by(G.account_id)
    return {int(r.account_id): (_q(r.dr), _q(r.cr)) for r in q.all()}


# ── The two registers ───────────────────────────────────────────────────────

def party_rows(side=None, as_of=None, search=None, group_id=None):
    """One row per account in scope that is carrying a balance.

    ``side`` filters to receivable / payable; omit it for both. Accounts that
    net to nothing are left out entirely — they are settled, not a debt.
    """
    in_scope = scope(as_dict=True)
    if not in_scope:
        return []
    balances = _balances(in_scope.keys(), as_of)
    if not balances:
        return []

    accounts = {int(a.id): a for a in ChartOfAccount.query.filter(
        ChartOfAccount.id.in_(list(balances.keys()))).all()}

    term = (search or "").strip().lower()
    rows = []
    for account_id, (dr, cr) in balances.items():
        acct = accounts.get(account_id)
        if acct is None:
            continue
        net = _q(dr - cr)
        if abs(net) < TOLERANCE:
            continue
        # The rule the whole module turns on: the sign decides the side, not
        # the account's type.
        row_side = RECEIVABLE if net > 0 else PAYABLE
        if side and row_side != side:
            continue
        root_id, root_label = in_scope.get(account_id, (None, ""))
        if group_id and root_id != int(group_id):
            continue
        if term and term not in acct.name.lower() and term not in acct.code.lower():
            continue
        rows.append({
            "account_id": account_id,
            "code": acct.code,
            "name": acct.name,
            "type": acct.type,
            "group_id": root_id,
            "group": root_label,
            "debit": _f(dr),
            "credit": _f(cr),
            "amount": _f(abs(net)),
            "side": row_side,
        })
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return rows


def totals(rows):
    """The two figures the page leads with: how much, and across how many."""
    return {
        "amount": _f(sum(Decimal(str(r["amount"])) for r in rows)) if rows else 0.0,
        "parties": len(rows),
    }


def both_sides(as_of=None):
    """Totals for each side in one pass — for the module dashboard."""
    rows = party_rows(as_of=as_of)
    return {
        RECEIVABLE: totals([r for r in rows if r["side"] == RECEIVABLE]),
        PAYABLE: totals([r for r in rows if r["side"] == PAYABLE]),
    }


def groups():
    """The picked control accounts, for the register's group filter."""
    out = []
    for pick in selections():
        if pick.account is None:
            continue
        out.append({"id": int(pick.account.id),
                    "label": f"{pick.account.code} · {pick.account.name}"})
    return out


def account_ledger(account_id, as_of=None, limit=200):
    """The postings behind one party's balance, newest first.

    This is the "why" behind a row — and because it reads the same journal the
    balance came from, an edited or reversed voucher shows here too.
    """
    q = (db.session.query(JournalLine, JournalEntry)
         .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
         .filter(JournalEntry.is_posted == True,   # noqa: E712
                 JournalLine.account_id == int(account_id)))
    if as_of:
        q = q.filter(JournalEntry.entry_date <= _eod(as_of))
    pairs = q.order_by(JournalEntry.entry_date.desc(),
                       JournalEntry.id.desc()).limit(limit).all()
    out = []
    for line, entry in pairs:
        out.append({
            "date": entry.entry_date,
            "voucher_type": entry.voucher_type,
            "voucher_number": entry.voucher_number,
            "description": line.description or entry.description or "",
            "debit": _f(line.debit),
            "credit": _f(line.credit),
        })
    return out


# ── Settings ────────────────────────────────────────────────────────────────

def selectable_accounts():
    """The whole chart, ordered for a tree picker, with selection state."""
    picked = {int(s.account_id): s for s in ExecAccountSelection.query.all()}
    accounts = ChartOfAccount.query.order_by(ChartOfAccount.code).all()
    parents = {int(a.parent_id) for a in accounts if a.parent_id is not None}
    out = []
    for a in accounts:
        sel = picked.get(int(a.id))
        out.append({
            "id": int(a.id),
            "code": a.code,
            "name": a.name,
            "type": a.type,
            "level": a.level or 5,
            "parent_id": a.parent_id,
            "selected": sel is not None,
            "include_children": bool(sel.include_children) if sel else True,
            # "Include sub-accounts" only means something on a parent — leaves
            # get no toggle at all, not a disabled one.
            "has_children": int(a.id) in parents,
        })
    return out


def set_selection(account_ids, include_children_ids=None, user_id=None):
    """Replace the whole selection with the given accounts.

    Replace rather than merge: the settings screen posts the full picture, and
    a merge would make unticking an account impossible.
    """
    def _ids(values):
        out = set()
        for i in (values or []):
            try:
                out.add(int(i))
            except (TypeError, ValueError):
                continue  # crafted non-numeric ids are ignored, not a 500
        return out

    wanted = _ids(account_ids)
    deep = _ids(include_children_ids)

    existing = {int(s.account_id): s for s in ExecAccountSelection.query.all()}
    for account_id, row in existing.items():
        if account_id not in wanted:
            db.session.delete(row)
        else:
            row.include_children = account_id in deep
    for account_id in wanted - set(existing):
        db.session.add(ExecAccountSelection(
            account_id=account_id,
            include_children=account_id in deep,
            created_by=user_id))
    db.session.commit()
    return len(wanted)


# ── Aging ────────────────────────────────────────────────────────────────────
#
# Every open party balance is aged from its own posting layers by FIFO: on the
# receivable side debits build the stack and credits consume the oldest layer
# first; on the payable side credits build it and debits consume it. The layers
# still on the stack are what is actually owed, and their age in days drives
# the buckets, the weighted-average collection / payment period, and the oldest
# debt on each side.

# (key, label, min days, max days — None = unbounded)
BUCKET_DEFS = (
    ("current", "Current", 0, 30),
    ("d31", "31–60 days", 31, 60),
    ("d61", "61–90 days", 61, 90),
    ("d91", "90+ days", 91, None),
)


def _aging_side(parties):
    """Collapse the per-party FIFO stacks into one side's dashboard view."""
    total = _f(sum(Decimal(str(p["amount"])) for p in parties)) if parties else 0.0
    buckets = []
    for key, label, lo, hi in BUCKET_DEFS:
        amount = sum(
            amount for p in parties
            for days, amount in p["layers"]
            if lo <= days and (hi is None or days <= hi))
        buckets.append({
            "key": key,
            "label": label,
            "amount": _f(Decimal(str(amount))),
            "share": _f(Decimal(str(amount)) / Decimal(str(total)) * 100)
            if total else 0.0,
        })
    avg_days = (sum(p["avg_days"] * p["amount"] for p in parties) / total
                if total else 0.0)
    top = sorted(parties, key=lambda p: p["amount"], reverse=True)[:5]
    oldest = max(parties, key=lambda p: p["oldest_days"]) if parties else None
    return {
        "total": total,
        "parties": len(parties),
        "avg_days": float(avg_days),
        "oldest_days": oldest["oldest_days"] if oldest else 0,
        "oldest_name": oldest["name"] if oldest else "",
        "oldest_code": oldest["code"] if oldest else "",
        "oldest_account_id": oldest["account_id"] if oldest else None,
        "buckets": buckets,
        "top": [{
            "name": p["name"],
            "code": p["code"],
            "account_id": p["account_id"],
            "amount": p["amount"],
            "share": _f(Decimal(str(p["amount"])) / Decimal(str(total)) * 100)
            if total else 0.0,
        } for p in top],
    }


def _age_party(account_id, acct, rows, balance, as_of_day, side):
    """FIFO-age one account: returns the surviving layers, oldest day, and
    the weighted average age of what remains."""
    layers = []  # [entry_date, remaining amount] — oldest first
    # A settlement that arrives before anything it could settle (an advance
    # from a customer, a prepayment to a supplier) is held here and applied
    # to the next layers as they open. Dropping it left the layers summing to
    # more than the balance: advance 400 then invoice 1,000 aged 1,000 against
    # a 600 balance, inflating the average and pushing bucket shares past 100%.
    unapplied = _q(0)
    add_idx, take_idx = (1, 2) if side == RECEIVABLE else (2, 1)
    for entry_date, dr, cr in rows:
        add = _q(dr if add_idx == 1 else cr)
        if add and unapplied:
            used = min(add, unapplied)
            add, unapplied = _q(add - used), _q(unapplied - used)
        if add:
            layers.append([entry_date, add])
        take = _q(cr if take_idx == 2 else dr)
        while take and layers:
            if layers[0][1] <= take:
                take = _q(take - layers[0][1])
                layers.pop(0)
            else:
                layers[0][1] = _q(layers[0][1] - take)
                take = None
        if take:
            unapplied = _q(unapplied + take)
    if not layers:
        return None

    ages = []
    total = _q(balance)
    for entry_date, amount in layers:
        days = max((as_of_day - entry_date.date()).days, 0)
        ages.append((days, amount))
    avg_days = float(sum(d * float(a) for d, a in ages) / float(total))
    return {
        "account_id": account_id,
        "code": acct.code,
        "name": acct.name,
        "amount": _f(total),
        "avg_days": avg_days,
        "oldest_days": max(d for d, _ in ages),
        "layers": ages,
    }


def _aged_parties(in_scope, as_of=None):
    """FIFO-age every open in-scope account: (receivable, payable) lists of
    _age_party() results."""
    as_of_day = as_of.date() if isinstance(as_of, datetime) else (
        as_of if isinstance(as_of, date) else datetime.utcnow().date())

    # Daily totals from the reporting table are exactly what FIFO aging needs:
    # within one day every layer is the same age.
    from shared.models.gl_balance import GLDailyBalance as G
    q = (db.session.query(G.account_id, G.day,
                          db.func.sum(G.debit), db.func.sum(G.credit))
         .filter(G.account_id.in_(list(in_scope.keys()))))
    if as_of:
        q = q.filter(G.day <= _glb_day(as_of))
    postings = {}
    for acc_id, day, dr, cr in q.group_by(G.account_id, G.day).order_by(G.day).all():
        postings.setdefault(int(acc_id), []).append(
            (datetime.combine(day, datetime.min.time()), _q(dr), _q(cr)))

    accounts = {int(a.id): a for a in ChartOfAccount.query.filter(
        ChartOfAccount.id.in_(list(postings.keys()))).all()}
    receivable, payable = [], []
    for account_id, rows in postings.items():
        net = _q(sum(dr - cr for _, dr, cr in rows))
        if abs(net) < TOLERANCE:
            continue
        acct = accounts.get(account_id)
        if acct is None:
            continue
        side = RECEIVABLE if net > 0 else PAYABLE
        party = _age_party(account_id, acct, rows, abs(net), as_of_day, side)
        if party:
            (receivable if side == RECEIVABLE else payable).append(party)
    return receivable, payable


def party_aging(as_of=None):
    """{account_id: {"buckets": {key: amount}, "avg_days", "oldest_days"}}
    for every open in-scope balance — the per-party view of aging(), used by
    the receivable/payable register exports."""
    in_scope = scope(as_dict=True)
    if not in_scope:
        return {}
    out = {}
    for party in sum(_aged_parties(in_scope, as_of), []):
        buckets = {key: 0.0 for key, *_ in BUCKET_DEFS}
        for days, amount in party["layers"]:
            for key, _label, lo, hi in BUCKET_DEFS:
                if days >= lo and (hi is None or days <= hi):
                    buckets[key] += float(amount)
                    break
        out[party["account_id"]] = {"buckets": buckets,
                                    "avg_days": party["avg_days"],
                                    "oldest_days": party["oldest_days"]}
    return out


def aging(as_of=None):
    """Age every open balance in scope, one side against the other.

    Returns ``{receivable: …, payable: …}``, each a side summary: total,
    party count, weighted-average days, oldest debt (days + party), the four
    buckets, and the five largest parties with their share of the total.
    """
    in_scope = scope(as_dict=True)
    if not in_scope:
        # Still scaled: the template reads bucket["width"] unconditionally,
        # and an empty scope is the most likely way to reach this page.
        empty = {RECEIVABLE: _aging_side([]), PAYABLE: _aging_side([])}
        _scale_buckets(empty[RECEIVABLE], empty[PAYABLE])
        return empty
    receivable, payable = _aged_parties(in_scope, as_of)
    sides = {
        RECEIVABLE: _aging_side(receivable),
        PAYABLE: _aging_side(payable),
    }
    _scale_buckets(sides[RECEIVABLE], sides[PAYABLE])
    return sides


def _scale_buckets(recv, pay):
    """Give the paired buckets a width both sides can be measured against.

    ``share`` is a bucket's percentage of *its own side*. That is the right
    number to print and the wrong one to draw: the dashboard puts the
    receivable and payable bars for one bucket in the same row, under one
    label, with a legend inviting the comparison. Drawn from ``share`` on
    equal-length tracks, 725,000 of receivable and 200 of payable come out as
    two identical full-width bars — the chart asks to be read as a comparison
    and then answers a different question on each row.

    ``width`` scales every bar against the largest single bucket on either
    side, so one pixel means the same amount everywhere in the chart. With
    both sides empty every width is 0 rather than a division by it.
    """
    peak = max((b["amount"] for b in recv["buckets"] + pay["buckets"]),
               default=0.0)
    for side in (recv, pay):
        for bucket in side["buckets"]:
            bucket["width"] = (
                _f(Decimal(str(bucket["amount"])) / Decimal(str(peak)) * 100)
                if peak else 0.0)
        side["peak"] = peak


# ── Liquidity snapshot ───────────────────────────────────────────────────────
#
# Company-wide (the whole chart, not just the exec scope) and so available
# even before any account is picked. Current Assets / Current Liabilities are
# located by their standard names at level 2, inventory by the Inventories
# subtree, and every figure is a plain balance — accumulated depreciation is a
# credit on an asset, which nets itself out with no special handling.

def _subtree_ids(kids_index, node_id):
    out, stack = [], [node_id]
    while stack:
        nid = stack.pop()
        out.append(nid)
        stack.extend(int(child.id) for child in kids_index.get(nid, []))
    return out


def _named_child(kids_index, accounts, parent_id, name):
    for child in kids_index.get(parent_id, []):
        acct = accounts.get(int(child.id))
        if acct is not None and acct.name == name:
            return acct
    return None


def liquidity(as_of=None):
    """Net assets plus current / quick ratios, derived from the chart.

    Returns ``None``-safe fields: the ratios are ``None`` when current
    liabilities are zero (no comparison is meaningful), net assets when the
    chart has no level-1 asset and liability roots.
    """
    assets_root = ChartOfAccount.query.filter(
        ChartOfAccount.type == "asset",
        ChartOfAccount.level == 1).first()
    liab_root = ChartOfAccount.query.filter(
        ChartOfAccount.type == "liability",
        ChartOfAccount.level == 1).first()
    if assets_root is None or liab_root is None:
        return {
            "net_assets": None, "total_assets": 0.0, "total_liabilities": 0.0,
            "current_assets": 0.0, "current_liabilities": 0.0,
            "inventory": 0.0, "current_ratio": None, "quick_ratio": None,
        }

    kids = _children_index()
    all_ids = (_subtree_ids(kids, int(assets_root.id))
               + _subtree_ids(kids, int(liab_root.id)))
    balances = _balances(all_ids, as_of)
    accounts = {int(a.id): a for a in ChartOfAccount.query.filter(
        ChartOfAccount.id.in_(all_ids)).all()}

    def _net(nid):
        dr, cr = balances.get(nid, (Decimal("0.00"), Decimal("0.00")))
        return _q(dr - cr)

    total_assets = _f(sum(_net(nid) for nid, acct in accounts.items()
                          if acct.type == "asset"))
    total_liabilities = _f(-sum(_net(nid) for nid, acct in accounts.items()
                                if acct.type == "liability"))

    current = {}
    for root, ttype, cname in (
            (assets_root, "asset", "Current Assets"),
            (liab_root, "liability", "Current Liabilities")):
        node = _named_child(kids, accounts, int(root.id), cname)
        nids = _subtree_ids(kids, int(node.id)) if node else []
        total = sum(_net(nid) for nid in nids)
        # Liabilities are held in credit, so debit-minus-credit nets negative
        # for a perfectly normal payable. Flip it to a positive magnitude, the
        # same convention total_liabilities already uses — without this the
        # denominator is negative on healthy books, the `cl > 0` guard below
        # never passes, and the ratio tiles read "—" for every company that is
        # not in trouble.
        current[ttype] = _f(-total if ttype == "liability" else total)

    inventory = 0.0
    inv_node = next((a for a in accounts.values()
                     if a.name == "Inventories"), None)
    if inv_node is not None:
        nids = _subtree_ids(kids, int(inv_node.id))
        inventory = _f(sum(_net(nid) for nid in nids))

    ca = current["asset"]
    cl = current["liability"]
    # A negative "liability" balance is really an asset (overpaid, drifted
    # payroll) — a ratio against it would be a meaningless negative number, so
    # the dashboard shows "—" instead.
    ratios = cl > 0
    return {
        "net_assets": _f(total_assets - total_liabilities),
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "current_assets": ca,
        "current_liabilities": cl,
        "inventory": inventory,
        "current_ratio": _f(ca / cl) if ratios else None,
        "quick_ratio": _f((ca - inventory) / cl) if ratios else None,
    }


# ── Profitability ────────────────────────────────────────────────────────────
#
# Revenue, gross profit and net profit month by month, straight off the posted
# ledger. The arithmetic is deliberately NOT reimplemented here: it calls the
# same _pl_by_section() the Profit & Loss report renders from, so the number on
# the executive dashboard and the number on the statement can never disagree.
# That is the whole point of sourcing this from the ledger rather than from
# shared/invoicing_performance.py, which counts documents and would drift the
# moment anyone posted a journal by hand.
#
# The import is function-local on purpose. shared/ importing from finance_app/
# is a layering inversion, and doing it at module scope would make every
# importer of this module drag in the finance blueprint.

# Sections whose contributions add up to net sales, and the one that is cost of
# sales. Both are keys from DEFAULT_PL_STRUCTURE; a company that has renamed
# its structure keeps working because a missing key simply contributes nothing.
_REVENUE_SECTIONS = ("sales", "sales_returns")
_COGS_SECTIONS = ("cost_of_sales",)


def _month_starts(end_day, count):
    """The first day of each of the `count` months ending with end_day's."""
    year, month = end_day.year, end_day.month
    out = []
    for _ in range(count):
        out.append(date(year, month, 1))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(out))


def _month_end(day):
    return (date(day.year + 1, 1, 1) if day.month == 12
            else date(day.year, day.month + 1, 1)) - timedelta(days=1)


def _pl_figures(from_date, to_date):
    """(net sales, cost of sales, gross profit, net profit) for one window.

    `contrib` from _pl_by_section is a signed contribution to profit: revenue
    positive, expenses negative, contra accounts self-correcting. So net profit
    is simply every section added up — the same running total _pl_rows()
    accumulates — and cost of sales has to be negated to read as a cost.
    """
    from finance_app.routes.reports import _pl_by_section

    by_section = _pl_by_section(from_date, to_date)
    total = lambda keys: sum(  # noqa: E731 - a name would not make this clearer
        (item["contrib"] for key in keys for item in by_section.get(key, [])),
        Decimal("0"))

    revenue = total(_REVENUE_SECTIONS)
    cogs_contrib = total(_COGS_SECTIONS)
    net = sum((item["contrib"] for items in by_section.values() for item in items),
              Decimal("0"))
    return (_f(revenue), _f(-cogs_contrib), _f(revenue + cogs_contrib), _f(net))


def _delta(now, before):
    """Percentage change, or None where the base makes one meaningless.

    Growth from zero is undefined, not infinite, and growth from a negative
    base has no sign anyone can read — both render as an em dash.
    """
    if before is None or before <= 0:
        return None
    return _f(Decimal(str(now - before)) / Decimal(str(before)) * 100)


def profitability(months=12, as_of=None):
    """Monthly revenue / gross / net profit plus the current month's deltas.

    Returns the series oldest-first (a chart reads left to right), the totals
    for the whole window, the figures for the latest month with their
    year-on-year deltas, and the peak/trough the chart has to fit.
    """
    end_day = as_of.date() if isinstance(as_of, datetime) else (
        as_of if isinstance(as_of, date) else datetime.utcnow().date())

    series = []
    for start in _month_starts(end_day, months):
        end = _month_end(start)
        revenue, cogs, gross, net = _pl_figures(start, end)
        series.append({
            "start": start, "label": start.strftime("%b"),
            "full_label": start.strftime("%b %Y"),
            "revenue": revenue, "cogs": cogs, "gross": gross, "net": net,
        })

    latest = series[-1] if series else {"revenue": 0.0, "cogs": 0.0,
                                        "gross": 0.0, "net": 0.0}
    # Same month last year, so a seasonal business is compared like for like.
    prior = None
    if series:
        want = date(series[-1]["start"].year - 1, series[-1]["start"].month, 1)
        prior = next((m for m in series if m["start"] == want), None)
    if prior is None and series:
        prior_start = date(end_day.year - 1, end_day.month, 1)
        revenue, cogs, gross, net = _pl_figures(prior_start,
                                                _month_end(prior_start))
        prior = {"revenue": revenue, "cogs": cogs, "gross": gross, "net": net}

    totals = {key: _f(sum(Decimal(str(m[key])) for m in series)) if series else 0.0
              for key in ("revenue", "cogs", "gross", "net")}
    values = [m[key] for m in series for key in ("revenue", "net")]
    return {
        "months": series,
        "totals": totals,
        "latest": latest,
        "prior": prior,
        "deltas": {key: _delta(latest[key], prior[key] if prior else None)
                   for key in ("revenue", "gross", "net")},
        "peak": max(values, default=0.0),
        "trough": min(min(values, default=0.0), 0.0),
        "margin": (_f(Decimal(str(totals["net"])) / Decimal(str(totals["revenue"])) * 100)
                   if totals["revenue"] else None),
    }


# ── Profitability chart geometry ─────────────────────────────────────────────
#
# Coordinates are worked out here, not in Jinja: a chart's geometry is exactly
# the kind of thing that needs a test, and a template is the one place in this
# codebase nothing can unit-test (UI_V2_GUIDE.md §6). The template receives
# strings and prints them.
#
# Two series, not three. The chart exists to answer "are we making money", so
# net profit is the subject and revenue is the context it is read against;
# gross profit is a tile above rather than a third line competing for the same
# ink. Revenue is also dashed, so the pair survives greyscale and colour vision
# deficiency without relying on the ink/muted difference alone (§6, §8).

PROFIT_SERIES = [
    {"key": "revenue", "label": "Revenue",    "var": "rev", "dash": "5 4"},
    {"key": "net",     "label": "Net profit", "var": "net", "dash": ""},
]


def profit_chart(data):
    """Turn a `profitability()` payload into ready-to-print SVG geometry."""
    from shared.invoicing_performance import (
        PAD_B, PAD_L, PAD_T, PLOT_H, PLOT_W, VIEW_H, VIEW_W, _nice_step)

    months = data["months"]
    if not months:
        return None
    # A ledger with no posted revenue or expenses would otherwise render a
    # flat line along zero with a duplicated axis — a chart that looks like
    # a finding when it is really an absence. The caller shows an empty
    # state instead.
    if not any(m["revenue"] or m["net"] for m in months):
        return None

    hi = max([m["revenue"] for m in months] + [m["net"] for m in months] + [0.0])
    lo = min([m["net"] for m in months] + [0.0])
    if hi == lo:
        hi = lo + 1.0
    step = _nice_step(hi - lo)
    top = math.ceil(hi / step) * step
    bottom = math.floor(lo / step) * step
    if top == bottom:
        top = bottom + step

    span = float(len(months) - 1) or 1.0

    def y_of(value):
        return PAD_T + PLOT_H * (top - value) / (top - bottom)

    def x_of(i):
        return PAD_L + (PLOT_W * i / span if len(months) > 1 else PLOT_W / 2)

    dp = 0 if step >= 1 else max(0, -math.floor(math.log10(step)))
    ticks, tick = [], bottom
    while tick <= top + step / 1000.0:
        ticks.append({"v": tick, "y": round(y_of(tick), 2), "dp": dp})
        tick += step

    zero_y = round(y_of(0), 2)
    series = []
    for spec in PROFIT_SERIES:
        pts = [(round(x_of(i), 2), round(y_of(m[spec["key"]]), 2))
               for i, m in enumerate(months)]
        series.append({
            **spec,
            "points": " ".join(f"{x},{y}" for x, y in pts),
            # The wash closes onto the zero line rather than the floor of the
            # box: with a loss month, a fill dropped to the bottom would read
            # as though the value were positive the whole way down.
            "area": (f"{pts[0][0]},{zero_y} "
                     + " ".join(f"{x},{y}" for x, y in pts)
                     + f" {pts[-1][0]},{zero_y}"),
            "dots": [{"x": x, "y": y, "v": months[i][spec["key"]],
                      "month": months[i]["full_label"]}
                     for i, (x, y) in enumerate(pts)],
            "last": {"x": pts[-1][0], "y": pts[-1][1],
                     "v": months[-1][spec["key"]]},
        })
    return {
        "view_w": VIEW_W, "view_h": VIEW_H,
        "pad_l": PAD_L, "pad_t": PAD_T, "pad_b": PAD_B,
        "plot_w": PLOT_W, "plot_h": PLOT_H,
        "plot_r": PAD_L + PLOT_W, "plot_b": PAD_T + PLOT_H,
        "zero_y": zero_y,
        "ticks": ticks, "series": series,
        "cols": [{"x": round(x_of(i), 2), "label": m["label"],
                  "full_label": m["full_label"], "i": i}
                 for i, m in enumerate(months)],
        "band": round(PLOT_W / span, 2),
    }
