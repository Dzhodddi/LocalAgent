from shop import pricing


def receipt(prices):
    return f"Total: {pricing.calc_total(prices):.2f}"
