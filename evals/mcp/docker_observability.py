"""MCP server for a Docker Compose project: service list, logs and Prometheus queries.

Read-only tools for the agent: list_services, service_logs, prometheus_query.
restart_service changes things and exists so an allowlist has something to leave out.

Environment:
  COMPOSE_PROJECT   only show containers of this Compose project (default: all)
  PROMETHEUS_URL    Prometheus base URL; default: the host port published by the project's
                    `prometheus` service
"""

import json
import math
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

from mcp.server.mcpserver import MCPServer

server = MCPServer("docker-observability")

PROJECT = os.environ.get("COMPOSE_PROJECT", "")
RECORD_START = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")  # a new log record, not a traceback line
MAX_LOG_LINES = 2000


def _docker(*args: str) -> str:
    proc = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=30, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"docker {args[0]} failed")
    return proc.stdout + proc.stderr


def _containers() -> list[dict]:
    args = ["ps", "-a", "--format", "{{json .}}"]
    if PROJECT:
        args += ["--filter", f"label=com.docker.compose.project={PROJECT}"]
    rows = [json.loads(line) for line in _docker(*args).splitlines() if line.strip()]
    for row in rows:
        labels = dict(item.split("=", 1) for item in row.get("Labels", "").split(",") if "=" in item)
        row["Service"] = labels.get("com.docker.compose.service", row["Names"])
    return rows


def _container_of(service: str) -> str:
    for row in _containers():
        if service in (row["Service"], row["Names"]):
            return row["ID"]
    names = ", ".join(sorted(r["Service"] for r in _containers()))
    raise ValueError(f"No service {service!r}. Services: {names}.")


def _prometheus_url() -> str:
    if url := os.environ.get("PROMETHEUS_URL"):
        return url.rstrip("/")
    port = _docker("port", _container_of("prometheus"), "9090").splitlines()[0].strip()
    return f"http://{port.replace('0.0.0.0', '127.0.0.1')}"


@server.tool()
def list_services() -> str:
    """Services (containers) in the project with their state, e.g. running or exited."""
    return json.dumps(
        [
            {"service": r["Service"], "state": r["State"], "status": r["Status"], "image": r["Image"]}
            for r in _containers()
        ]
    )


@server.tool()
def service_logs(service: str, since: str = "15m", contains: str = "", limit: int = 30) -> str:
    """Log records of a service, newest last. A record keeps its traceback lines.

    since: how far back, e.g. "10m" or "1h". contains: only records with this text
    (case-insensitive), e.g. "ERROR" or "Traceback". limit: at most this many records.
    """
    try:
        raw = _docker("logs", "--since", since, "--tail", str(MAX_LOG_LINES), _container_of(service))
    except (RuntimeError, ValueError) as e:
        return f"Error: {e}"
    records: list[str] = []
    for line in raw.splitlines():
        if RECORD_START.match(line) or not records:
            records.append(line)
        else:
            records[-1] += "\n" + line
    if contains:
        records = [r for r in records if contains.lower() in r.lower()]
    shown = records[-max(1, limit) :]
    header = f"{len(shown)} of {len(records)} matching records" if contains else f"last {len(shown)} records"
    return header + "\n" + "\n".join(shown) if shown else "No matching log records."


def _round(value: str) -> float:
    number = float(value)
    return number if math.isnan(number) else round(number, 4)


@server.tool()
def prometheus_query(query: str, minutes: int = 0) -> str:
    """Run a PromQL query. minutes=0: the current value; minutes>0: values over that many
    minutes (about 20 points). Example: sum by (route, status) (rate(http_requests_total[1m]))."""
    try:
        base = _prometheus_url()
        params = {"query": query}
        endpoint = "query"
        if minutes > 0:
            now = time.time()
            endpoint = "query_range"
            params |= {"start": now - minutes * 60, "end": now, "step": max(15, minutes * 3)}
        url = f"{base}/api/v1/{endpoint}?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.load(response)
    except Exception as e:  # noqa: BLE001 - every failure goes back to the model as text
        return f"Error: {getattr(e, 'reason', e)}"
    if data.get("status") != "success":
        return f"Error: {data.get('error', data)}"
    result = []
    for series in data["data"]["result"]:
        labels = {k: v for k, v in series["metric"].items() if k not in ("instance", "job")}
        if "values" in series:
            points = [[time.strftime("%H:%M:%S", time.localtime(t)), _round(v)] for t, v in series["values"]]
            result.append({"metric": labels, "values": points})
        else:
            result.append({"metric": labels, "value": _round(series["value"][1])})
    return json.dumps(result) if result else "No data. Check the metric name and labels."


@server.tool()
def restart_service(service: str) -> str:
    """Restart a service. Changes the running system."""
    _docker("restart", _container_of(service))
    return f"Restarted {service}."


if __name__ == "__main__":
    server.run()
