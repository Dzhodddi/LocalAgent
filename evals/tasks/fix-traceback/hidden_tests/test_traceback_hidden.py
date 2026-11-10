def test_dollar_prices(tmp_path):
    from inventory.models import Item
    from inventory.storage import load

    (tmp_path / "s.csv").write_text('name,quantity,price\na,1,$2.50\nb,2,"$1,200.00"\nc,3,3.5\n')
    assert load(tmp_path / "s.csv") == [Item("a", 1, 2.5), Item("b", 2, 1200.0), Item("c", 3, 3.5)]


def test_report_runs():
    from inventory.report import summary
    from inventory.storage import load

    assert summary(load("stock.csv")) == "2 items, value 3630.00, low stock: drill"
