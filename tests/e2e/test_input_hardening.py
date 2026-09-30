"""Bad input never 500s, and user-entered names are never rendered raw.

Blank or garbage numeric fields used to raise ValueError from a bare
``float(request.form.get(...))`` straight into the 500 page; they now flash a
message naming the field. The members page used to mark an inviter's full
name ``|safe``, so a crafted name was stored XSS against every admin.
"""
import os
import tempfile

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), "erp_input_hardening.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
os.environ["DATABASE_URL"] = "sqlite:///" + _TMP_DB.replace("\\", "/")

from app import app as flask_app  # noqa: E402
from shared.extensions import db  # noqa: E402


@pytest.fixture(scope="module")
def client():
    c = flask_app.test_client()
    c.get("/")  # lazy create_all + migrate + seed
    from hr_app.models.user import User
    with flask_app.app_context():
        user = (User.query.filter(User.email.ilike("admin%")).first()
                or User.query.first())
        uid = user.id
    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
    yield c


def _company_id():
    from shared.models.company import Company
    from shared.tenancy import unscoped
    with flask_app.app_context():
        with unscoped():
            return Company.query.order_by(Company.id).first().id


def _category_id():
    from fixed_assets_app.models.asset import AssetCategory
    from shared.tenancy import set_current_company
    with flask_app.app_context():
        set_current_company(_company_id())
        cat = AssetCategory.query.first()
        assert cat is not None, "seed produced no asset categories"
        return cat.id


@pytest.mark.parametrize("field,value,message", [
    ("purchase_cost", "twelve", b"Purchase cost must be a number"),
    ("purchase_date", "", b"Purchase date is required"),
])
def test_asset_form_flashes_bad_input_instead_of_500(client, field, value, message):
    data = {"name": "Hardening Laptop", "category_id": str(_category_id()),
            "purchase_date": "2026-01-10", "purchase_cost": "1000",
            "useful_life": "3", "salvage_value": "",
            "depreciation_method": "straight_line"}
    data[field] = value
    resp = client.post("/fixed-assets/assets/create", data=data,
                       headers={"Referer": "/fixed-assets/assets/create"},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert message in resp.data


def test_blank_salvage_value_is_zero_not_a_crash(client):
    from fixed_assets_app.models.asset import FixedAsset
    from shared.tenancy import set_current_company
    resp = client.post("/fixed-assets/assets/create", data={
        "name": "Blank Salvage Desk", "category_id": str(_category_id()),
        "purchase_date": "2026-01-10", "purchase_cost": "500",
        "useful_life": "", "salvage_value": "",
        "depreciation_method": "straight_line"}, follow_redirects=True)
    assert resp.status_code == 200
    with flask_app.app_context():
        set_current_company(_company_id())
        asset = FixedAsset.query.filter_by(name="Blank Salvage Desk").first()
        assert asset is not None
        assert float(asset.salvage_value) == 0


def test_inviter_name_is_escaped_on_members_page(client):
    from hr_app.models.user import User
    from shared.models.base import Role
    from shared.models.company import CompanyInvitation
    with flask_app.app_context():
        admin = (User.query.filter(User.email.ilike("admin%")).first()
                 or User.query.first())
        admin.full_name = "<img src=x onerror=alert(1)>"
        role = Role.query.filter_by(name=Role.EMPLOYEE).first()
        db.session.add(CompanyInvitation(
            company_id=_company_id(), email="xss-probe@example.com",
            role_id=role.id, invited_by=admin.id,
            status=CompanyInvitation.SENT))
        db.session.commit()
    resp = client.get("/settings/members/")
    assert resp.status_code == 200
    assert b"xss-probe@example.com" in resp.data
    assert b"<img src=x onerror=alert(1)>" not in resp.data
    assert b"&lt;img src=x onerror=alert(1)&gt;" in resp.data


def test_confirm_dialog_names_cannot_break_out_into_script(client):
    """``onsubmit="return confirm('Delete unit {{ u.name }}?')"`` — the
    attribute decodes Jinja's &#39; back to a quote before JavaScript runs,
    so a name with a quote in it executed. Names now go in as JSON."""
    from inventory_app.models.unit import InvUnit
    from shared.tenancy import set_current_company
    evil = "x');alert(document.cookie);//"
    with flask_app.app_context():
        set_current_company(_company_id())
        db.session.add(InvUnit(name=evil, abbreviation="xq"))
        db.session.commit()
    resp = client.get("/inventory/units/")
    assert resp.status_code == 200
    assert b"confirm('Delete unit x&#39;);alert" not in resp.data
    # The quote arrives as a \u0027 escape inside a JSON string: inert.
    assert (rb"confirm('Delete unit ' + &#34;x\u0027);alert(document.cookie);"
            b"//&#34; + '?')") in resp.data
