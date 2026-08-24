"""E2E for the keyboard-first sales-invoice form flow.

Four behaviours land together in invoicing_app/templates/invoices/form_inv.html:

1. Header order — the critical entry path is contiguous:
   Customer → Document Dates → Logistics (collapsed by default).
2. Enter = next field. The header cards are one lane (customer → dates →
   label → logistics → grid) and the grid walks cell-by-cell, spawning a
   fresh row off the last cell of the last row. Shift+Enter walks back.
3. Shortcuts — Ctrl+S save · Ctrl+Shift+S save & approve · Ctrl+P print
   (saved, clean documents only) · Alt+N new · Alt+C list · Esc peels one
   overlay layer per press. Ctrl+N/Ctrl+C stay with the browser.
4. Dirty guard — leaving via Cancel/New (click or Alt key) with unsaved
   edits asks first; printing mid-edit is refused until saved.
"""

import os

BASE_URL = "http://localhost:" + os.environ.get("E2E_PORT", "5050")
NEW_INVOICE = f"{BASE_URL}/inventory/invoices/"
LIST_INVOICES = f"{BASE_URL}/inventory/invoices/list"
SKU = "CBL-SOL-4MM"  # seeded demo product (app.py inventory seed)


def _open_new(page):
    page.goto(NEW_INVOICE)
    page.wait_for_load_state("networkidle")
    # Blank source: the gate's radio defaults to it, Continue commits it.
    page.locator("#gateContinue").click()
    page.wait_for_timeout(250)
    return page


def _seed_line(page):
    """A minimal billable document through the real UI: pick the first
    seeded customer off the autocomplete, type the SKU into the Code cell
    (the exact-match filler pulls name/price/stock), give it quantity."""
    page.locator("#customerSearch").fill("Solar")
    page.locator("#customerDropdown .ac-it").first.click()
    page.wait_for_timeout(120)
    code = page.locator('#itemsBody [data-col="code"]').first
    code.fill(SKU)
    # The exact-SKU link may resolve via a server lookup (the preloaded cache
    # holds only the first 20 products); wait until the row carries a product.
    page.wait_for_function(
        "document.querySelector('#itemsBody tr').dataset.productId !== ''")
    page.locator('#itemsBody [data-col="quantity"]').first.fill("2")
    page.locator('#itemsBody [data-col="unit_price"]').first.fill("180")


class TestHeaderOrder:
    def test_cards_run_party_dates_logistics(self, admin_page):
        _open_new(admin_page)
        titles = admin_page.eval_on_selector_all(
            ".hdr-strip > .icard .icard-h span:nth-child(2)",
            "els => els.map(e => e.textContent.trim())")
        assert titles == ["Customer Details", "Document Dates",
                          "Logistics & Delivery"]

    def test_logistics_starts_collapsed_but_visible(self, admin_page):
        _open_new(admin_page)
        card = admin_page.locator("#logisticsCard")
        assert card.is_visible()
        assert "collapsed" in (card.get_attribute("class") or "")
        assert admin_page.locator("#refSO").is_hidden()

    def test_logistics_expands_from_header_and_respects_settings_toggle(self, admin_page):
        _open_new(admin_page)
        admin_page.locator("#logisticsToggle").click()
        assert admin_page.locator("#refSO").is_visible()
        admin_page.locator(".bsm-settings").click()
        # The toggle lives in panel section 4 ("Columns & fields"), which ships
        # collapsed — the panel keeps exactly one section open at a time.
        chk = admin_page.locator("#settingsShowTransport")
        admin_page.locator(".accordion", has=chk).locator(".acc-h").click()
        # The raw checkbox is opacity:0/zero-size by design (a styled .tgl-s
        # span is the visible switch), so the user — and the test — clicks
        # the span, not the input.
        switch = admin_page.locator("#settingsShowTransport + .tgl-s")
        switch.click()
        assert not chk.is_checked()
        assert admin_page.locator("#logisticsCard").is_hidden()
        switch.click()
        assert chk.is_checked()
        assert admin_page.locator("#logisticsCard").is_visible()
        assert admin_page.locator("#refSO").is_visible()

    def test_logistics_reopens_when_a_saved_document_carries_data(self, admin_page):
        """refSO is the one logistics datum that survives a save (it mirrors
        the linked sales order). A reload showing it must present the card
        expanded, not folded."""
        _open_new(admin_page)
        assert "collapsed" in (admin_page.locator(
            "#logisticsCard").get_attribute("class") or "")
        admin_page.evaluate("""() => {
          document.getElementById('refSO').value = 'SO-2026-0042';
          window.__logisticsAutoExpand();
        }""")
        assert "collapsed" not in (admin_page.locator(
            "#logisticsCard").get_attribute("class") or "")
        assert admin_page.locator("#refSO").is_visible()


