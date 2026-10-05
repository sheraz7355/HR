"""Accounting voucher form v3 and the sidebar accordion.

Voucher: a saved draft opens ready to edit (no "Edit" step); the summary rail
shows a live entry preview (Dr lines, then the Cr cash/bank line) that
balances; approving asks in-page, not with the browser's confirm.

Sidebar: one group open at a time; on load only the active page's group is
open; nothing re-opens from old per-group localStorage state.
"""
import os

BASE_URL = "http://127.0.0.1:" + os.environ.get("E2E_PORT", "5050")


def _pick(page, selector, text=None):
    page.locator(selector).focus()
    if text:
        page.keyboard.type(text)
    else:
        page.keyboard.press(" ")
    page.wait_for_timeout(600)
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    page.wait_for_timeout(250)


def _fill_cpv(page, amount="1500"):
    page.goto(f"{BASE_URL}/accounting/vouchers?type=CPV")
    page.wait_for_load_state("networkidle")
    _pick(page, "#cbSearch")
    _pick(page, ".acct-input", "expense")
    page.locator(".amt-input").first.fill(amount)


def test_entry_preview_follows_the_lines(admin_page):
    page = admin_page
    _fill_cpv(page)
    page.wait_for_selector("#jePreview .vpre-row")
    rows = page.locator("#jePreview .vpre-row")
    assert rows.count() == 2
    assert page.locator("#jePreview .vpre-row.dr").count() == 1
    assert page.locator("#jePreview .vpre-row.cr").count() == 1
    assert "Balanced" in page.locator("#jePreview").inner_text()
    # Cash balance before → after this voucher.
    page.wait_for_function("document.querySelector('#cbBalance') && /after this voucher/.test(document.querySelector('#cbBalance').textContent)")


def test_approve_asks_in_page_and_draft_opens_editable(admin_page):
    page = admin_page
    _fill_cpv(page, "700")
    page.locator("#saveBtn").click()
    page.wait_for_load_state("networkidle")
    # Saved draft: fields are editable straight away, no Edit step.
    assert page.locator("#cbSearch").is_enabled()
    assert page.locator(".amt-input").first.is_enabled()
    assert page.locator("a[href*='edit=1']").count() == 0
    page.locator("#approveBtn").click()
    assert page.locator("#vConfirm").is_visible()
    assert "general ledger" in page.locator("#vConfirmMsg").inner_text()
    page.locator("#vConfirmOk").click()
    page.wait_for_selector(".vlock")
    assert "Approved" in page.locator(".vchip").inner_text()
    page.locator(".vmore-btn").click()
    assert page.locator("button:has-text('Unapprove')").is_visible()


def test_sidebar_is_an_accordion(admin_page):
    page = admin_page
    page.evaluate("localStorage.setItem('sidebar_group_procurement','expanded');"
                  "localStorage.setItem('sidebar_group_sales','expanded')")
    page.goto(f"{BASE_URL}/inventory/customers/")
    page.wait_for_load_state("networkidle")
    groups = page.locator(".sidebar .nav-group")
    if groups.count() < 2:
        page.goto(f"{BASE_URL}/inventory/invoices/list")
        page.wait_for_load_state("networkidle")
        groups = page.locator(".sidebar .nav-group")
    assert groups.count() >= 2
    # Old stored states do not open anything: at most the active group is open.
    assert page.locator(".sidebar .nav-group.expanded").count() <= 1
    first, second = groups.nth(0), groups.nth(1)
    first.locator(".nav-group-header").click()
    if "expanded" not in (first.get_attribute("class") or ""):
        first.locator(".nav-group-header").click()
    second.locator(".nav-group-header").click()
    assert "expanded" in (second.get_attribute("class") or "")
    assert "expanded" not in (first.get_attribute("class") or "")
    assert page.locator(".sidebar .nav-group.expanded").count() == 1
    assert page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('sidebar_group_')).length") == 0
