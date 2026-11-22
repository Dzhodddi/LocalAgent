from customer import Customer
from order import Order


def test_total():
    order = Order(Customer("ann"))
    order.add("tea", 2, 3.5)
    order.add("cake", 1, 4.25)
    assert order.total() == 11.25
