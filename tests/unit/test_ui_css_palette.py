"""Structural guarantees about the UI v2 palette in ``static/css/ui.css``.

None of this is style policing. Each check pins a rule that, when it broke in
the past, broke *silently* — the page still rendered, it just rendered wrong,
and only in a state (dark mode, the print dialog) that nobody looks at on the
way to shipping something else.

The three rules:

* The dark palette exists twice — once for ``data-theme="dark"`` and once
  inside ``@media (prefers-color-scheme:dark)`` — because CSS cannot share one
  declaration list across a media-query boundary. Two lists that must agree is
  exactly the shape of a bug that ships, so they are compared here.
* Print re-declares the light palette, and has to out-specify the dark ones to
  do it: ``@media`` adds no specificity, so a plain ``[data-ui="v2"]`` block
  loses to ``[data-ui="v2"][data-theme="dark"]`` and a dark-mode user prints
  near-white text onto paper.
* Every token the dark palette overrides has to exist in the light one, or the
  two themes are describing different vocabularies and something is undefined
  in one of them — and an undefined custom property invalidates the whole
  declaration that reads it rather than falling back.
"""

import re
from pathlib import Path

import pytest

UI_CSS = Path(__file__).resolve().parents[2] / "static" / "css" / "ui.css"

# Tokens the print palette deliberately does not restate: they are shadows and
# the rail, which print flattens anyway.
_PRINT_EXEMPT = {"--v2-rail"}


@pytest.fixture(scope="module")
def css():
    return UI_CSS.read_text(encoding="utf-8")


def _block(css_text, selector):
    """Return the declaration text of the first rule whose selector matches.

    Deliberately a small brace-counter rather than a regex: the print rule is
    nested inside ``@media``, and a regex that tolerates that would be less
    readable than this.
    """
    start = css_text.index(selector)
    open_brace = css_text.index("{", start)
    depth, i = 1, open_brace + 1
    while depth:
        if css_text[i] == "{":
            depth += 1
        elif css_text[i] == "}":
            depth -= 1
        i += 1
    return css_text[open_brace + 1 : i - 1]


def _tokens(block_text):
    """Custom-property declarations in a block, as {name: value}."""
    return {
        name: value.strip()
        for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block_text)
    }


def test_toggle_and_os_dark_palettes_are_identical(css):
    """The two dark blocks must not drift apart.

    If this fails, someone edited one dark palette and not the other, and the
    app now looks different depending on *how* you asked for dark rather than
    whether you asked for it.
    """
    toggled = _tokens(_block(css, '[data-ui="v2"][data-theme="dark"]'))
    os_level = _tokens(_block(css, '[data-ui="v2"]:not([data-theme="light"])'))

    assert toggled, "no tokens found in the data-theme=dark block"
    assert toggled == os_level, (
        "the data-theme=dark palette and the prefers-color-scheme palette "
        "disagree; edit both or neither"
    )


def test_os_dark_yields_to_an_explicit_light_choice(css):
    """The OS rule must exclude data-theme="light", or the toggle is one-way.

    Both selectors are (0,2,0), so precedence is source order alone: without
    the :not(), a user on a dark OS could never choose light.
    """
    media = css.index("@media (prefers-color-scheme:dark)")
    assert '[data-ui="v2"]:not([data-theme="light"])' in css[media:], (
        "the prefers-color-scheme block must target "
        '[data-ui="v2"]:not([data-theme="light"])'
    )
    assert media > css.index('[data-ui="v2"][data-theme="dark"]'), (
        "the OS block must come after the toggle block to win the tie"
    )


def test_print_palette_outspecifies_every_dark_palette(css):
    """Print must beat both dark selectors, and come last to do it."""
    print_at = css.index("@media print")
    print_selectors = css[print_at : css.index("{", css.index("{", print_at) + 1)]

    for selector in ('[data-ui="v2"][data-theme="dark"]',
                     '[data-ui="v2"]:not([data-theme="light"])'):
        assert selector in print_selectors, (
            f"@media print does not answer {selector}; a dark-mode user prints "
            "the dark palette onto paper"
        )
        assert print_at > css.index(selector), (
            "@media print must come after the dark palettes it overrides"
        )

    printed = _tokens(_block(css, "@media print"))
    assert printed["--v2-ground"].upper() == "#FFFFFF"
    assert printed["--v2-surface"].upper() == "#FFFFFF"


def test_dark_and_print_only_override_tokens_the_light_palette_defines(css):
    """No theme may invent a token the base palette never declared."""
    light = _tokens(_block(css, '[data-ui="v2"]{'))
    assert light, "no tokens found in the base [data-ui=v2] block"

    for label, selector in (
        ("dark", '[data-ui="v2"][data-theme="dark"]'),
        ("print", "@media print"),
    ):
        unknown = set(_tokens(_block(css, selector))) - set(light)
        assert not unknown, f"{label} palette declares tokens light never does: {unknown}"


def test_print_restates_every_colour_token(css):
    """A token left un-restated by print keeps its dark value on paper."""
    dark = set(_tokens(_block(css, '[data-ui="v2"][data-theme="dark"]')))
    printed = set(_tokens(_block(css, "@media print")))
    missing = dark - printed - _PRINT_EXEMPT
    assert not missing, (
        f"print does not restate {sorted(missing)}; those keep their dark "
        "values when a dark-mode page is printed"
    )
