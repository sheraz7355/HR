"""Audit trail: every change to a business record, recorded automatically.

Two sources feed ``AuditLog``:

1. A session hook (``before_flush`` / ``after_flush_postexec``) that watches
   the tracked tables below. Every insert, update and delete on them is
   logged with the user, time, IP, record reference and — for updates — each
   changed field's old and new value. A status change to/from "approved" is
   logged as approve/unapprove; a journal entry insert is "post" and its
   is_posted flipping off is "unpost". Because it sits on the session, every
   module is covered without touching individual routes, and a rolled-back
   request logs nothing (it never happened).

2. ``record_now(...)`` for events that are not row changes — sign-in, failed
   sign-in, sign-out, a posting the period lock or the costing engine refused.
   These are written on their own connection so they survive the rollback of
   the request that triggered them.

Secrets never reach the log: password hashes, tokens and keys are redacted.
"""

import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, inspect as sa_inspect

from shared.extensions import db

# table -> (module, entity label, reference attribute(s))
TRACKED = {
    "inv_invoices": ("invoicing", "Sales invoice", ("invoice_number",)),
    "inv_purchase_invoices": ("invoicing", "Purchase invoice", ("invoice_number",)),
    "inv_sales_returns": ("invoicing", "Sales return", ("return_number",)),
    "inv_purchase_returns": ("invoicing", "Purchase return", ("return_number",)),
    "inv_sales_orders": ("invoicing", "Sales order", ("order_number", "id")),
    "inv_purchase_orders": ("invoicing", "Purchase order", ("order_number", "id")),
    "inv_customers": ("invoicing", "Customer", ("name",)),
    "inv_suppliers": ("invoicing", "Supplier", ("name",)),
    "inv_products": ("inventory", "Product", ("sku", "name")),
    "consumption_vouchers": ("inventory", "Consumption voucher", ("voucher_number",)),
    "scrap_vouchers": ("inventory", "Scrap voucher", ("voucher_number",)),
    "stock_adjustment_vouchers": ("inventory", "Stock adjustment", ("voucher_number",)),
    "stock_takes": ("inventory", "Stock take", ("reference",)),
    "inventory_settings": ("inventory", "Inventory settings", ("id",)),
    "accounting_vouchers": ("accounting", "Accounting voucher", ("voucher_number",)),
    "journal_entries": ("accounting", "Journal entry", ("voucher_number",)),
    "chart_of_accounts": ("accounting", "Account", ("code", "name")),
    "accounting_periods": ("accounting", "Accounting period", ("period_name",)),
    "project_labels": ("accounting", "Project label", ("name",)),
    "company_info": ("settings", "Company profile", ("company_name", "id")),
    "report_settings": ("settings", "Report settings", ("id",)),
    "invoice_settings": ("settings", "Invoice settings", ("id",)),
    "fixed_assets": ("fixed_assets", "Fixed asset", ("asset_code", "name")),
    "asset_transfers": ("fixed_assets", "Asset transfer", ("voucher_number",)),
    "asset_depreciation": ("fixed_assets", "Depreciation", ("id",)),
    "payroll_runs": ("hr", "Payroll run", ("month", "year")),
    "payroll_profiles": ("hr", "Payroll profile", ("user_id",)),
    "users": ("admin", "User", ("email",)),
    "company_memberships": ("admin", "Membership", ("user_id",)),
}

# Never logged: bookkeeping columns, and anything secret.
SKIP_FIELDS = {"updated_at", "last_login", "created_at"}
SECRET_MARKERS = ("password", "token", "secret", "api_key", "otp")

STATUS_FIELDS = ("status", "voucher_status")
MAX_VALUE = 300


def _model_table(obj):
    try:
        return obj.__table__.name
    except AttributeError:
        return None


def _jsonable(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        if isinstance(v, str) and len(v) > MAX_VALUE:
            return v[:MAX_VALUE] + "…"
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)[:MAX_VALUE]


def _secret(field):
    f = field.lower()
    return any(m in f for m in SECRET_MARKERS)


def _reference(obj, attrs):
    if not attrs:
        return None
    if attrs == ("month", "year"):
        return f"{getattr(obj, 'month', '')}/{getattr(obj, 'year', '')}"
    for a in attrs:
        v = getattr(obj, a, None)
        if v not in (None, ""):
            return str(v)[:120]
    return None


def _snapshot(obj):
    out = {}
    for col in obj.__table__.columns:
        k = col.key
        if k in SKIP_FIELDS or k == "id":
            continue
        v = getattr(obj, k, None)
        if v in (None, "", 0, 0.0, False):
            continue
        out[k] = "•••" if _secret(k) else _jsonable(v)
    return out


