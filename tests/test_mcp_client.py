import sys
from pathlib import Path

import pytest

from localagents.mcp_client import McpClient, McpError

FAKE = [sys.executable, str(Path(__file__).parent / "fake_mcp_server.py")]


@pytest.fixture
def client(tmp_path):
    with McpClient(FAKE, env={}, cwd=tmp_path, timeout=5) as c:
        yield c


def test_handshake_and_paged_tool_list(client):
    assert client.server_info == {"name": "fake"}
    assert [t["name"] for t in client.list_tools()] == ["echo", "fail"]


def test_call_skips_server_requests(client):
    assert client.call_tool("echo", {"repo_path": "/r", "text": "hi"}) == ("/r|hi", False)
    assert client.call_tool("fail", {"repo_path": "/r"}) == ("boom", True)


def test_errors(client):
    with pytest.raises(McpError, match="no unknown"):
        client.request("unknown")
    with pytest.raises(McpError, match="exited"):
        client.request("crash")
    with pytest.raises(McpError):
        client.request("tools/list")


def test_close_stops_server(tmp_path):
    c = McpClient(FAKE, env={}, cwd=tmp_path, timeout=5)
    c.close()
    assert c.proc.poll() is not None
