"""The shared shell and the v2 modules must not carry hardcoded light colours.

`UI_V2_GUIDE.md` §9 step 3 is a manual grep — "check the page for hex literals
inside `<style>` and for Tailwind colour utilities". Manual greps get skipped,
and both classes of literal fail the same silent way: the page renders, it just
renders a near-white block that keeps its colour when the text on it turns
light. The company switcher in `app_shell.html` shipped exactly that — a `#fff`
pill labelled `var(--ink)`, which is near-white-on-white in dark mode, in the
topbar of every module.

Two rules, one per test:

* The shell's own `<style>` speaks only token names. It is the one stylesheet
  loaded for **both** v1 and v2 modules, so it may not reach for a `--v2-*`
  name either (undefined on v1 kills the whole declaration, §3) — the bridge
  names in `app.css`/`ui.css` are what it is allowed to use.
* No template in a v2 module uses a Tailwind colour utility. Tailwind ships a
  fixed light palette, so `text-slate-400` is the first rule wearing a class
  name (§7).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_SHELL = ROOT / "templates" / "layouts" / "app_shell.html"

# Template roots for the modules listed in UI_V2_MODULES.
V2_TEMPLATE_ROOTS = [
    "templates",
    "invoicing_app/templates",
    "inventory_app/templates",
    "hr_app/templates",
    "executive_app/templates",
    "fixed_assets_app/templates",
    "finance_app/templates",
    "fbr_app/templates",
]

# Standalone popups (print/preview) re-declare a light palette on purpose:
# "Print stays light" (§7). They opt out of the hex rule inside @media print.
_TAILWIND_COLOUR = re.compile(
    r"\b(?:bg|text|border|ring|divide|from|via|to)-"
    r"(?:slate|gray|grey|zinc|neutral|stone|red|orange|amber|yellow|lime|green|"
    r"emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b"
)


def _strip_comments(text):
    """Drop CSS, Jinja and HTML comments.

    A rule that has been *documented as removed* still names the thing it
    replaced — the finance layout explains at length why `text-red-600` is gone.
    Matching those would make the test unfixable without deleting the reasoning.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return text


def _style_blocks(text):
    return re.findall(r"<style\b[^>]*>(.*?)</style>", text, flags=re.S | re.I)


def test_app_shell_style_uses_only_token_names():
    """No colour literal in the shell's <style>; it is shared by v1 and v2."""
    css = _strip_comments("\n".join(_style_blocks(APP_SHELL.read_text(encoding="utf-8"))))
    # rgba(0,0,0,...) shadows are alpha black — correct in either theme.
    css = re.sub(r"rgba\(\s*(?:0\s*,\s*){2}0\s*,[^)]*\)", "", css)
    css = re.sub(r"rgba\(\s*(?:255\s*,\s*){2}255\s*,[^)]*\)", "", css)

    literals = re.findall(r"#[0-9a-fA-F]{3,8}\b", css)
    assert not literals, (
        f"{APP_SHELL.name} <style> hardcodes {literals}. Use a bridge token "
        "(--surface, --ink, --line, --wash, --primary, --on-fill, --link, "
        "--ledger-dim) so v1 keeps its palette and v2 follows the theme."
    )


def test_app_shell_style_avoids_v2_only_tokens():
    """A --v2-* name is undefined on a v1 module and voids the declaration."""
    css = _strip_comments("\n".join(_style_blocks(APP_SHELL.read_text(encoding="utf-8"))))
    used = sorted(set(re.findall(r"var\(\s*(--v2-[\w-]+)", css)))
    assert not used, (
        f"{APP_SHELL.name} reads v2-only tokens {used}. The shell renders for "
        "modules outside UI_V2_MODULES too, where those names do not exist — "
        "an undefined custom property invalidates the whole declaration."
    )


@pytest.mark.parametrize("root", V2_TEMPLATE_ROOTS)
def test_no_tailwind_colour_utilities_in_v2_modules(root):
    """Tailwind's colour scale is a fixed light palette (§7)."""
    base = ROOT / root
    if not base.is_dir():
        pytest.skip(f"{root} not present")

    offenders = []
    for path in base.rglob("*.html"):
        for lineno, line in enumerate(
            _strip_comments(path.read_text(encoding="utf-8", errors="replace")).splitlines(), 1
        ):
            for hit in _TAILWIND_COLOUR.findall(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {hit}")

    assert not offenders, "Tailwind colour utilities keep their light value in dark mode:\n" + "\n".join(
        offenders
    )
