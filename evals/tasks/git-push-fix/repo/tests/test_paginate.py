from paginate import paginate


def test_even_split():
    assert paginate([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
