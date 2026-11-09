from paginate import paginate


def test_partial_last_page():
    assert paginate([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_empty():
    assert paginate([], 3) == []


def test_page_larger_than_items():
    assert paginate([1, 2], 10) == [[1, 2]]
