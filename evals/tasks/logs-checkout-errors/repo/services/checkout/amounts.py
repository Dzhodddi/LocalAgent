from decimal import Decimal


def parse_amount(text: str) -> Decimal:
    """Parse an amount as sent by the payment form, e.g. "12.50"."""
    return Decimal(text.strip())
