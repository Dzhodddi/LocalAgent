from services.checkout.amounts import parse_amount


def total(prices: list[str]):
    """Sum of the prices sent by the payment form."""
    return sum((parse_amount(p) for p in prices), parse_amount("0"))
