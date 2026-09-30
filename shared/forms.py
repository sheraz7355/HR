"""Numeric form fields that never 500.

``float(request.form.get("salvage_value", 0))`` only falls back when the field
is ABSENT; a field submitted blank arrives as ``""`` and ``float("")`` raised
straight through to the 500 page. These read a blank field as its default and
turn anything unparseable into a ``FormInputError`` naming the field, which
the app-wide handler flashes before sending the user back to the form.
"""
from flask import request


class FormInputError(ValueError):
    """A submitted field could not be read as the number it must be."""


# Pass as ``default`` for a field that must be filled in.
REQUIRED = object()


def _blank(name, default, label):
    if default is REQUIRED:
        raise FormInputError(
            f"{label or name.replace('_', ' ').capitalize()} is required.")
    return default


def _raw(name):
    value = request.form.get(name)
    return value.strip() if isinstance(value, str) else value


def form_float(name, default=0.0, label=None):
    raw = _raw(name)
    if raw in (None, ""):
        return _blank(name, default, label)
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        raise FormInputError(
            f"{label or name.replace('_', ' ').capitalize()} must be a number."
        ) from None


def form_int(name, default=0, label=None):
    raw = _raw(name)
    if raw in (None, ""):
        return _blank(name, default, label)
    try:
        return int(raw)
    except ValueError:
        raise FormInputError(
            f"{label or name.replace('_', ' ').capitalize()} must be a whole "
            f"number."
        ) from None


def form_date(name, default=None, label=None, fmt="%Y-%m-%d"):
    from datetime import datetime
    raw = _raw(name)
    if raw in (None, ""):
        return _blank(name, REQUIRED if default is None else default, label)
    try:
        return datetime.strptime(raw, fmt).date()
    except ValueError:
        raise FormInputError(
            f"{label or name.replace('_', ' ').capitalize()} is not a valid "
            f"date.") from None
