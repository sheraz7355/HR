"""Settings fixes: duplicated visibility toggles, the Company Profile tab
blanking the shell's company name, and Report Structure reordering."""
import os
import re

BASE_URL = "http://127.0.0.1:" + os.environ.get("E2E_PORT", "5050")


def test_visibility_toggles_render_once_and_can_be_turned_off(admin_page):
    page = admin_page
    page.goto(f"{BASE_URL}/settings/?tab=invoicing")
    page.wait_for_load_state("networkidle")
    # One control per setting: the duplicate card posted a second, still
    # checked copy, so a switch turned off stayed on.
    assert page.locator('input[name="require_approval"]').count() == 1
    toggle = page.locator('input[name="allow_partial_payment"]')
    if toggle.is_checked():
        toggle.locator("xpath=..").click()
    page.locator("button:has-text('Save Invoice Settings')").click()
    page.wait_for_load_state("networkidle")
    page.goto(f"{BASE_URL}/settings/?tab=invoicing")
    assert not page.locator('input[name="allow_partial_payment"]').is_checked()
    # Put it back for other tests.
    page.locator('input[name="allow_partial_payment"]').locator("xpath=..").click()
    page.locator("button:has-text('Save Invoice Settings')").click()
    page.wait_for_load_state("networkidle")


def test_company_profile_tab_keeps_the_company_name_in_the_header(admin_page):
    page = admin_page
    page.goto(f"{BASE_URL}/settings/?tab=company")
    name = page.locator(".company-switch-name").inner_text().strip()
    assert name and name != "No company"


def test_report_structure_rows_move_and_save(admin_page):
    page = admin_page
    page.goto(f"{BASE_URL}/settings/?tab=reports")
    labels = lambda: page.locator('#rsTable input[name^="row_label_"]').evaluate_all("els => els.map(e => e.value)")
    before = labels()
    assert page.locator("#rsTable .rs-up").first.is_disabled()
    page.locator("#rsTable tr.rs-row").nth(1).locator(".rs-up").click()
    moved = labels()
    assert moved[0] == before[1] and moved[1] == before[0]
    page.locator("button:has-text('Save report structure')").click()
    page.wait_for_load_state("networkidle")
    assert labels()[:2] == moved[:2]
    # Back to standard.
    page.once("dialog", lambda d: d.accept())
    page.locator("button:has-text('Reset to standard')").click()
    page.wait_for_load_state("networkidle")
    assert labels()[:2] == before[:2]


def test_fiscal_rule_states_the_real_year_end(admin_page):
    """The rule used to print '1 January -> 0 December' (start day minus one)."""
    page = admin_page
    page.goto(f"{BASE_URL}/settings/?tab=periods")
    text = page.locator(".set-card").first.inner_text()
    assert " 0 December" not in text and "00 December" not in text
    assert re.search(r"Each financial year runs \d{1,2} \w+ → \d{1,2} \w+", text), text


def test_company_audit_log_leaves_out_super_admin_console_visits(admin_page):
    page = admin_page
    # Enter the console: a platform event recorded with no company.
    page.goto(f"{BASE_URL}/superadmin/login")
    if page.locator("#login").count():
        page.fill("#login", "admin@gmail.com")
        page.fill("#password", "admin123")
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle")
    page.goto(f"{BASE_URL}/settings/?tab=audit&action=login")
    assert "entered the console" not in page.content()
