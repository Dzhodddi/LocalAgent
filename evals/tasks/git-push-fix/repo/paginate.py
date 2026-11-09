def paginate(items, page_size):
    """Split items into consecutive pages of at most page_size items."""
    pages = []
    for start in range(0, len(items) - page_size, page_size):
        pages.append(items[start : start + page_size])
    return pages
