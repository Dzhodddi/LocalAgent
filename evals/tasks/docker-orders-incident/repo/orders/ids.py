def parse_order_id(raw: str) -> int:
    """The numeric order id from a URL path segment, e.g. "1042"."""
    return int(raw)
