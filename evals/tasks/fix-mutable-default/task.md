Bug report: calling `add_item()` from cart.py several times without passing `items`
returns a list that still contains items from earlier calls. Each call without `items`
should start from an empty list. Fix the bug and add a test for it in tests/test_cart.py.
