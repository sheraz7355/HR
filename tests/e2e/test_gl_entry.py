"""The "Accounting entry" button: the journal a document posted, from any form.

API (in-process, real routes): an approved document returns exactly the
journal lines in the ledger; unapproving moves that journal to history and
leaves nothing posted; a draft and an unsaved document return nothing;
another company's document id returns nothing (tenancy); extra journals
(an asset's depreciation runs) come back with the document.

UI (Playwright): the floating button is on the posting forms, its dot shows
posted/not posted, and the panel lists debits and credits with a balance
check.
"""
import os
import tempfile
from datetime import date

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), "erp_gl_entry.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
os.environ["DATABASE_URL"] = (os.environ.get("TEST_DATABASE_URL")
                              or "sqlite:///" + _TMP_DB.replace("\\", "/"))

from app import app as flask_app  # noqa: E402
from shared.extensions import db  # noqa: E402

BASE_URL = "http://127.0.0.1:" + os.environ.get("E2E_PORT", "5050")


@pytest.fixture(scope="module")
def w():
    c = flask_app.test_client()
    c.get("/")
    from hr_app.models.user import User
    from shared.models.company import CompanyMembership
    from shared.tenancy import set_current_company, unscoped
    from inventory_app.models.product import InvProduct
    from inventory_app.models.customer import InvCustomer
    with flask_app.app_context():
        user = (User.query.filter_by(is_super_admin=True).order_by(User.id).first()
                or User.query.order_by(User.id).first())
        with unscoped():
            m = (CompanyMembership.query.filter_by(user_id=user.id)
                 .order_by(CompanyMembership.id).first())
        set_current_company(m.company_id)
        p = InvProduct.query.filter(InvProduct.current_stock > 5).order_by(InvProduct.id).first()
        cust = InvCustomer.query.order_by(InvCustomer.id).first()
        ids = {"uid": user.id, "cid": m.company_id, "product": p.id,
               "price": float(p.unit_price or 1000), "customer": cust.id}
    with c.session_transaction() as s:
        s["_user_id"] = str(ids["uid"])
        s["_fresh"] = True
        s["company_id"] = ids["cid"]
    ids["c"] = c
    return ids


def _sale(w, action):
    q, pr = 2, w["price"]
    r = w["c"].post("/inventory/invoices/save", json={
        "customer_id": w["customer"], "invoice_date": date.today().isoformat(),
        "discount_mode": "general", "charges_mode": "general", "tax_mode": "general",
        "global_discount_pct": 0, "global_discount_value": 0, "global_delivery": 0,
        "global_installation": 0, "global_sales_tax_pct": 0, "further_tax_pct": 0,
        "apply_further_tax": False, "withholding_tax_pct": 0, "subtotal": q * pr,
        "total_discount": 0, "total_charges": 0, "total_tax": 0, "total_amount": q * pr,
        "items": [{"product_id": w["product"], "quantity": q, "unit_price": pr,
                   "description": "GL entry test", "unit": "pcs", "discount_pct": 0,
                   "delivery": 0, "installation": 0, "sales_tax_pct": 0,
                   "total_before_discount": q * pr, "total_after_discount": q * pr}],
        "action": action})
    body = r.get_json()
    assert body and body.get("ok"), r.get_data(as_text=True)[:300]
    return body["id"]


def _entry(w, vtype, vid, **extra):
    q = f"/accounting/gl-entry?type={vtype}&id={vid}"
    for k, v in extra.items():
        q += f"&{k}={v}"
    r = w["c"].get(q)
    assert r.status_code == 200
    return r.get_json()


def test_approved_invoice_returns_exactly_its_ledger_journal(w):
    inv_id = _sale(w, "approve")
    d = _entry(w, "SI", inv_id)
    assert d["ok"] and d["saved"]
    assert len(d["posted"]) == 1 and d["history"] == []
    e = d["posted"][0]
    assert e["voucher_type"] == "SI" and e["balanced"]
    # Same lines as the ledger holds for it.
    from shared.models.ledger import JournalEntry, JournalLine
    from shared.tenancy import set_current_company
    with flask_app.app_context():
        set_current_company(w["cid"])
        je = JournalEntry.query.filter_by(voucher_type="SI", voucher_id=inv_id,
                                          is_posted=True).one()
        lines = JournalLine.query.filter_by(journal_entry_id=je.id).all()
        expect = sorted((l.account_id, float(l.debit or 0), float(l.credit or 0)) for l in lines)
    got = sorted((l["account_id"], l["debit"], l["credit"]) for l in e["lines"])
    assert got == expect
    # Debits are listed before credits.
    kinds = ["dr" if l["debit"] > 0 else "cr" for l in e["lines"]]
    assert kinds == sorted(kinds, key=lambda k: k == "cr")
    assert e["total_debit"] == pytest.approx(e["total_credit"])
    w["approved"] = inv_id


