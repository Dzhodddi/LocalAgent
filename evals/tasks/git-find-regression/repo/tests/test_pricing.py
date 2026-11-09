from pricing import final_price


def test_twenty_percent_off():
    assert final_price(100, 20) == 80
