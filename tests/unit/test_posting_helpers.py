"""Document dates and label splits used by every posting route."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from shared.posting_helpers import (DocumentDateError, label_weights,
                                    parse_doc_date, split_by_label)


def test_doc_date_parses_iso_to_midnight():
    assert parse_doc_date("2026-03-15") == datetime(2026, 3, 15)


def test_blank_doc_date_keeps_the_existing_date():
    existing = datetime(2025, 12, 31, 17, 45)
    assert parse_doc_date("", fallback=existing) == datetime(2025, 12, 31)


def test_blank_doc_date_without_fallback_is_today():
    assert parse_doc_date(None).date() == date.today()


def test_malformed_doc_date_is_refused_not_silently_today():
    with pytest.raises(DocumentDateError):
        parse_doc_date("31/31/2026")


def test_single_label_takes_the_whole_amount():
    assert split_by_label(100, {7: Decimal("1")}) == [(7, Decimal("100.00"))]


def test_split_is_pro_rata_and_cent_exact():
    parts = split_by_label(100, label_weights([(1, 1), (2, 1), (3, 1)]))
    assert [l for l, _ in parts] == [1, 2, 3]
    assert sum(a for _, a in parts) == Decimal("100.00")
    assert parts[0][1] == Decimal("33.33")
    assert parts[-1][1] == Decimal("33.34"), "the remainder lands on the last label"


def test_weights_for_the_same_label_accumulate():
    w = label_weights([(1, 30), (2, 10), (1, 60)])
    assert w == {1: Decimal("90"), 2: Decimal("10")}
    assert split_by_label(50, w) == [(1, Decimal("45.00")), (2, Decimal("5.00"))]


def test_zero_weights_fall_back_to_the_first_label():
    assert split_by_label(10, {None: Decimal("0"), 4: Decimal("0")}) == [(None, Decimal("10.00"))]