def test_unapproving_moves_the_journal_to_history(w):
    inv_id = w["approved"]
    r = w["c"].post(f"/inventory/invoices/unapprove/{inv_id}")
    assert r.get_json().get("ok"), r.get_data(as_text=True)[:300]
    d = _entry(w, "SI", inv_id)
    assert d["posted"] == []
    assert len(d["history"]) == 1 and d["history"][0]["posted"] is False


def test_draft_and_unsaved_documents_have_no_entry(w):
    draft = _sale(w, "save")
    d = _entry(w, "SI", draft)
    assert d["saved"] and d["posted"] == [] and d["history"] == []
    d = w["c"].get("/accounting/gl-entry?type=SI").get_json()
    assert d["ok"] and d["saved"] is False


def test_another_companys_document_is_not_visible(w):
    inv_id = _sale(w, "approve")
    from shared.models.company import Company, CompanyMembership
    from shared.models.base import Role
    from shared.tenancy import unscoped
    with flask_app.app_context():
        with unscoped():
            comp = Company(name="GL Other", slug="gl-other-e2e", is_active=True,
                           created_by=w["uid"])
            db.session.add(comp)
            db.session.flush()
            role = Role.query.filter_by(name=Role.ADMIN).first()
            db.session.add(CompanyMembership(company_id=comp.id, user_id=w["uid"],
                                             role_id=role.id, status=CompanyMembership.ACTIVE))
            db.session.commit()
            other = comp.id
    with w["c"].session_transaction() as s:
        s["company_id"] = other
    try:
        d = _entry(w, "SI", inv_id)
        assert d["posted"] == [] and d["history"] == []
    finally:
        with w["c"].session_transaction() as s:
            s["company_id"] = w["cid"]


def test_extra_journals_come_back_with_the_document(w):
    inv_id = _sale(w, "approve")
    # Ask for the invoice as an "also" of a type that has no entry itself.
    d = _entry(w, "FA-ACQ", 999999, also=f"SI:{inv_id}")
    assert len(d["posted"]) == 1 and d["posted"][0]["kind"] == "related"


def test_bad_type_is_refused(w):
    r = w["c"].get("/accounting/gl-entry?type=" + "X" * 40 + "&id=1")
    assert r.status_code == 400


# ── UI ──

def test_button_and_panel_on_an_approved_invoice(admin_page):
    from tests.e2e.test_invoice_form_flow import _open_new, _seed_line
    page = admin_page
    _open_new(page)
    fab = page.locator("#gleFab")
    assert fab.is_visible()
    fab.click()
    assert page.locator("#glePanel").is_visible()
    page.wait_for_selector("#gleBody .gle-empty")
    assert "Nothing posted yet" in page.locator("#gleBody").inner_text()
    page.keyboard.press("Escape")
    assert page.locator("#glePanel").is_hidden()
    _seed_line(page)
    page.locator("#saveApproveBtn").click()
    page.locator("#confirmOkBtn").click()
    page.wait_for_selector(".ap-b")
    page.wait_for_load_state("networkidle")
    page.wait_for_function("document.getElementById('gleFab').dataset.state === 'posted'")
    page.locator("#gleFab").click()
    page.wait_for_selector("#gleBody .gle-tbl")
    text = page.locator("#gleBody").inner_text()
    assert "Balanced" in text and "Sales invoice" in text
    assert page.locator("#gleBody .gle-dr").count() >= 1
    assert page.locator("#gleBody .gle-cr").count() >= 1
    # Each account opens in the general ledger.
    href = page.locator("#gleBody .gle-acc a").first.get_attribute("href")
    assert href.startswith("/finance/ledger?") and "account_ids=" in href


@pytest.mark.parametrize("path", [
    "/inventory/purchase-invoice/", "/accounting/vouchers",
    "/inventory/vouchers/consumption", "/inventory/vouchers/scrap",
    "/inventory/vouchers/adjustment"])
def test_button_is_on_every_posting_form(admin_page, path):
    admin_page.goto(BASE_URL + path)
    admin_page.wait_for_load_state("networkidle")
    assert admin_page.locator("#gleFab").count() == 1
