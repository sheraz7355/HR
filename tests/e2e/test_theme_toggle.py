"""Every page can switch between light and dark, and the switch is honest.

The theme switch used to live only in the app shell's top bar, so the ERP
Hub, the company portal, the super admin console, the landing page and the
sign-in screens had no way to change theme. And the shell's own switch read
only the data-theme attribute: with the OS in dark mode and nothing stored,
the first click "switched" to the dark theme already on screen and nothing
happened. static/js/theme.js now reads the theme as the user sees it.
"""
import os

import pytest

BASE_URL = "http://127.0.0.1:" + os.environ.get("E2E_PORT", "5050")


def _login(page):
    page.goto(f"{BASE_URL}/superadmin/login")
    page.fill("#login", "admin@gmail.com")
    page.fill("#password", "admin123")
    page.click("button[type='submit']")
    page.wait_for_url("**/superadmin/**")


def _effective(page):
    return page.evaluate("document.documentElement.getAttribute('data-theme-effective')")


@pytest.fixture
def dark_os(browser, flask_server):
    ctx = browser.new_context(color_scheme="dark", viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    yield page
    ctx.close()


@pytest.fixture
def light_os(browser, flask_server):
    ctx = browser.new_context(color_scheme="light", viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    yield page
    ctx.close()


@pytest.mark.parametrize("path", ["/", "/auth/login", "/superadmin/login"])
def test_public_pages_have_a_working_switch(light_os, path):
    page = light_os
    page.goto(BASE_URL + path)
    btn = page.locator("[data-theme-toggle]")
    assert btn.count() == 1 and btn.is_visible()
    assert _effective(page) == "light"
    btn.click()
    assert _effective(page) == "dark"
    assert page.evaluate("localStorage.getItem('ax-theme')") == "dark"


@pytest.mark.parametrize("path", ["/portal/", "/superadmin/", "/dashboard/"])
def test_signed_in_standalone_pages_have_a_switch(light_os, path):
    page = light_os
    _login(page)
    if path == "/dashboard/":
        page.goto(f"{BASE_URL}/portal/")
        page.locator("a.enter").first.click()
        page.wait_for_url("**/dashboard/**")
    else:
        page.goto(BASE_URL + path)
    btn = page.locator("[data-theme-toggle]")
    assert btn.count() == 1 and btn.is_visible()
    btn.click()
    assert _effective(page) == "dark"
    # The choice follows the user into the app.
    page.reload()
    assert _effective(page) == "dark"
    page.evaluate("localStorage.removeItem('ax-theme')")


def test_first_click_on_an_os_dark_page_goes_light(dark_os):
    page = dark_os
    page.goto(f"{BASE_URL}/auth/login")
    page.evaluate("localStorage.removeItem('ax-theme')")
    page.reload()
    assert _effective(page) == "dark"
    # The glyph offers the theme you would move to: a sun on a dark page.
    assert page.locator("[data-theme-toggle] .t-dark").is_visible()
    page.locator("[data-theme-toggle]").click()
    assert _effective(page) == "light"
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "light"
    page.evaluate("localStorage.removeItem('ax-theme')")


def test_sign_in_switch_floats_clear_of_the_form(light_os):
    page = light_os
    page.goto(f"{BASE_URL}/auth/login")
    pos = page.evaluate("getComputedStyle(document.querySelector('[data-theme-toggle]')).position")
    assert pos == "fixed"
