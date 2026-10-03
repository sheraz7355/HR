"""Audit trail: who did what, to which record, when — written automatically.

Drives real routes and checks the audit rows they leave: a document's
lifecycle (create → edit → approve → unapprove → delete) with field-level
diffs, the journals it posted and un-posted, refused postings, sign-in
events, secret redaction, company isolation, the viewer and the CSV export.
"""
import json
import os
import tempfile
from datetime import date, timedelta

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), "erp_audit_log.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
# TEST_DATABASE_URL runs the same scenario against Postgres (production is
# Neon); default is a throwaway SQLite file.
os.environ["DATABASE_URL"] = (os.environ.get("TEST_DATABASE_URL")
                              or "sqlite:///" + _TMP_DB.replace("\\", "/"))

from app import app as flask_app  # noqa: E402
from shared.extensions import db  # noqa: E402


def _new_company(uid, slug):
    from shared.models.company import Company, CompanyMembership
    from shared.models.base import Role
    from shared.tenancy import set_current_company, unscoped
    from shared.company_setup import provision_company
    with unscoped():
        comp = Company(name=slug.title(), slug=slug, is_active=True, created_by=uid)
        db.session.add(comp)
        db.session.flush()
        admin_role = Role.query.filter_by(name=Role.ADMIN).first()
        db.session.add(CompanyMembership(company_id=comp.id, user_id=uid,
                                         role_id=admin_role.id,
                                         status=CompanyMembership.ACTIVE))
        db.session.commit()
        cid = comp.id
    set_current_company(cid)
    provision_company(cid)
    set_current_company(cid)
    return cid


@pytest.fixture(scope="module")
def w():
    c = flask_app.test_client()
    c.get("/")
    from hr_app.models.user import User
    from inventory_app.models.product import InvProduct
    from inventory_app.models.supplier import InvSupplier
    with flask_app.app_context():
        # Explicitly the super admin: an unordered first() returns a
        # different row on Postgres than on SQLite.
        user = (User.query.filter_by(is_super_admin=True).order_by(User.id).first()
                or User.query.order_by(User.id).first())
        uid = user.id
        cid = _new_company(uid, "audit-co-e2e")
        prod = InvProduct(sku="AUD-1", name="Audit Bolt", unit="pcs",
                          unit_price=10, cost_price=0, current_stock=0)
        sup = InvSupplier(name="Audit Supplier")
        db.session.add_all([prod, sup])
        db.session.commit()
        ids = {"uid": uid, "cid": cid, "product": prod.id, "supplier": sup.id}
        other = _new_company(uid, "audit-other-e2e")
        ids["other"] = other
    with c.session_transaction() as s:
        s["_user_id"] = str(uid)
        s["_fresh"] = True
        s["company_id"] = cid
    ids["c"] = c
    return ids


def rows(w, **filters):
    from shared.models.audit_log import AuditLog
    with flask_app.app_context():
        q = AuditLog.query.filter_by(**filters).order_by(AuditLog.id)
        return [(r.action, r.entity_type, r.reference, r.summary, r.changes,
                 r.company_id, r.user_id) for r in q.all()]


def purchase(w, qty, price, inv_id=None, action="approve", when=None):
    total = qty * price
    r = w["c"].post("/inventory/purchase-invoice/save", json={
        "id": inv_id, "supplier_id": w["supplier"],
        "invoice_date": when or date.today().isoformat(),
        "discount_mode": "general", "expenses_mode": "general", "tax_mode": "general",
        "global_discount_pct": 0, "global_discount_value": 0, "global_commission": 0,
        "global_freight": 0, "global_loading": 0, "global_sales_tax_pct": 0,
        "global_withholding_tax_pct": 0, "subtotal": total, "total_discount": 0,
        "net_payable": total, "total_amount": total,
        "items": [{"product_id": w["product"], "quantity": qty, "unit_price": price,
                   "discount_pct": 0, "total_before_discount": total,
                   "total_after_discount": total}],
        "action": action})
    return r.get_json() or {}


def test_document_lifecycle_is_audited_with_field_diffs(w):
    body = purchase(w, 5, 20, action="save")
    assert body.get("ok"), body
    inv_id = body["id"]
    trail = rows(w, entity_type="Purchase invoice", entity_id=inv_id)
    assert trail and trail[0][0] == "create"
    assert trail[0][5] == w["cid"] and trail[0][6] == w["uid"]

    purchase(w, 5, 25, inv_id=inv_id, action="save")          # edit
    upd = [t for t in rows(w, entity_type="Purchase invoice", entity_id=inv_id)
           if t[0] == "update"]
    assert upd, "edit not audited"
    fields = {c["field"]: c for c in json.loads(upd[-1][4])}
    assert fields["net_payable"]["old"] == 100 and fields["net_payable"]["new"] == 125

    assert purchase(w, 5, 25, inv_id=inv_id).get("ok")         # approve
    acts = [t[0] for t in rows(w, entity_type="Purchase invoice", entity_id=inv_id)]
    assert "approve" in acts
    posted = rows(w, entity_type="Journal entry", action="post")
    assert any("Purchase Invoice" in (t[3] or "") for t in posted), \
        "the journal the approval posted is audited"

    r = w["c"].post(f"/inventory/purchase-invoice/unapprove/{inv_id}")
    assert r.get_json()["ok"]
    acts = [t[0] for t in rows(w, entity_type="Purchase invoice", entity_id=inv_id)]
    assert "unapprove" in acts
    assert rows(w, entity_type="Journal entry", action="unpost"), \
        "un-posting the journal is audited"

    r = w["c"].post(f"/inventory/purchase-invoice/delete/{inv_id}")
    assert r.get_json()["ok"]
    deleted = [t for t in rows(w, entity_type="Purchase invoice", entity_id=inv_id)
               if t[0] == "delete"]
    assert deleted and "net_payable" in deleted[0][4], "a delete keeps a snapshot"