def _diff(obj):
    """[{field, old, new}] for every column whose value really changed."""
    changes = []
    state = sa_inspect(obj)
    for col in obj.__table__.columns:
        k = col.key
        if k in SKIP_FIELDS:
            continue
        try:
            hist = state.attrs[k].history
        except KeyError:
            continue
        if not hist.has_changes():
            continue
        old = hist.deleted[0] if hist.deleted else None
        new = hist.added[0] if hist.added else None
        if _jsonable(old) == _jsonable(new):
            continue
        if isinstance(old, (int, float, Decimal)) and isinstance(new, (int, float, Decimal)):
            if abs(float(old) - float(new)) < 1e-9:
                continue
        if _secret(k):
            changes.append({"field": k, "old": "•••", "new": "•••"})
        else:
            changes.append({"field": k, "old": _jsonable(old), "new": _jsonable(new)})
    return changes


def _classify_update(table, changes):
    fields = {c["field"]: c for c in changes}
    if table == "journal_entries" and "is_posted" in fields:
        return "unpost" if not fields["is_posted"]["new"] else "post"
    for sf in STATUS_FIELDS:
        if sf in fields:
            old, new = fields[sf]["old"], fields[sf]["new"]
            if new == "approved":
                return "approve"
            if old == "approved":
                return "unapprove"
    return "update"


def _context():
    """(user_id, user_name, ip, path) of the current request, if any."""
    try:
        from flask import has_request_context, request
        from flask_login import current_user
    except Exception:
        return None, None, None, None
    uid = name = ip = path = None
    if has_request_context():
        try:
            if current_user and current_user.is_authenticated:
                uid = current_user.id
                name = (getattr(current_user, "full_name", None)
                        or getattr(current_user, "email", None))
        except Exception:
            pass
        fwd = request.headers.get("X-Forwarded-For", "")
        ip = (fwd.split(",")[0].strip() if fwd else request.remote_addr) or None
        path = (request.path or "")[:300]
    # Postgres enforces VARCHAR lengths (SQLite never did).
    return uid, (name[:200] if name else name), (ip[:64] if ip else ip), path


def _company_for(obj):
    cid = getattr(obj, "company_id", None)
    if cid is not None:
        return cid
    try:
        from shared.tenancy import current_company_id
        return current_company_id()
    except Exception:
        return None


def _summary(action, label, ref, changes, obj):
    ref_txt = f" {ref}" if ref else ""
    verbs = {"create": "created", "delete": "deleted", "approve": "approved",
             "unapprove": "unapproved", "post": "posted", "unpost": "un-posted",
             "update": "edited"}
    text = f"{label}{ref_txt} {verbs.get(action, action)}"
    if action == "update" and changes:
        names = ", ".join(c["field"].replace("_", " ") for c in changes[:4])
        more = f" +{len(changes) - 4} more" if len(changes) > 4 else ""
        text += f" ({names}{more})"
    if action in ("post", "unpost") and hasattr(obj, "description") and obj.description:
        text += f" — {str(obj.description)[:150]}"
    return text[:500]


# ── session hooks ───────────────────────────────────────────────────────────

_PENDING = "_audit_pending"


@event.listens_for(db.session, "before_flush")
def _collect(session, flush_context, instances):
    if session.info.get("audit_disabled"):
        return
    pending = session.info.setdefault(_PENDING, [])
    for obj in list(session.new):
        t = _model_table(obj)
        if t in TRACKED:
            pending.append(("create", obj, None))
    for obj in list(session.dirty):
        t = _model_table(obj)
        if t not in TRACKED or not session.is_modified(obj, include_collections=False):
            continue
        changes = _diff(obj)
        if changes:
            pending.append((_classify_update(t, changes), obj, changes))
    for obj in list(session.deleted):
        t = _model_table(obj)
        if t in TRACKED:
            pending.append(("delete", obj, _snapshot(obj)))


@event.listens_for(db.session, "after_flush_postexec")
def _write(session, flush_context):
    pending = session.info.pop(_PENDING, None)
    if not pending:
        return
    from shared.models.audit_log import AuditLog
    uid, name, ip, path = _context()
    for action, obj, payload in pending:
        t = _model_table(obj)
        module, label, ref_attrs = TRACKED[t]
        if action == "create" and t == "journal_entries":
            action = "post" if getattr(obj, "is_posted", True) else "create"
        if action == "create":
            payload = _snapshot(obj)
        ref = _reference(obj, ref_attrs)
        try:
            entity_id = sa_inspect(obj).identity[0] if sa_inspect(obj).identity else getattr(obj, "id", None)
        except Exception:
            entity_id = getattr(obj, "id", None)
        session.add(AuditLog(
            company_id=_company_for(obj), user_id=uid, user_name=name,
            action=action, module=module, entity_type=label,
            entity_id=entity_id if isinstance(entity_id, int) else None,
            reference=ref, summary=_summary(action, label, ref,
                                            payload if action == "update" else None, obj),
            changes=json.dumps(payload, default=str) if payload else None,
            ip_address=ip, path=path))


