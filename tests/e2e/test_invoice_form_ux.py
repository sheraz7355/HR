"""E2E for the document UI layer on the invoice forms (static/js/doc_form.js,
static/css/doc_form.css).

- One header: the document number is the title, one status chip; payment
  status only once approved.
- States: new → draft (saved, still editable; Save lights only when there is
  something to save) → approved (locked, Print is the primary action, rare
  actions in "More", row buttons hidden, lock notice) → unapproved again.
- Payment terms fill the due date.
- On a phone the lines are labelled cards and the action bar is pinned to
  the bottom, with no horizontal scroll.
- The purchase invoice gets the same bar plus the shortcuts and the
  unsaved-changes guard it never had.
"""
import os

from tests.e2e.test_invoice_form_flow import _open_new, _seed_line

BASE_URL = "http://127.0.0.1:" + os.environ.get("E2E_PORT", "5050")
NEW_PURCHASE = f"{BASE_URL}/inventory/purchase-invoice/"
SKU = "CBL-SOL-4MM"


def _save_draft(page):
    page.keyboard.press("Control+s")
    page.wait_for_function("() => document.getElementById('invoiceId').value !== ''")
    page.wait_for_function("() => window.formDirty === false")


def _approve(page):
    page.locator("#saveApproveBtn").click()
    page.locator("#confirmOkBtn").click()
    page.wait_for_selector(".ap-b")
    page.wait_for_load_state("networkidle")


class TestHeader:
    def test_new_invoice_reads_as_a_new_draft(self, admin_page):
        _open_new(admin_page)
        assert admin_page.locator("#docTitle").inner_text() == "New sales invoice"
        assert admin_page.locator("#statusBadge").inner_text() == "Draft"
        assert admin_page.locator("#paymentBadge").is_hidden()
        # The topbar no longer repeats the status in the page name.
        assert "Unapproved" not in admin_page.locator(".topbar").inner_text()
        # New state: cancel, save draft, save & approve — nothing else.
        labels = [t.strip() for t in admin_page.locator(".ab > .btn").all_inner_texts()]
        assert labels == ["Cancel", "Save draft", "Save & approve"]


class TestDraftStaysEditable:
    def test_saving_a_draft_keeps_the_form_open_for_editing(self, admin_page):
        _open_new(admin_page)
        _seed_line(admin_page)
        _save_draft(admin_page)
        inv_id = admin_page.evaluate("document.getElementById('invoiceId').value")
        # The URL now names the document, so a refresh reopens it.
        assert admin_page.url.endswith(f"/inventory/invoices/{inv_id}")
        assert admin_page.locator("#docTitle").inner_text().startswith("SI-")
        assert admin_page.locator("#statusBadge").inner_text() == "Draft"
        # Fields stay editable and Save is off until something changes.
        assert admin_page.locator("#customerSearch").is_enabled()
        assert admin_page.locator('#itemsBody [data-col="quantity"]').first.is_enabled()
        assert admin_page.locator("#saveBtn").is_disabled()
        admin_page.locator('#itemsBody [data-col="quantity"]').first.fill("3")
        assert admin_page.locator("#saveBtn").is_enabled()
        _save_draft(admin_page)
        assert admin_page.locator("#saveBtn").is_disabled()
        # Still the same document, not a second one.
        assert admin_page.evaluate("document.getElementById('invoiceId').value") == inv_id

    def test_reopened_draft_offers_print_and_delete(self, admin_page):
        _open_new(admin_page)
        _seed_line(admin_page)
        _save_draft(admin_page)
        admin_page.reload()
        admin_page.wait_for_load_state("networkidle")
        assert admin_page.locator("#printBtn").is_visible()
        admin_page.locator(".ab-more-btn").click()
        assert admin_page.locator("#deleteBtn").is_visible()
        admin_page.locator("#deleteBtn").click()
        assert admin_page.locator("#confirmTitle").inner_text() == "Delete draft"
        admin_page.keyboard.press("Escape")
        assert admin_page.locator("#confirmModal.show").count() == 0


class TestPaymentTerms:
    def test_terms_fill_the_due_date(self, admin_page):
        _open_new(admin_page)
        admin_page.locator("#invDate").fill("2026-10-01")
        admin_page.locator("#payTerms").select_option("30")
        assert admin_page.locator("#dueDate").input_value() == "2026-10-31"
        # Moving the invoice date keeps the terms.
        admin_page.locator("#invDate").fill("2026-11-15")
        admin_page.locator("#invDate").dispatch_event("change")
        assert admin_page.locator("#dueDate").input_value() == "2026-12-15"
        # A hand-picked due date means custom terms.
        admin_page.locator("#dueDate").fill("2026-12-20")
        admin_page.locator("#dueDate").dispatch_event("change")
        assert admin_page.locator("#payTerms").input_value() == ""


