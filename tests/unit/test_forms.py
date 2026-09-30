"""Numeric/date form helpers: blank means default, garbage is a clean
FormInputError (flashed by the app), never a 500."""
from datetime import date

import pytest
from flask import Flask

from shared.forms import (REQUIRED, FormInputError, form_date, form_float,
                          form_int)

_app = Flask(__name__)


def _form(**data):
    return _app.test_request_context("/", method="POST", data=data)


def test_blank_and_missing_fields_use_the_default():
    with _form(salvage_value="", useful_life="  "):
        assert form_float("salvage_value", 0) == 0
        assert form_int("useful_life", 5) == 5
        assert form_float("absent", 1.5) == 1.5


def test_values_parse_including_thousands_separators():
    with _form(cost="1,250.50", life="7", when="2026-03-04"):
        assert form_float("cost") == 1250.5
        assert form_int("life") == 7
        assert form_date("when") == date(2026, 3, 4)


@pytest.mark.parametrize("fn,value", [(form_float, "abc"), (form_int, "1.5"),
                                      (form_date, "04/03/2026")])
def test_garbage_raises_a_named_form_error(fn, value):
    with _form(purchase_cost=value):
        with pytest.raises(FormInputError, match="Purchase cost"):
            fn("purchase_cost")


def test_required_fields_refuse_blank():
    with _form(basic_salary="", effective_from=""):
        with pytest.raises(FormInputError, match="required"):
            form_float("basic_salary", REQUIRED)
        with pytest.raises(FormInputError, match="required"):
            form_date("effective_from")
