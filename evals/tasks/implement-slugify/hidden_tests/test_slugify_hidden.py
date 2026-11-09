from text_utils import slugify


def test_runs_collapse():
    assert slugify("a  --  b") == "a-b"


def test_trims_edges():
    assert slugify("  --Python 3.13!--  ") == "python-3-13"


def test_empty_and_symbols():
    assert slugify("") == ""
    assert slugify("!!!") == ""
