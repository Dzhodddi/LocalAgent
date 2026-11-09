import pytest
from stack import Stack


def test_push_pop():
    s = Stack()
    s.push(1)
    s.push(2)
    assert s.pop() == 2
    assert len(s) == 1


def test_pop_empty():
    with pytest.raises(IndexError):
        Stack().pop()
