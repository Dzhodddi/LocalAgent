from pathlib import Path

import pytest
from stack import Stack


def test_peek_keeps_item():
    s = Stack()
    s.push("a")
    s.push("b")
    assert s.peek() == "b"
    assert len(s) == 2


def test_peek_empty():
    with pytest.raises(IndexError, match="peek from empty stack"):
        Stack().peek()


def test_agent_added_tests():
    source = (Path(__file__).parent.parent / "tests" / "test_stack.py").read_text()
    assert "peek" in source
