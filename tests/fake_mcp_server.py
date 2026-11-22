"""A tiny MCP server for client tests: one tool `echo`, plus `fail` and a server->client request."""

import json
import sys

for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg or "method" not in msg:  # notifications and replies to our requests
        continue
    method, reply = msg["method"], None
    if method == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {}}), flush=True)
        reply = {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake"},
        }
    elif method == "tools/list" and not msg["params"].get("cursor"):
        reply = {
            "tools": [
                {
                    "name": "echo",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"repo_path": {"type": "string"}, "text": {"type": "string"}},
                        "required": ["repo_path", "text"],
                    },
                }
            ],
            "nextCursor": "page2",
        }
    elif method == "tools/list":
        reply = {
            "tools": [
                {
                    "name": "fail",
                    "description": "always fails",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"repo_path": {"type": "string"}},
                        "required": ["repo_path"],
                    },
                }
            ]
        }
    elif method == "tools/call":
        args = msg["params"]["arguments"]
        if msg["params"]["name"] == "echo":
            print(json.dumps({"jsonrpc": "2.0", "id": 999, "method": "roots/list"}), flush=True)
            reply = {"content": [{"type": "text", "text": f"{args['repo_path']}|{args['text']}"}]}
        else:
            reply = {"content": [{"type": "text", "text": "boom"}], "isError": True}
    if method == "crash":
        sys.exit(1)
    if reply is None:
        print(
            json.dumps(
                {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"no {method}"}}
            ),
            flush=True,
        )
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": reply}), flush=True)
