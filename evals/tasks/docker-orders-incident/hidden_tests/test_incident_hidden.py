import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def test_region_prefixed_ids():
    from orders.ids import parse_order_id

    assert parse_order_id("EU-1003") == 1003
    assert parse_order_id("US-77") == 77
    assert parse_order_id("1042") == 1042


def test_handler_serves_prefixed_ids():
    from orders.app import handle

    status, body = handle("/orders/EU-1007")
    assert status == 200 and body["id"] == 1007


def test_bad_ids_still_rejected():
    from orders.ids import parse_order_id

    for raw in ("abc", "EU-", "EU-x1"):
        with pytest.raises(ValueError):
            parse_order_id(raw)


def test_regression_test_added():
    tests = "".join(p.read_text() for p in (ROOT / "tests").rglob("test_*.py"))
    assert re.search(r"[A-Z]{2}-\d+", tests), "no test with a region-prefixed id"
