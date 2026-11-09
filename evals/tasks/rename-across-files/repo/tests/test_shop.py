from shop.cart import Cart
from shop.report import receipt


def test_cart_total():
    cart = Cart()
    cart.add(10)
    cart.add(5)
    assert cart.total(0.1) == 16.5


def test_receipt():
    assert receipt([1, 2.5]) == "Total: 3.50"
