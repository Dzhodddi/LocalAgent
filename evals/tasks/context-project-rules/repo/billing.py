from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")


def subtotal(lines):
    """Sum of quantity * unit price for (quantity, unit_price) lines."""
    total = sum((Decimal(quantity) * Decimal(price) for quantity, price in lines), Decimal(0))
    return total.quantize(CENTS, rounding=ROUND_HALF_UP)
