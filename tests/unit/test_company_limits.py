"""Quota overrides: 0 is a real value, NULL means "use the default".

company_limit_for / member_limit_for used truthiness (``or``), so a
super-admin setting of 0 ("may create none" / "no members") silently fell
back to the global default and the limit could never forbid.
"""
import sys
import types
from pathlib import Path

ACCOUNTIX_ERP = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ACCOUNTIX_ERP))

from shared.models.company import Company, GlobalLimits  # noqa: E402
import shared.models.base  # noqa: E402,F401  (User: relationship target)


def _user(**kw):
    return types.SimpleNamespace(**kw)


def _limits():
    lim = GlobalLimits()
    lim.max_companies_per_user = 3
    lim.default_max_members = 25
    return lim


def test_company_limit_zero_forbids():
    assert _limits().company_limit_for(_user(max_companies_owned=0)) == 0


def test_company_limit_none_uses_default():
    assert _limits().company_limit_for(_user(max_companies_owned=None)) == 3


def test_company_limit_missing_attr_uses_default():
    # Rows predating the migration have no override attribute at all.
    assert _limits().company_limit_for(_user()) == 3


def test_company_limit_positive_passes_through():
    assert _limits().company_limit_for(_user(max_companies_owned=5)) == 5


def test_member_limit_zero_forbids():
    company = Company()
    company.max_members = 0
    assert _limits().member_limit_for(company) == 0


def test_member_limit_none_uses_default():
    company = Company()
    company.max_members = None
    assert _limits().member_limit_for(company) == 25


def test_join_limit_zero_still_forbids():
    assert _limits().join_limit_for(_user(max_companies_joined=0)) == 0
    assert _limits().join_limit_for(_user(max_companies_joined=None)) is None
