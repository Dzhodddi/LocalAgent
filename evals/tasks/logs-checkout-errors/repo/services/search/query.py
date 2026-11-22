def normalize_query(text: str) -> str:
    """Lower-case words separated by single spaces."""
    return " ".join(text.lower().split())
