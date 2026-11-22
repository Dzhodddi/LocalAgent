"""A small synchronous MCP client over stdio (JSON-RPC, one message per line).

Enough to start a server, list its tools and call them from the agent loop's thread.
"""

import itertools
import json
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any, Self

PROTOCOL_VERSION = "2025-06-18"


class McpError(Exception):
    """The server failed, timed out or answered with an error."""


class McpClient:
    def __init__(self, cmd: list[str], env: dict[str, str], cwd: Path, timeout: float = 60.0):
        self.timeout = timeout
        self._ids = itertools.count(1)
        self._lines: queue.Queue[str | None] = queue.Queue()
        self.proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )  # fmt: skip
        threading.Thread(target=self._read, daemon=True).start()
        self.server_info = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "localagents", "version": "0"},
            },
        ).get("serverInfo", {})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _read(self) -> None:
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)  # server exited

    def _send(self, message: dict[str, Any]) -> None:
        try:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError) as e:
            raise McpError("The MCP server is not running.") from e

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = next(self._ids)
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        while True:
            try:
                line = self._lines.get(timeout=self.timeout)
            except queue.Empty as e:
                raise McpError(f"MCP server did not answer {method} within {self.timeout:g}s.") from e
            if line is None:
                raise McpError(f"MCP server exited during {method}.")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # stray output
            if "method" in message and "id" in message:  # a request from the server: we support none
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {"code": -32601, "message": "not supported"},
                    }
                )
                continue
            if message.get("id") != request_id:
                continue  # notification or a late reply
            if "error" in message:
                raise McpError(f"{method} failed: {message['error'].get('message', message['error'])}")
            return message.get("result", {})

    def list_tools(self) -> list[dict[str, Any]]:
        tools, cursor = [], None
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += result.get("tools", [])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Returns (text, is_error)."""
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        text = "\n".join(
            part.get("text", "") for part in result.get("content", []) if part.get("type") == "text"
        )
        return text.strip(), bool(result.get("isError"))

    def close(self) -> None:
        try:
            self.proc.stdin.close()  # closing stdin asks the server to exit
        except BrokenPipeError:
            pass  # it already died
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
