LOW_STOCK = 5


def summary(items):
    total = sum(item.value for item in items)
    low = sorted(item.name for item in items if item.quantity < LOW_STOCK)
    return f"{len(items)} items, value {total:.2f}, low stock: {', '.join(low) or 'none'}"
