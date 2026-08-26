"""E2E for the invoice source gate (§4.1, Figure 2).

A new invoice must decide where its lines come from *before* the form is worked
in — not by pressing a button on an already-blank invoice, and not by a control
sitting inside the form. The gate is the first thing the screen presents: two
radio cards (blank / from orders) and one committing action, "Continue". ×,
Cancel, Escape or the backdrop all mean "start blank" — the empty form is
already the state of a fresh page.
"""

import os

# Same port the harness starts the server on (tests/e2e/conftest.py).
BASE_URL = "http://127.0.0.1:" + os.environ.get("E2E_PORT", "5050")
NEW_INVOICE = f"{BASE_URL}/inventory/invoices/"
NEW_PURCHASE = f"{BASE_URL}/inventory/purchase-invoice/"


def _open_new(page, url=NEW_INVOICE):
    page.goto(url)
    page.wait_for_load_state("networkidle")
    return page


def _choose(page, card):
    """Select one of the radio cards and commit the gate with Continue."""
    page.locator(card).click()
    page.locator("#gateContinue").click()
    page.wait_for_timeout(250)


class TestSourceGate:
    def test_a_new_invoice_opens_on_the_gate(self, admin_page):
        _open_new(admin_page)
        assert admin_page.locator("#sourceGate.show").count() == 1
        assert admin_page.locator("#gateBlank").is_visible()
        assert admin_page.locator("#gateOrders").is_visible()

    def test_the_gate_covers_the_form_until_it_is_answered(self, admin_page):
        """It is a decision, not a suggestion: the form behind it must not be
        reachable while the question is open."""
        _open_new(admin_page)
        # A click aimed at the grid lands on the gate, not on the row beneath.
        blocked = admin_page.evaluate("""() => {
          const cell = document.querySelector('#itemsBody [data-col="quantity"]');
          if (!cell) return 'no cell';
          const r = cell.getBoundingClientRect();
          const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return hit && hit.closest('#sourceGate') ? 'gate' : 'form';
        }""")
        assert blocked == "gate"

    def test_choosing_blank_dismisses_the_gate_and_frees_the_form(self, admin_page):
        _open_new(admin_page)
        _choose(admin_page, "#gateBlank")
        assert admin_page.locator("#sourceGate.show").count() == 0
        qty = admin_page.locator('#itemsBody [data-col="quantity"]').first
        qty.fill("3")
        assert qty.input_value() == "3"

    def test_choosing_blank_leaves_no_order_link(self, admin_page):
        """A blank invoice must carry no order reference — the Order ref column
        stays hidden and nothing is written back to an order on approve."""
        _open_new(admin_page)
        _choose(admin_page, "#gateBlank")
        assert admin_page.evaluate("() => loadedOrderIds.length") == 0

    def test_choosing_orders_opens_the_picker(self, admin_page):
        _open_new(admin_page)
        _choose(admin_page, "#gateOrders")
        assert admin_page.locator("#sourceGate.show").count() == 0
        assert admin_page.locator("#orderModal.show").count() == 1

    def test_the_picker_names_the_missing_customer_rather_than_claiming_no_orders(self, admin_page):
        """Reached with no customer chosen, the list must not read "No approved
        orders for this customer" — there is no customer to have any."""
        _open_new(admin_page)
        _choose(admin_page, "#gateOrders")
        text = admin_page.locator("#ordersList").inner_text().lower()
        assert "select a customer" in text

    def test_the_gate_is_not_shown_on_a_saved_invoice(self, admin_page):
        """Reopening has already answered the question — the answer is whether
        the lines carry an order link."""
        admin_page.goto(f"{BASE_URL}/inventory/invoices/list")
        admin_page.wait_for_load_state("networkidle")
        first = admin_page.locator("table tbody tr a").first
        if first.count() == 0:
            return  # no saved invoices in this database
        first.click()
        admin_page.wait_for_load_state("networkidle")
        assert admin_page.locator("#sourceGate").count() == 0

    def test_the_close_button_and_escape_mean_blank(self, admin_page):
        """The × and Escape both step out of the way onto the empty form —
        a blank invoice is already the state of a fresh page."""
        _open_new(admin_page)
        admin_page.locator("#gateClose").click()
        admin_page.wait_for_timeout(200)
        assert admin_page.locator("#sourceGate.show").count() == 0
        _open_new(admin_page)
        admin_page.keyboard.press("Escape")
        admin_page.wait_for_timeout(200)
        assert admin_page.locator("#sourceGate.show").count() == 0
        assert admin_page.evaluate("() => loadedOrderIds.length") == 0

    def test_the_gate_lists_its_source_options_clearly(self, admin_page):
        """The dialog names the decision and both paths, with a hint that the
        import button stays available in the toolbar."""
        _open_new(admin_page)
        # The eyebrow renders uppercased by CSS (text-transform).
        assert admin_page.locator(".gate-eyebrow").inner_text().lower() == \
            "new sales invoice"
        assert admin_page.locator("#gateTitle").inner_text() == \
            "How do you want to start?"
        assert admin_page.locator("#gateBlank .gate-n").inner_text() == \
            "Blank invoice"
        assert admin_page.locator("#gateOrders .gate-n").inner_text() == \
            "Load from sales orders"
        assert "From Orders" in admin_page.locator(".gate-hint").inner_text()

    def test_the_purchase_invoice_opens_on_the_same_gate(self, admin_page):
        _open_new(admin_page, NEW_PURCHASE)
        assert admin_page.locator("#sourceGate.show").count() == 1
        assert admin_page.locator(".gate-eyebrow").inner_text().lower() == \
            "new purchase invoice"
        assert admin_page.locator("#gateBlank").is_visible()
        assert admin_page.locator("#gateOrders").is_visible()

    def test_purchase_blank_frees_the_form(self, admin_page):
        _open_new(admin_page, NEW_PURCHASE)
        _choose(admin_page, "#gateBlank")
        assert admin_page.locator("#sourceGate.show").count() == 0
        assert admin_page.locator("#supplierSearch").is_visible()

    def test_purchase_orders_hands_off_to_the_toolbar_flow(self, admin_page):
        """With no supplier chosen the import modal must not open — the same
        guard the toolbar button uses, reached through the gate."""
        _open_new(admin_page, NEW_PURCHASE)
        _choose(admin_page, "#gateOrders")
        assert admin_page.locator("#sourceGate.show").count() == 0
        assert admin_page.locator("#orderModal.show").count() == 0

    def test_direct_sales_flow_skips_the_gate(self, admin_page):
        """Settings > Sales flow = Direct Invoice: a new invoice opens straight
        on the form — no sourcing question, because there is no order chain to
        source from. The purchase flow (with_po) keeps its gate, and the
        setting is restored afterwards for the other tests."""
        admin_page.goto(f"{BASE_URL}/settings/?tab=inventory")
        admin_page.wait_for_load_state("networkidle")
        try:
            sales_direct = admin_page.locator(
                'input[name="sales_flow"][value="direct_invoice"]')
            sales_direct.check(force=True)
            admin_page.get_by_role("button",
                                   name="Save Inventory Settings").click()
            admin_page.wait_for_load_state("networkidle")
            admin_page.goto(NEW_INVOICE)
            admin_page.wait_for_load_state("networkidle")
            assert admin_page.locator("#sourceGate").count() == 0
            admin_page.goto(NEW_PURCHASE)
            admin_page.wait_for_load_state("networkidle")
            assert admin_page.locator("#sourceGate.show").count() == 1
        finally:
            admin_page.goto(f"{BASE_URL}/settings/?tab=inventory")
            admin_page.wait_for_load_state("networkidle")
            sales_order = admin_page.locator(
                'input[name="sales_flow"][value="with_so"]')
            sales_order.check(force=True)
            admin_page.get_by_role("button",
                                   name="Save Inventory Settings").click()
            admin_page.wait_for_load_state("networkidle")