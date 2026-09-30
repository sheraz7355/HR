"""FIFO aging of one party: surviving layers must always sum to its balance."""
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from shared.executive_reports import PAYABLE, RECEIVABLE, _age_party

ACCT = SimpleNamespace(code="1101", name="Customer A")
AS_OF = date(2026, 3, 31)


def _row(day, dr=0, cr=0):
    return (datetime(2026, 3, day), Decimal(str(dr)), Decimal(str(cr)))


def test_payment_consumes_oldest_layer_first():
    rows = [_row(1, dr=1000), _row(26, dr=400), _row(28, cr=400)]
    party = _age_party(1, ACCT, rows, Decimal("1000"), AS_OF, RECEIVABLE)
    assert party["layers"] == [(30, Decimal("600.00")), (5, Decimal("400.00"))]


def test_advance_received_before_the_invoice_settles_it():
    """Advance 400 on the 1st, invoice 1,000 on the 21st: 600 is owed, aged
    from the invoice — not 1,000 against a 600 balance."""
    rows = [_row(1, cr=400), _row(21, dr=1000)]
    party = _age_party(1, ACCT, rows, Decimal("600"), AS_OF, RECEIVABLE)
    assert party["layers"] == [(10, Decimal("600.00"))]
    assert sum(a for _d, a in party["layers"]) == Decimal("600")
    assert party["avg_days"] == 10


def test_prepayment_to_a_supplier_mirrors_it():
    rows = [_row(1, dr=250), _row(11, cr=1000), _row(21, cr=500)]
    party = _age_party(2, ACCT, rows, Decimal("1250"), AS_OF, PAYABLE)
    assert party["layers"] == [(20, Decimal("750.00")), (10, Decimal("500.00"))]
