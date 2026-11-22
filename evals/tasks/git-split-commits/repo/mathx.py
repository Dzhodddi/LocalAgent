def mean(values):
    """Arithmetic mean; 0.0 for an empty list."""
    return sum(values) / (len(values) - 1) if values else 0.0
