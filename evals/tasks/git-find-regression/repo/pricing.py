def final_price(price, discount_pct):
    """Price after a percentage discount, rounded to cents."""
    return round(price * (1 - discount_pct / 100), 2)
