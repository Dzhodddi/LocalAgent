from inventory.models import Item
from inventory.report import summary
from inventory.storage import load


def test_summary():
    items = [Item("a", 2, 1.5), Item("b", 10, 1.0)]
    assert summary(items) == "2 items, value 13.00, low stock: a"


def test_load_plain_prices(tmp_path):
    (tmp_path / "s.csv").write_text("name,quantity,price\nbolt,4,0.25\n")
    assert load(tmp_path / "s.csv") == [Item("bolt", 4, 0.25)]


def test_load_stock_file():
    assert summary(load("stock.csv")) == "2 items, value 3630.00, low stock: drill"