def test_refused_posting_is_audited_even_though_it_rolled_back(w):
    from shared.models.company_settings import AccountingPeriod
    from shared.tenancy import set_current_company
    with flask_app.app_context():
        set_current_company(w["cid"])
        p = AccountingPeriod(fiscal_year="T", period_name="Locked",
                             start_date=date.today() - timedelta(days=100),
                             end_date=date.today() - timedelta(days=90),
                             is_closed=True)
        db.session.add(p)
        db.session.commit()
    body = purchase(w, 1, 10, when=(date.today() - timedelta(days=95)).isoformat())
    assert body.get("ok") is False
    refused = rows(w, action="refused", company_id=w["cid"])
    assert refused and "closed" in refused[-1][3].lower()


def test_failed_sign_in_is_audited_without_the_password(w):
    anon = flask_app.test_client()
    anon.post("/auth/login", data={"login": "nobody@example.com",
                                   "password": "wrong-pass-123"})
    failed = rows(w, action="login_failed")
    assert failed and "nobody@example.com" in failed[-1][3]
    assert all("wrong-pass-123" not in (t[3] or "") + (t[4] or "") for t in failed)


def test_password_changes_are_redacted(w):
    from hr_app.models.user import User
    with flask_app.app_context():
        u = db.session.get(User, w["uid"])
        u.set_password("Rotated-Secret-9")
        db.session.commit()
    user_rows = rows(w, entity_type="User", entity_id=w["uid"])
    assert user_rows, "user change not audited"
    blob = " ".join((t[4] or "") for t in user_rows)
    assert "Rotated-Secret-9" not in blob and "pbkdf2" not in blob and "scrypt" not in blob
    changed = [c for t in user_rows if t[0] == "update"
               for c in json.loads(t[4] or "[]")]
    pw = [c for c in changed if "password" in c["field"]]
    assert pw and pw[-1]["old"] == "•••" and pw[-1]["new"] == "•••"


def test_viewer_shows_this_company_only_and_exports_csv(w):
    from shared.audit import record_now
    with flask_app.app_context():
        record_now("update", "OTHER-COMPANY-SECRET-EVENT", company_id=w["other"])
    page = w["c"].get("/settings/?tab=audit")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Audit Log" in html and "Purchase invoice" in html
    assert "OTHER-COMPANY-SECRET-EVENT" not in html, "no cross-company leak"

    filtered = w["c"].get("/settings/?tab=audit&action=unapprove").get_data(as_text=True)
    assert "unapprove" in filtered

    csv_resp = w["c"].get("/settings/audit-log.csv?module=invoicing")
    assert csv_resp.status_code == 200
    assert csv_resp.mimetype == "text/csv"
    text = csv_resp.get_data(as_text=True)
    assert text.splitlines()[0].startswith("When (UTC),User,Action")
    assert "Purchase invoice" in text
    assert "OTHER-COMPANY-SECRET-EVENT" not in text


def test_audit_log_is_admin_only(w):
    from shared.models.company import CompanyMembership
    from shared.models.base import Role
    from hr_app.models.user import User
    with flask_app.app_context():
        emp_role = Role.query.filter_by(name=Role.EMPLOYEE).first()
        u = User(email="audit-emp@example.com", login_id="audit-emp@example.com",
                 full_name="Audit Employee", employee_code="AUDEMP1",
                 role_id=emp_role.id, is_active=True)
        u.set_password("emp-pass-123")
        db.session.add(u)
        db.session.flush()
        db.session.add(CompanyMembership(company_id=w["cid"], user_id=u.id,
                                         role_id=emp_role.id,
                                         status=CompanyMembership.ACTIVE))
        db.session.commit()
        emp_id = u.id
    c2 = flask_app.test_client()
    with c2.session_transaction() as s:
        s["_user_id"] = str(emp_id)
        s["_fresh"] = True
        s["company_id"] = w["cid"]
    html = c2.get("/settings/?tab=audit").get_data(as_text=True)
    assert "Every change to a business record" not in html
    assert c2.get("/settings/audit-log.csv").status_code == 403


def test_super_admin_sees_platform_events(w):
    from shared.audit import record_now
    with flask_app.app_context():
        record_now("login", "PLATFORM-CONSOLE-SIGNIN", company_id=None)
    page = w["c"].get("/superadmin/audit/?company_id=platform")
    assert page.status_code == 200
    assert "PLATFORM-CONSOLE-SIGNIN" in page.get_data(as_text=True)
