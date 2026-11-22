"""The orders HTTP API. `handle()` does the work, so tests need no server."""

import json
import logging
import random
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from orders import metrics
from orders.ids import parse_order_id
from orders.store import ORDERS, PRODUCTS

log = logging.getLogger("orders")


def route_of(path: str) -> str:
    return "/orders" if path.startswith("/orders/") else path


def handle(path: str) -> tuple[int, dict]:
    """(status, JSON body) for a GET request path."""
    url = urlparse(path)
    if url.path == "/health":
        return 200, {"status": "ok"}
    if url.path.startswith("/orders/"):
        order_id = parse_order_id(url.path.removeprefix("/orders/"))
        order = ORDERS.get(order_id)
        return (200, order) if order else (404, {"error": f"order {order_id} not found"})
    if url.path == "/search":
        query = parse_qs(url.query).get("q", [""])[0].lower()
        return 200, {"results": [p for p in PRODUCTS if query in p]}
    return 404, {"error": "no such route"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        started = time.monotonic()
        if self.path == "/metrics":
            self._send(200, metrics.render().encode(), "text/plain; version=0.0.4")
            return
        try:
            if self.path.startswith("/search"):
                time.sleep(random.choice([0.02, 0.05, 0.08, 0.6]))  # the search index is slow sometimes
            status, body = handle(self.path)
        except Exception:
            log.exception("GET %s failed", self.path)
            status, body = 500, {"error": "internal error"}
        self._send(status, json.dumps(body).encode(), "application/json")
        metrics.observe(route_of(urlparse(self.path).path), status, time.monotonic() - started)
        log.info("GET %s %d %.0fms", self.path, status, (time.monotonic() - started) * 1000)

    def _send(self, status, data, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # access lines come from log.info above
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("orders API listening on :8000")
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
