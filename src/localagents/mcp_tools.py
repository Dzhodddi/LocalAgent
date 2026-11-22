"""Tools from outside MCP servers, e.g. for reading logs and metrics.

Configured in a JSON file you control, never one from the project the agent works in (a
project file could start any command on your machine):

    {"servers": {"grafana": {
        "command": ["mcp-grafana"],
        "env": {"GRAFANA_URL": "http://localhost:3000", "GRAFANA_SERVICE_ACCOUNT_TOKEN": "${GRAFANA_TOKEN}"},
        "tools": ["query_loki_logs", "query_prometheus"],
        "descriptions": {"query_prometheus": "Run a PromQL query. ..."}
    }}}

- `tools` is required: only these tools reach the model. List read-only ones.
- `${VAR}` comes from your environment when the server starts, so tokens stay out of the
  file and out of eval results. `${CONFIG_DIR}` is the config file's folder and `${PYTHON}`
  the Python running LocalAgents.
- `descriptions` replaces a tool's description; long ones cost a small model context.

The servers run outside the sandbox (they need the network), from the config file's
folder, with only PATH, HOME, LANG and the configured `env`.
"""

import json
import os
import re
import sys
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from localagents.config import Settings
from localagents.mcp_client import McpClient, McpError
from localagents.tools import Tool, ToolError

DEFAULT_CONFIG = Path.home() / ".config" / "localagents" / "mcp.json"
MAX_DESCRIPTION_CHARS = 400
PASSED_ENV = ("PATH", "HOME", "LANG")
VAR_RE = re.compile(r"\$\{(\w+)\}")


@dataclass(frozen=True)
class McpServerSpec:
    name: str
    command: tuple[str, ...]
    tools: tuple[str, ...]  # allowlist: the only tools the model sees
    config_dir: Path
    env: dict[str, str] = field(default_factory=dict)  # values may hold ${VAR}
    descriptions: dict[str, str] = field(default_factory=dict)


def default_mcp_servers() -> list[McpServerSpec]:
    """Servers from ~/.config/localagents/mcp.json, or none."""
    return load_mcp_config(DEFAULT_CONFIG) if DEFAULT_CONFIG.is_file() else []


def load_mcp_config(path: Path) -> list[McpServerSpec]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Cannot read MCP config {path}: {e}") from e
    specs = []
    for name, server in data.get("servers", {}).items():
        command = server.get("command")
        if isinstance(command, str):
            command = [command]
        if not command or not server.get("tools"):
            raise ValueError(f"MCP server {name!r} in {path} needs `command` and a `tools` allowlist.")
        specs.append(
            McpServerSpec(
                name,
                (*command, *server.get("args", [])),
                tuple(server["tools"]),
                path.parent.resolve(),
                dict(server.get("env", {})),
                dict(server.get("descriptions", {})),
            )
        )
    return specs


def _expand(value: str, spec: McpServerSpec) -> str:
    def var(match: re.Match) -> str:
        key = match[1]
        if key == "CONFIG_DIR":
            return str(spec.config_dir)
        if key == "PYTHON":
            return sys.executable
        if key not in os.environ:
            raise ToolError(f"MCP server {spec.name}: environment variable {key} is not set.")
        return os.environ[key]

    return VAR_RE.sub(var, value)


def _compact(text: str, settings: Settings) -> str:
    """JSON without indentation (half the tokens), cut to max_output_chars with a hint to narrow."""
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))
    except json.JSONDecodeError:
        pass
    limit = settings.max_output_chars
    if len(text) > limit:
        text = (
            text[:limit] + f"\n... ({len(text) - limit} chars cut). Narrow the query: a shorter time range, "
            "a filter or a lower limit."
        )
    return text


def _parameters(schema: dict[str, Any]) -> dict[str, Any]:
    schema = {k: v for k, v in schema.items() if k != "$schema"}
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


def start_server(spec: McpServerSpec, settings: Settings, stack: ExitStack) -> list[Tool]:
    env = {k: os.environ[k] for k in PASSED_ENV if k in os.environ}
    env |= {k: _expand(v, spec) for k, v in spec.env.items()}
    command = [_expand(part, spec) for part in spec.command]
    try:
        client = stack.enter_context(McpClient(command, env=env, cwd=spec.config_dir))
        offered = {t["name"]: t for t in client.list_tools()}
    except (McpError, OSError) as e:
        raise ToolError(f"MCP server {spec.name} did not start: {e}") from e
    missing = [name for name in spec.tools if name not in offered]
    if missing:
        raise ToolError(
            f"MCP server {spec.name} has no tool {', '.join(missing)}. It offers: {', '.join(sorted(offered))}."
        )

    def call(name: str, **arguments: Any) -> str:
        try:
            text, is_error = client.call_tool(name, arguments)
        except McpError as e:
            raise ToolError(str(e)) from e
        if is_error:
            raise ToolError(text or f"{name} failed.")
        return _compact(text, settings) if text else "No results."

    tools = []
    for name in spec.tools:
        description = spec.descriptions.get(name) or offered[name].get("description") or name
        if len(description) > MAX_DESCRIPTION_CHARS:
            description = description[:MAX_DESCRIPTION_CHARS].rsplit(" ", 1)[0] + " ..."
        tools.append(
            Tool(
                name=name,
                description=description,
                parameters=_parameters(offered[name].get("inputSchema", {})),
                func=lambda _name=name, **kw: call(_name, **kw),
            )
        )
    return tools


def mcp_tools(specs: list[McpServerSpec], settings: Settings, stack: ExitStack) -> list[Tool]:
    """Start every server (closed with `stack`) and return its allowed tools."""
    return [tool for spec in specs for tool in start_server(spec, settings, stack)]
