from pathlib import Path

from cart import add_item


def test_calls_are_independent():
    assert add_item("x") == ["x"]
    assert add_item("y") == ["y"]


def test_given_list_still_used():
    items = ["a"]
    assert add_item("b", items) is items


def test_agent_added_a_test():
    source = (Path(__file__).parent.parent / "tests" / "test_cart.py").read_text()
    assert source.count("def test_") >= 2
