"""In-memory orders, standing in for the database."""

ORDERS = {
    1001 + i: {"id": 1001 + i, "customer": f"customer-{i}", "total": round(19.5 + 7.25 * i, 2), "currency": "EUR"}
    for i in range(10)
}
ORDERS[77] = {"id": 77, "customer": "us-store", "total": 120.0, "currency": "USD"}

PRODUCTS = ["lamp", "sofa", "chair", "desk", "rug", "shelf", "mirror"]
