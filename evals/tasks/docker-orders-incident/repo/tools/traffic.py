"""Production-like requests against the orders API, forever."""

import random
import time
import urllib.error
import urllib.request

BASE = "http://orders:8000"
PATHS = (
    [f"/orders/{1001 + i}" for i in range(10)] * 3
    + ["/orders/77", "/orders/9999"]
    + ["/orders/EU-1003", "/orders/EU-1007", "/orders/US-77"]  # mobile app v3
    + ["/search?q=lamp", "/search?q=so", "/search?q=desk", "/health"]
)

if __name__ == "__main__":
    random.seed(7)
    while True:
        try:
            urllib.request.urlopen(BASE + random.choice(PATHS), timeout=5).read()
        except (urllib.error.URLError, OSError):
            pass  # errors show up in the orders logs and metrics
        time.sleep(0.15)