class TestApprovedDocument:
    def test_approved_invoice_is_locked_and_reads_as_a_document(self, admin_page):
        _open_new(admin_page)
        _seed_line(admin_page)
        _approve(admin_page)
        assert admin_page.locator("#statusBadge").inner_text() == "Approved"
        assert admin_page.locator("#paymentBadge").is_visible()
        assert "Approved and locked" in admin_page.locator(".ap-b").inner_text()
        # One primary: Print.
        assert "btn-s" in (admin_page.locator("#printBtn").get_attribute("class") or "")
        assert admin_page.locator("#saveBtn").count() == 0
        # Row add/remove buttons are not offered on a locked document.
        assert admin_page.locator("#itemsBody .ra").first.is_hidden()
        assert admin_page.locator("#customerSearch").is_disabled()
        # Corrective actions are one step away, in More.
        admin_page.locator(".ab-more-btn").click()
        assert admin_page.locator("#unapproveBtn").is_visible()
        assert admin_page.locator("#validateFbrBtn").is_visible()

    def test_unapprove_reopens_the_invoice_for_editing(self, admin_page):
        _open_new(admin_page)
        _seed_line(admin_page)
        _approve(admin_page)
        admin_page.locator(".ab-more-btn").click()
        admin_page.locator("#unapproveBtn").click()
        admin_page.locator("#confirmOkBtn").click()
        admin_page.wait_for_function(
            "() => document.getElementById('statusBadge').textContent.trim() === 'Draft'")
        admin_page.wait_for_load_state("networkidle")
        assert admin_page.locator(".ap-b").count() == 0
        assert admin_page.locator("#customerSearch").is_enabled()
        # Ctrl+S works again (it used to answer "approved invoices are locked").
        admin_page.locator('#itemsBody [data-col="quantity"]').first.fill("4")
        _save_draft(admin_page)
        assert admin_page.locator(".toast-s").count() >= 1


class TestPhone:
    def test_lines_are_cards_and_the_bar_is_pinned(self, admin_mobile):
        page = admin_mobile
        _open_new(page)
        # No sideways scroll anywhere on the page.
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 1")
        # Quantity and rate are visible on the card, each with its label.
        qty = page.locator('#itemsBody [data-col="quantity"]').first
        assert qty.is_visible()
        label = page.evaluate(
            "getComputedStyle(document.querySelector('#itemsBody [data-col=quantity]')"
            ".closest('td'), '::before').content")
        assert "Quantity" in label
        # Primary action within thumb reach: the bar is fixed to the bottom.
        bar = page.evaluate(
            "(() => { const b = document.querySelector('#pageActions .ab');"
            " const r = b.getBoundingClientRect();"
            " return [getComputedStyle(b).position, Math.round(r.bottom), innerHeight]; })()")
        assert bar[0] == "fixed" and abs(bar[1] - bar[2]) <= 1
        assert page.locator("#saveApproveBtn").is_visible()


class TestPurchaseInvoice:
    def _open(self, page):
        page.goto(NEW_PURCHASE)
        page.wait_for_load_state("networkidle")
        gate = page.locator("#gateContinue")
        if gate.count() and gate.is_visible():
            gate.click()
            page.wait_for_timeout(250)

    def _seed(self, page):
        page.locator("#supplierSearch").fill("a")
        page.locator("#supplierDropdown .ac-it").first.click()
        page.wait_for_timeout(120)
        page.locator('#itemsBody [data-col="code"]').first.fill(SKU)
        page.wait_for_function(
            "document.querySelector('#itemsBody tr').dataset.productId !== ''")
        page.locator('#itemsBody [data-col="quantity"]').first.fill("2")
        page.locator('#itemsBody [data-col="unit_price"]').first.fill("100")

    def test_purchase_gets_the_same_bar_and_shortcuts(self, admin_page):
        self._open(admin_page)
        assert admin_page.locator("#docTitle").inner_text() == "New purchase invoice"
        self._seed(admin_page)
        # Ctrl+S is new on this form.
        _save_draft(admin_page)
        assert admin_page.locator("#docTitle").inner_text().startswith("PI-")
        assert admin_page.locator("#supplierSearch").is_enabled()
        assert admin_page.locator("#saveBtn").is_disabled()

    def test_purchase_warns_before_discarding_edits(self, admin_page):
        self._open(admin_page)
        admin_page.locator("#invoiceNotes").fill("half-typed bill")
        admin_page.keyboard.press("Alt+c")
        assert admin_page.locator("#confirmModal.show").count() == 1
        assert "Discard" in admin_page.locator("#confirmTitle").inner_text()
        admin_page.locator("#confirmOkBtn").click()
        admin_page.wait_for_url("**/purchase-invoice/list**")
