"""Pages that render OUTSIDE app_shell must opt into UI v2 themselves.

`templates/layouts/app_shell.html` stamps `data-ui="v2"` on `<html>` and links
`ui.css` for every module in `UI_V2_MODULES`. A page with no shell inherits
none of that, and the failure mode is not a graceful fall back to v1: every
`--v2-*` name the page reaches for becomes undefined, and an undefined custom
property invalidates the whole declaration rather than inheriting, so the page
loses its colours outright (`UI_V2_GUIDE.md` §3).

That is exactly how the landing page, both sign-in screens, the company
portal, the module hub and the super admin console sat on a hardcoded navy
palette long after every module had moved — nine private copies of one light
theme, which `tests/unit/test_ui_css_palette.py` cannot guard because it only
sees `ui.css`. These two tests keep a newly added standalone page from
repeating it.

Kept separate from `test_shell_palette_literals.py` because that file's
subject is the *shared shell* and the v2 modules' Tailwind usage; this one's
subject is the set of templates that bypass the shell entirely.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Roots that can hold a full-page template. superadmin_app is here and absent
# from test_shell_palette_literals.py's list on purpose: the console is not a
# module the shell serves, which is why it was missed by the rollout.
TEMPLATE_ROOTS = [
    "templates",
    "invoicing_app/templates",
    "inventory_app/templates",
    "hr_app/templates",
    "executive_app/templates",
    "fixed_assets_app/templates",
    "finance_app/templates",
    "fbr_app/templates",
    "superadmin_app/templates",
]

# The shell is the thing being opted into; it stamps the attribute from Jinja
# for the modules in UI_V2_MODULES and must keep serving a v1 module unstamped.
EXEMPT = {"templates/layouts/app_shell.html"}

HTML_OPEN = re.compile(r"<html\b[^>]*>", re.I)


def _standalone_pages():
    """Every root template that opens its own <html> (i.e. bypasses the shell)."""
    found = []
    for root in TEMPLATE_ROOTS:
        base = ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.html")):
            rel = path.relative_to(ROOT).as_posix()
            if rel in EXEMPT or path.name.startswith("_"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "{% extends" in text:
                continue  # inherits its <html> from a layout
            if not HTML_OPEN.search(text):
                continue  # a partial or fragment, not a page
            found.append((rel, text))
    return found


PAGES = _standalone_pages()
IDS = [rel for rel, _ in PAGES]


def test_there_are_standalone_pages_to_check():
    """Guard the guard: a broken discovery would make both tests vacuous."""
    assert len(PAGES) >= 8, f"only found {IDS} — discovery is probably broken"


@pytest.mark.parametrize("rel,text", PAGES, ids=IDS)
def test_standalone_page_opts_into_v2(rel, text):
    """The stamp on <html>, and ui.css reaching the page one way or another."""
    opening = HTML_OPEN.search(text).group(0)
    assert 'data-ui="v2"' in opening, (
        f"{rel}: <html> carries no data-ui=\"v2\", so none of the --v2-* names "
        f"it uses resolve and every declaration reading one is dropped "
        f"(UI_V2_GUIDE.md §2/§3). Found: {opening}"
    )
    has_css = "css/ui.css" in text or "_v2_head.html" in text
    assert has_css, (
        f"{rel}: stamped data-ui=\"v2\" but never loads ui.css — the attribute "
        f'selects nothing. Include "partials/_v2_head.html" in <head>.'
    )


@pytest.mark.parametrize("rel,text", PAGES, ids=IDS)
def test_standalone_page_hardcodes_no_light_colour(rel, text):
    """UI_V2_GUIDE.md §9 step 3, made unskippable for these pages.

    A colour literal is allowed in exactly three places: as a `var(--x, #hex)`
    fallback, inside `@media print` (print stays light, §7), and in the favicon
    data-URI, which is not CSS and cannot read a custom property.
    """
    body = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    body = re.sub(r"\{#.*?#\}", "", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"@media\s+print\s*\{.*?\n\s{0,4}\}", "", body, flags=re.S)
    body = re.sub(r"var\(\s*--[\w-]+\s*,[^)]*\)", "", body)
    body = re.sub(r'<link rel="icon"[^>]*>', "", body)
    body = re.sub(r"&#\d+;", "", body)          # HTML entities, not colours
    body = re.sub(r"rgba?\(\s*(?:0\s*,\s*){2}0\s*[^)]*\)", "", body)  # alpha black

    literals = re.findall(r"#[0-9a-fA-F]{3,8}\b", body)
    assert not literals, (
        f"{rel} hardcodes {sorted(set(literals))}. A fixed light value keeps "
        f"its colour when the text around it turns light (§7) — reach for a "
        f"token, or write it as a var() fallback."
    )
