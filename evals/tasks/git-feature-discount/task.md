Add customer discounts. `Customer` in customer.py gets a new field
`discount_pct: float = 0.0`, and `Order.total()` in order.py applies the customer's
discount (10 means 10% off), rounded to cents. Add a test for it. Do the work on a new
branch `feat/customer-discount`, commit it and push the branch to `origin`.