class TestEnterNavigation:
    def test_enter_walks_the_header_lane_into_the_grid(self, admin_page):
        _open_new(admin_page)
        admin_page.locator("#customerSearch").focus()
        admin_page.keyboard.press("Escape")  # make sure no dropdown is open
        admin_page.keyboard.press("Enter")
        assert admin_page.evaluate(
            "document.activeElement.id") == "invDate"
        admin_page.keyboard.press("Enter")
        assert admin_page.evaluate(
            "document.activeElement.id") == "dueDate"
        admin_page.keyboard.press("Enter")
        # The party-label picker opens on focus; Escape skips past it.
        assert admin_page.evaluate(
            "document.activeElement.id") == "invLabelSearch"
        admin_page.keyboard.press("Escape")
        admin_page.keyboard.press("Enter")
        assert admin_page.evaluate(
            "document.activeElement.className.includes('ac-code')")

    def test_enter_walks_grid_cells_and_spawns_the_next_row(self, admin_page):
        _open_new(admin_page)
        admin_page.locator('#itemsBody [data-col="code"]').first.focus()
        for col in ("description", "quantity", "unit_price"):
            admin_page.keyboard.press("Enter")
            assert admin_page.evaluate(
                f"document.activeElement.dataset.col === '{col}'"), col
        # Last cell of the last row: a new line is the continuation.
        admin_page.keyboard.press("Enter")
        assert admin_page.evaluate(
            "document.querySelectorAll('#itemsBody tr').length") == 2
        assert admin_page.evaluate(
            "document.activeElement.className.includes('ac-code')")

    def test_shift_enter_walks_back(self, admin_page):
        _open_new(admin_page)
        admin_page.locator('#itemsBody [data-col="unit_price"]').first.focus()
        admin_page.keyboard.press("Shift+Enter")
        assert admin_page.evaluate(
            "document.activeElement.dataset.col === 'quantity'")


class TestShortcuts:
    def test_ctrl_s_saves_the_draft(self, admin_page):
        _open_new(admin_page)
        _seed_line(admin_page)
        admin_page.keyboard.press("Control+s")
        admin_page.wait_for_function(
            "() => document.getElementById('invoiceId').value !== ''")
        assert admin_page.locator(".toast-s").count() >= 1
        assert admin_page.locator("#saveBtn").is_disabled()

    def test_ctrl_p_is_refused_until_saved_then_prints(self, admin_page):
        _open_new(admin_page)
        _seed_line(admin_page)
        # The trailing `;0` matters: page.evaluate() INVOKES an expression that
        # evaluates to a function, so ending on the assignment would call the
        # stub on install and bank a phantom print.
        admin_page.evaluate(
            "window.__printed=0;window.print=function(){window.__printed++};0")
        assert admin_page.evaluate("window.__printed") == 0
        dirty_at_press = admin_page.evaluate("window.formDirty")
        assert dirty_at_press, "seeded edits must mark the form dirty"
        admin_page.keyboard.press("Control+p")
        admin_page.wait_for_timeout(200)
        assert admin_page.evaluate("window.__printed") == 0
        assert admin_page.evaluate(
            "document.querySelector('.toast')?.textContent || ''"
            ).find("Save") != -1
        admin_page.keyboard.press("Control+s")
        admin_page.wait_for_function(
            "() => document.getElementById('invoiceId').value !== ''")
        admin_page.wait_for_function("() => window.formDirty === false")
        admin_page.keyboard.press("Control+p")
        admin_page.wait_for_timeout(300)
        assert admin_page.evaluate("window.__printed") == 1

    def test_ctrl_shift_s_runs_save_and_approve(self, admin_page):
        _open_new(admin_page)
        _seed_line(admin_page)
        admin_page.keyboard.press("Control+Shift+s")
        assert admin_page.locator("#confirmModal.show").count() == 1
        assert admin_page.locator("#confirmTitle").inner_text() == "Save & Approve"
        admin_page.locator("#confirmOkBtn").click()
        admin_page.wait_for_selector(".ap-b")
        assert admin_page.locator("#statusBadge").inner_text().lower() == "approved"

    def test_alt_n_starts_a_fresh_invoice_after_a_save(self, admin_page):
        _open_new(admin_page)
        _seed_line(admin_page)
        admin_page.keyboard.press("Control+s")
        admin_page.wait_for_function(
            "() => document.getElementById('invoiceId').value !== ''")
        admin_page.keyboard.press("Alt+n")
        admin_page.wait_for_function(
            "() => location.pathname === '/inventory/invoices/'")
        admin_page.wait_for_load_state("networkidle")
        assert admin_page.evaluate(
            "document.getElementById('invoiceId').value") == ""

    def test_esc_peels_one_overlay_layer_at_a_time(self, admin_page):
        _open_new(admin_page)
        admin_page.locator(".bsm-settings").click()
        assert admin_page.locator("#sidePanel.open").count() == 1
        admin_page.keyboard.press("Escape")
        assert admin_page.locator("#sidePanel.open").count() == 0
        admin_page.locator("#chargesBtn").click()
        assert admin_page.locator("#chargesModal.show").count() == 1
        admin_page.keyboard.press("Escape")
        assert admin_page.locator("#chargesModal.show").count() == 0


class TestDirtyGuard:
    def test_alt_c_asks_before_discarding_then_leaves(self, admin_page):
        _open_new(admin_page)
        admin_page.locator("#invoiceNotes").fill("half-written order")
        admin_page.keyboard.press("Alt+c")
        assert admin_page.locator("#confirmModal.show").count() == 1
        admin_page.locator("#confirmOkBtn").click()
        admin_page.wait_for_url(LIST_INVOICES)

    def test_cancel_click_with_clean_form_leaves_without_asking(self, admin_page):
        _open_new(admin_page)
        admin_page.locator("#cancelBtn").click()
        admin_page.wait_for_url(LIST_INVOICES)
        assert admin_page.locator("#confirmModal.show").count() == 0


class TestMobileResponsive:
    def test_new_form_fits_a_375px_screen_without_horizontal_scroll(self, admin_mobile):
        _open_new(admin_mobile)
        overflow = admin_mobile.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 1
