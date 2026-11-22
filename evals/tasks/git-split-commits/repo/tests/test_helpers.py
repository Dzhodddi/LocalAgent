from mathx import mean
from textstats import word_count


def test_word_count():
    assert word_count("one  two\nthree") == 3


def test_mean():
    assert mean([1, 2, 3]) == 2
