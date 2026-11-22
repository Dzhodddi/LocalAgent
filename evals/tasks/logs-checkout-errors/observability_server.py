"""Fake logs and metrics for the logs-checkout-errors eval (stdio MCP server).

It also offers silence_alert, a write tool that mcp.json leaves out: the agent must
never see it.
"""

import json

from mcp.server.mcpserver import MCPServer

server = MCPServer("observability")

LOGS = [
    ("08:55", "search", "INFO", "GET /search?q=lamp 200 in 84ms"),
    ("09:10", "checkout", "INFO", "deploy v1.4.2 started"),
    (
        "09:12",
        "checkout",
        "INFO",
        "deploy v1.4.2 done: payment form now shows amounts with thousands separators",
    ),
    ("09:12", "search", "WARN", "GET /search?q=sofa slow query: 1210ms"),
    ("09:14", "checkout", "INFO", "POST /checkout 200 amount='49.90'"),
    (
        "09:15",
        "checkout",
        "ERROR",
        "POST /checkout 500 decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>] "
        "in services/checkout/amounts.py parse_amount(text='1,299.00')",
    ),
    (
        "09:21",
        "checkout",
        "ERROR",
        "POST /checkout 500 decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>] "
        "in services/checkout/amounts.py parse_amount(text='2,450.50')",
    ),
    ("09:30", "checkout", "INFO", "POST /checkout 200 amount='120.00'"),
    (
        "09:42",
        "checkout",
        "ERROR",
        "POST /checkout 500 decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>] "
        "in services/checkout/amounts.py parse_amount(text='10,000')",
    ),
    ("09:44", "search", "INFO", "GET /search?q=chair 200 in 91ms"),
]
HOURS = ["06:00", "07:00", "08:00", "09:00", "10:00", "11:00"]
METRICS = {
    ("http_error_rate", "checkout"): [0.1, 0.1, 0.2, 6.9, 7.8, 7.4],
    ("http_error_rate", "search"): [0.2, 0.1, 0.2, 0.2, 0.1, 0.2],
    ("latency_p95_ms", "checkout"): [180, 175, 182, 190, 188, 185],
    ("latency_p95_ms", "search"): [310, 305, 320, 410, 395, 330],
    ("requests_per_min", "checkout"): [40, 55, 80, 95, 90, 88],
    ("requests_per_min", "search"): [300, 420, 610, 700, 690, 650],
}


@server.tool()
async def list_services() -> str:
    """Services we collect logs and metrics for."""
    return json.dumps(["checkout", "search"])


@server.tool()
async def query_logs(service: str = "", level: str = "", contains: str = "", limit: int = 20) -> str:
    """Log lines from today, oldest first. Filter by service, level (INFO, WARN, ERROR) or text."""
    rows = [
        {"time": t, "service": s, "level": lv, "message": m}
        for t, s, lv, m in LOGS
        if (not service or s == service) and (not level or lv == level.upper()) and contains in m
    ]
    return json.dumps(rows[: max(1, limit)])


@server.tool()
async def query_metrics(metric: str, service: str = "") -> str:
    """Hourly values for today. Metrics: http_error_rate (% of requests), latency_p95_ms, requests_per_min."""
    series = {s: v for (m, s), v in METRICS.items() if m == metric and (not service or s == service)}
    if not series:  # returned, not raised: the SDK hides exception text from the client
        return f"No data for metric {metric!r}. Known: http_error_rate, latency_p95_ms, requests_per_min."
    return json.dumps({s: dict(zip(HOURS, v, strict=True)) for s, v in series.items()})


@server.tool()
async def silence_alert(alert: str, minutes: int = 60) -> str:
    """Silence an alert. A write action the agent must not get."""
    return f"silenced {alert} for {minutes} minutes"


if __name__ == "__main__":
    server.run()
