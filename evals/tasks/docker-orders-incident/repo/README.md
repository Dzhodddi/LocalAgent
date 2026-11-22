# Orders API

A small HTTP API for orders, run with Docker Compose:

- `orders`: the API on port 8000 (`python -m orders.app`), Prometheus metrics at `/metrics`
- `traffic`: replays production-like requests against `orders`
- `prometheus`: scrapes `orders` every 5 seconds

Routes: `GET /orders/<id>`, `GET /search?q=<text>`, `GET /health`.

Order ids are numbers. Since mobile app v3, clients may send an id with a region prefix,
`<REGION>-<number>` (e.g. `EU-1042`, `US-77`); the number after the dash is the order id.

Tests: `python -m pytest -q`
