"""E2E for the settings module's relocated section navigation.

The section list used to be a rail on the settings page itself; it now lives
in the app sidebar as tab-scoped nav items (one route, many sections) exactly
like every other module's groups. These tests drive the real browser through
the sidebar: group rendering, link targets, active highlight, gating for a
non-admin, and the mobile behaviour (page has no in-page rail to overflow).
"""

import os

BASE_URL = "http://localhost:" + os.environ.get("E2E_PORT", "5050")


def _nav_links(page):
    return set(a.get_attribute("href")
               for a in page.locator(".sidebar-nav a").all())


def _active_links(page):
    return [a.get_attribute("href")
            for a in page.locator(".sidebar-nav a.active").all()]


def _expand(page, group_text):
    """Expand the group containing the link unless it already is (groups
    remember their state in localStorage, so a blind click would collapse an
    expanded group), then wait out the 300ms max-height transition."""
    hdr = page.locator(".nav-group-header", has_text=group_text)
    group = hdr.locator("..")
    if "expanded" not in (group.get_attribute("class") or ""):
        hdr.click()
        page.wait_for_timeout(500)


def _click_section(page, tab, group_text):
    _expand(page, group_text)
    loc = page.locator(f"a[href='/settings/?tab={tab}']")
    loc.scroll_into_view_if_needed()
    loc.click()


class TestSettingsSidebarSections:
    def test_admin_sees_settings_sections_in_the_sidebar(self, admin_page):
        admin_page.goto(f"{BASE_URL}/settings/")
        page = admin_page
        # The in-page rail is gone.
        assert page.locator(".set-rail").count() == 0
        assert page.locator(".set-main").count() == 1
        # Tabs become sidebar links to the same route with a query param.
        links = _nav_links(page)
        assert "/settings/?tab=account" in links
        assert "/settings/?tab=labels" in links
        assert "/settings/?tab=members" in links
        # The group headers are there (CSS uppercases them on screen).
        body = page.locator(".sidebar-nav").inner_text().lower()
        for label in ("company & finance", "inventory", "invoicing",
                      "administration", "my account"):
            assert label in body

    def test_clicking_a_section_loads_it_and_highlights_it(self, admin_page):
        page = admin_page
        page.goto(f"{BASE_URL}/settings/")
        _click_section(page, "reports", "Company & Finance")
        page.wait_for_url("**/settings/?tab=reports")
        # The report-structure content (its lead-in text) is the loaded section.
        assert "P&L" in page.locator(".set-main").inner_text() or \
               "Profit & Loss" in page.locator(".set-main").inner_text()
        # Exactly one nav item is active and it is the clicked section.
        assert _active_links(page) == ["/settings/?tab=reports"]

    def test_plain_settings_url_highlights_the_first_section(self, admin_page):
        page = admin_page
        page.goto(f"{BASE_URL}/settings/")
        assert "Account" in page.locator(".set-main").inner_text()
        assert _active_links(page) == ["/settings/?tab=account"]

    def test_every_section_loads_through_its_sidebar_link(self, admin_page):
        page = admin_page
        for tab, group in (
            ("company", "Company & Finance"),
            ("labels", "Company & Finance"),
            ("inventory", "Inventory"),
            ("templates", "Invoicing"),
            ("members", "Administration"),
        ):
            page.goto(f"{BASE_URL}/settings/")
            _click_section(page, tab, group)
            page.wait_for_url(f"**/settings/?tab={tab}")
            assert _active_links(page) == [f"/settings/?tab={tab}"]

    def test_sidebar_groups_collapse_like_other_modules(self, admin_page):
        """Sections are collapsible groups, not a flat list: the group with
        the active item is expanded by default."""
        page = admin_page
        page.goto(f"{BASE_URL}/settings/?tab=labels")
        expanded = page.locator(".nav-group.expanded").all_inner_texts()
        assert any("company & finance" in t.lower() for t in expanded)


class TestSettingsSidebarGating:
    def test_employee_only_sees_their_sections(self, hr_user_page):
        page = hr_user_page
        page.goto(f"{BASE_URL}/settings/")
        # Everything a plain employee may touch: account + invites. Nothing
        # module-gated or admin-gated may leak into their sidebar.
        assert _nav_links(page) == {"/settings/?tab=account",
                                    "/settings/?tab=invites"}
        assert _active_links(page) == ["/settings/?tab=account"]

    def test_employee_sidebar_has_no_admin_groups(self, hr_user_page):
        page = hr_user_page
        page.goto(f"{BASE_URL}/settings/")
        text = page.locator(".sidebar-nav").inner_text().lower()
        assert "administration" not in text
        assert "company & finance" not in text
        assert "inventory" not in text
        assert "invoicing" not in text


class TestSettingsMobile:
    def test_settings_on_mobile_has_no_in_page_rail_or_horizontal_scroll(
            self, admin_mobile):
        page = admin_mobile
        page.goto(f"{BASE_URL}/settings/?tab=labels")
        page.wait_for_load_state("networkidle")
        assert page.locator(".set-rail").count() == 0
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth "
            "- document.documentElement.clientWidth")
        assert overflow <= 0, f"horizontal overflow {overflow}px"
        # The sidebar is available through the toggle like every other module.
        page.locator("#sidebar-toggle").click()
        assert page.locator("#sidebar").is_visible()
        assert page.locator("a[href='/settings/?tab=labels']").is_visible()