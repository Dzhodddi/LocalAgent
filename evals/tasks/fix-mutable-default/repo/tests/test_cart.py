from cart import add_item


def test_add_to_given_list():
    assert add_item("b", ["a"]) == ["a", "b"]
