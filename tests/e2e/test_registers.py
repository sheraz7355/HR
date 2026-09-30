"""E2E: bulk invoice + voucher registers — lazy view, filter, export, print."""
import os

BASE_URL = "http://127.0.0.1:" + os.environ.get("E2E_PORT", "5050")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class TestInvoiceRegister:
    def test_view_does_not_autoload(self, admin_page):
        admin_page.goto(f"{BASE_URL}/invoicing/registers/")
        admin_page.wait_for_load_state("networkidle")
        body = admin_page.locator("body").inner_text()
        assert "Invoice Register" in body
        for label in ("Month", "Financial Year", "Custom Range"):
            assert label in body
        assert "Load Invoices" in body
        assert "press View" in body
        # Nothing fetched yet: no rows, no totals.
        assert admin_page.locator("#regBody tr").count() == 0

    def test_view_button_loads_the_table(self, admin_page):
        admin_page.goto(
            f"{BASE_URL}/invoicing/registers/?doc=sales&mode=month&month=2026-01")
        admin_page.wait_for_load_state("networkidle")
        admin_page.click("#regLoadBtn")
        admin_page.wait_for_selector("#regLoaded:not([style*='none'])",
                                     timeout=30000)
        body = admin_page.locator("body").inner_text()
        assert "TOTAL" in body
        assert "January 2026" in body

    def test_purchase_register_loads(self, admin_page):
        admin_page.goto(f"{BASE_URL}/invoicing/registers/?doc=purchase")
        admin_page.wait_for_load_state("networkidle")
        body = admin_page.locator("body").inner_text()
        assert "Purchase Invoice Register" in body
        assert "Supplier" in body

    def test_month_filter_labels_the_view(self, admin_page):
        admin_page.goto(
            f"{BASE_URL}/invoicing/registers/?doc=sales&mode=month&month=2026-01")
        admin_page.wait_for_load_state("networkidle")
        assert "January 2026" in admin_page.locator("body").inner_text()

    def test_custom_filter_labels_the_view(self, admin_page):
        admin_page.goto(
            f"{BASE_URL}/invoicing/registers/?doc=sales&mode=custom"
            "&from=2026-01-05&to=2026-01-20")
        admin_page.wait_for_load_state("networkidle")
        body = admin_page.locator("body").inner_text()
        assert "05 Jan 2026" in body and "20 Jan 2026" in body

    def test_export_buttons_appear_after_load(self, admin_page):
        admin_page.goto(
            f"{BASE_URL}/invoicing/registers/?doc=sales&mode=month&month=2026-01")
        admin_page.wait_for_load_state("networkidle")
        admin_page.click("#regLoadBtn")
        admin_page.wait_for_selector("#regLoaded:not([style*='none'])",
                                     timeout=30000)
        excel = admin_page.locator("a[href*='fmt=excel']").first
        pdf = admin_page.locator("a[href*='fmt=pdf']").first
        assert "month=2026-01" in (excel.get_attribute("href") or "")
        assert "month=2026-01" in (pdf.get_attribute("href") or "")
        assert admin_page.locator("#regActions button:has-text('Print')").is_visible()

    def test_rows_link_to_full_invoice_view(self, admin_page):
        admin_page.goto(
            f"{BASE_URL}/invoicing/registers/?doc=sales&mode=custom&from=2020-01-01&to=2030-01-01&view=1")
        admin_page.wait_for_load_state("networkidle")
        links = admin_page.locator(".reg-table a[href*='/inventory/invoices/']")
        if links.count():
            assert "View" in (links.first.inner_text() or "")

    def test_excel_export_downloads(self, admin_page):
        resp = admin_page.request.get(
            f"{BASE_URL}/invoicing/registers/export?fmt=excel&doc=sales")
        assert resp.status == 200
        assert XLSX in resp.headers.get("content-type", "")
        assert len(resp.body()) > 1000

    def test_pdf_export_downloads(self, admin_page):
        resp = admin_page.request.get(
            f"{BASE_URL}/invoicing/registers/export?fmt=pdf&doc=purchase")
        assert resp.status == 200
        assert "application/pdf" in resp.headers.get("content-type", "")
        assert resp.body()[:5] == b"%PDF-"

    def test_unknown_format_is_404(self, admin_page):
        resp = admin_page.request.get(
            f"{BASE_URL}/invoicing/registers/export?fmt=csv")
        assert resp.status == 404

    def test_bulk_documents_load_full_invoices(self, admin_page):
        admin_page.goto(
            f"{BASE_URL}/invoicing/registers/documents?doc=sales&mode=custom&from=2020-01-01&to=2030-01-01")
        admin_page.wait_for_load_state("networkidle")
        # Chunked loader finishes: overlay closes, actions appear.
        admin_page.wait_for_selector("body[data-docs='done']", timeout=60000)
        body = admin_page.locator("body").inner_text()
        assert "Sales Invoice Register" in body