@event.listens_for(db.session, "after_rollback")
def _discard(session):
    session.info.pop(_PENDING, None)


# ── explicit events ─────────────────────────────────────────────────────────

def record_now(action, summary, module="admin", entity_type=None, entity_id=None,
               reference=None, company_id=None, user_id=None, user_name=None,
               changes=None):
    """Write one audit row immediately, on its own connection.

    For events that must survive the request being rolled back (a failed
    sign-in, a refused posting) or that change no tracked row at all.
    Never raises — auditing must not take a request down with it.
    """
    try:
        from shared.models.audit_log import AuditLog
        ctx_uid, ctx_name, ip, path = _context()
        if company_id is None:
            try:
                from shared.tenancy import current_company_id
                company_id = current_company_id()
            except Exception:
                company_id = None
        row = {
            "company_id": company_id,
            "created_at": datetime.utcnow(),
            "user_id": user_id if user_id is not None else ctx_uid,
            "user_name": ((user_name or ctx_name) or None) and (user_name or ctx_name)[:200],
            "action": action[:30], "module": module, "entity_type": entity_type,
            "entity_id": entity_id, "reference": (reference or None),
            "summary": (summary or "")[:500],
            "changes": json.dumps(changes, default=str) if changes else None,
            "ip_address": ip, "path": path,
        }
        with db.engine.begin() as conn:
            conn.execute(AuditLog.__table__.insert().values(**row))
    except Exception as e:  # pragma: no cover - defensive
        try:
            from flask import current_app
            current_app.logger.warning("audit record failed: %s", e)
        except Exception:
            pass


def history_for(entity_type, entity_id, company_id):
    """Audit rows for one record, newest first."""
    from shared.models.audit_log import AuditLog
    return (AuditLog.query
            .filter(AuditLog.company_id == company_id,
                    AuditLog.entity_type == entity_type,
                    AuditLog.entity_id == entity_id)
            .order_by(AuditLog.id.desc()).all())


ACTIONS = ("create", "update", "delete", "approve", "unapprove", "post",
           "unpost", "refused", "login", "login_failed", "logout")
MODULES = ("invoicing", "inventory", "accounting", "fixed_assets", "hr",
           "settings", "admin")


def search(company_id, args, member_ids=()):
    """Filtered audit query for one company.

    Rows of the company itself, plus sign-in events (company NULL) of the
    company's own members — an admin should see who signed in to their books,
    but never another company's activity, nor a member's visits to the super
    admin console (those are on the console's own audit page).
    """
    from datetime import datetime as _dt, time as _time
    from shared.models.audit_log import AuditLog
    q = AuditLog.query
    own = AuditLog.company_id == company_id
    if member_ids:
        own = db.or_(own, db.and_(AuditLog.company_id.is_(None),
                                  AuditLog.user_id.in_(list(member_ids)),
                                  AuditLog.action.in_(("login", "logout",
                                                       "login_failed")),
                                  # Entering the super admin console is a
                                  # platform event, not a visit to these books.
                                  db.or_(AuditLog.path.is_(None),
                                         ~AuditLog.path.like("/superadmin%"))))
    q = q.filter(own)

    def _d(v):
        try:
            return _dt.strptime((v or "").strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
    start, end = _d(args.get("from")), _d(args.get("to"))
    if start:
        q = q.filter(AuditLog.created_at >= _dt.combine(start, _time.min))
    if end:
        q = q.filter(AuditLog.created_at <= _dt.combine(end, _time.max))
    if args.get("user_id", "").isdigit():
        q = q.filter(AuditLog.user_id == int(args["user_id"]))
    if args.get("module") in MODULES:
        q = q.filter(AuditLog.module == args["module"])
    if args.get("action") in ACTIONS:
        q = q.filter(AuditLog.action == args["action"])
    term = (args.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        q = q.filter(db.or_(AuditLog.reference.ilike(like),
                            AuditLog.summary.ilike(like),
                            AuditLog.entity_type.ilike(like),
                            AuditLog.user_name.ilike(like)))
    return q.order_by(AuditLog.id.desc())


def decode_changes(row):
    """Changes as a list of {field, old, new} (updates) or [(field, value)]."""
    if not row.changes:
        return []
    try:
        data = json.loads(row.changes)
    except ValueError:
        return []
    if isinstance(data, list):
        return [{"field": c.get("field", "").replace("_", " "),
                 "old": c.get("old"), "new": c.get("new")} for c in data]
    if isinstance(data, dict):
        return [{"field": k.replace("_", " "), "old": None, "new": v}
                for k, v in data.items()]
    return []
