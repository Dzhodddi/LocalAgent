from decimal import Decimal

from billing import subtotal


def test_subtotal():
    assert subtotal([(2, "1.10"), (1, "0.05")]) == Decimal("2.25")
