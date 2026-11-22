from orders.app import handle
from orders.ids import parse_order_id


def test_parse_plain_id():
    assert parse_order_id("1042") == 1042


def test_get_order():
    status, body = handle("/orders/1001")
    assert status == 200 and body["id"] == 1001


def test_missing_order():
    assert handle("/orders/9999")[0] == 404


def test_search():
    assert handle("/search?q=lamp") == (200, {"results": ["lamp"]})