class TestVoucherRegister:
    def test_view_does_not_autoload(self, admin_page):
        admin_page.goto(f"{BASE_URL}/accounting/registers/vouchers")
        admin_page.wait_for_load_state("networkidle")
        body = admin_page.locator("body").inner_text()
        assert "Voucher Register" in body
        assert "Load Vouchers" in body
        assert "Load Vouchers" in (
            admin_page.locator("#regDocsBtn").inner_text() or "")
        assert admin_page.locator("#regBody tr").count() == 0

    def test_view_button_loads_the_table(self, admin_page):
        admin_page.goto(
            f"{BASE_URL}/accounting/registers/vouchers?mode=month&month=2026-01")
        admin_page.wait_for_load_state("networkidle")
        admin_page.click("#regLoadBtn")
        admin_page.wait_for_selector("#regLoaded:not([style*='none'])",
                                     timeout=30000)
        body = admin_page.locator("body").inner_text()
        assert "TOTAL" in body
        assert "Description" in body
        assert "Status" not in admin_page.locator(
            ".voucher-table thead").inner_text()

    def test_type_filter_labels_the_view(self, admin_page):
        admin_page.goto(
            f"{BASE_URL}/accounting/registers/vouchers?vtype=JV")
        admin_page.wait_for_load_state("networkidle")
        assert "Journal Voucher" in admin_page.locator("body").inner_text()

    def test_rows_link_to_full_voucher_view(self, admin_page):
        admin_page.goto(
            f"{BASE_URL}/accounting/registers/vouchers?mode=custom&from=2020-01-01&to=2030-01-01&view=1")
        admin_page.wait_for_load_state("networkidle")
        links = admin_page.locator("a.vnum")
        if links.count():
            href = links.first.get_attribute("href") or ""
            assert "/accounting/vouchers/" in href and "/preview" in href

    def test_excel_export_downloads(self, admin_page):
        resp = admin_page.request.get(
            f"{BASE_URL}/accounting/registers/vouchers/export?fmt=excel")
        assert resp.status == 200
        assert XLSX in resp.headers.get("content-type", "")
        assert len(resp.body()) > 1000

    def test_pdf_export_downloads(self, admin_page):
        resp = admin_page.request.get(
            f"{BASE_URL}/accounting/registers/vouchers/export?fmt=pdf&vtype=JV")
        assert resp.status == 200
        assert "application/pdf" in resp.headers.get("content-type", "")
        assert resp.body()[:5] == b"%PDF-"

    def test_unknown_format_is_404(self, admin_page):
        resp = admin_page.request.get(
            f"{BASE_URL}/accounting/registers/vouchers/export?fmt=csv")
        assert resp.status == 404

    def test_bulk_documents_load_full_vouchers(self, admin_page):
        admin_page.goto(
            f"{BASE_URL}/accounting/registers/vouchers/documents?mode=custom&from=2020-01-01&to=2030-01-01")
        admin_page.wait_for_load_state("networkidle")
        admin_page.wait_for_selector("body[data-docs='done']", timeout=60000)
        body = admin_page.locator("body").inner_text()
        assert "Bulk Vouchers" in body
