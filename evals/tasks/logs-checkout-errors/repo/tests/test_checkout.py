from decimal import Decimal

from services.checkout.amounts import parse_amount
from services.checkout.cart import total


def test_parse_amount():
    assert parse_amount(" 12.50 ") == Decimal("12.50")


def test_total():
    assert total(["1.10", "2.05"]) == Decimal("3.15")
