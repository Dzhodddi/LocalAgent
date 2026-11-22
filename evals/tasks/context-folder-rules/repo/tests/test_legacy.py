from legacy.users import find_user


def test_find_user():
    assert find_user([{"id": 1}], 1) == {"id": 1}
    assert find_user([], 1) is None
