import re
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def test_amounts_from_the_logs_parse():
    from services.checkout.amounts import parse_amount

    assert parse_amount("1,299.00") == Decimal("1299.00")
    assert parse_amount("2,450.50") == Decimal("2450.50")
    assert parse_amount("10,000") == Decimal("10000")
    assert parse_amount(" 12.50 ") == Decimal("12.50")


def test_garbage_still_fails():
    from services.checkout.amounts import parse_amount

    with pytest.raises((ValueError, ArithmeticError)):
        parse_amount("twelve")


def test_regression_test_added():
    tests = "".join(p.read_text() for p in (ROOT / "tests").rglob("test_*.py"))
    assert re.search(r"\d,\d{3}", tests), "no test with a thousands separator"
