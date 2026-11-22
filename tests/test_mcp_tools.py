import json
import sys
from contextlib import ExitStack
from pathlib import Path

import pytest

from localagents.agent import run_agent
from localagents.mcp_tools import McpServerSpec, _compact, load_mcp_config, mcp_tools
from localagents.tools import ToolError
from tests.fakes import FakeModel
from tests.test_agent import call

FAKE_SERVER = Path(__file__).parent / "fake_mcp_server.py"


def spec(tmp_path, tools=("echo",), **kw):
    return McpServerSpec("fake", ("${PYTHON}", str(FAKE_SERVER)), tuple(tools), tmp_path, **kw)


def write_config(tmp_path, servers):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": servers}))
    return path


def test_load_config(tmp_path):
    path = write_config(
        tmp_path,
        {"logs": {"command": "srv", "args": ["--ro"], "tools": ["query"], "env": {"TOKEN": "${T}"}}},
    )
    [s] = load_mcp_config(path)
    assert (s.name, s.command, s.tools, s.env, s.config_dir) == (
        "logs", ("srv", "--ro"), ("query",), {"TOKEN": "${T}"}, tmp_path.resolve()
    )  # fmt: skip


def test_config_needs_an_allowlist(tmp_path):
    with pytest.raises(ValueError, match="allowlist"):
        load_mcp_config(write_config(tmp_path, {"logs": {"command": "srv"}}))
    with pytest.raises(ValueError, match="Cannot read"):
        load_mcp_config(tmp_path / "missing.json")


def test_only_allowed_tools_reach_the_model(tmp_path, settings):
    with ExitStack() as stack:
        [echo] = mcp_tools([spec(tmp_path, descriptions={"echo": "Say it back."})], settings, stack)
        assert (echo.name, echo.description) == ("echo", "Say it back.")
        assert echo.call({"repo_path": "r", "text": "hi"}) == "r|hi"


def test_unknown_allowed_tool_lists_what_exists(tmp_path, settings):
    with ExitStack() as stack, pytest.raises(ToolError, match="no tool delete_all. It offers: echo, fail"):
        mcp_tools([spec(tmp_path, tools=("echo", "delete_all"))], settings, stack)


def test_tool_errors_and_missing_env(tmp_path, settings, monkeypatch):
    with ExitStack() as stack:
        [fail] = mcp_tools([spec(tmp_path, tools=("fail",))], settings, stack)
        with pytest.raises(ToolError, match="boom"):
            fail.call({"repo_path": "r"})
    monkeypatch.delenv("LOCALAGENTS_TEST_TOKEN", raising=False)
    with ExitStack() as stack, pytest.raises(ToolError, match="LOCALAGENTS_TEST_TOKEN is not set"):
        mcp_tools([spec(tmp_path, env={"TOKEN": "${LOCALAGENTS_TEST_TOKEN}"})], settings, stack)


def test_compact_json_and_cut(settings):
    assert _compact('{\n  "a": [1, 2],\n  "b": "x"\n}', settings) == '{"a":[1,2],"b":"x"}'
    assert _compact("plain text", settings) == "plain text"
    long = _compact("x" * (settings.max_output_chars + 10), settings)
    assert long.endswith("Narrow the query: a shorter time range, a filter or a lower limit.")


def test_agent_gets_mcp_tools_before_finish(ws, settings, tmp_path):
    model = FakeModel([call("echo", repo_path="r", text="hi"), call("finish", summary="ok")])
    result = run_agent("t", ws, model, settings, mcp_servers=[spec(tmp_path)])
    assert result.status == "finished"
    assert model.calls[1][-1] == {"role": "tool", "tool_name": "echo", "content": "r|hi"}


def test_agent_reports_servers_that_do_not_start(ws, settings, tmp_path):
    broken = McpServerSpec("broken", (sys.executable, "-c", "pass"), ("x",), tmp_path)
    result = run_agent("t", ws, FakeModel([]), settings, mcp_servers=[broken])
    assert result.status == "error" and "did not start" in result.summary


def test_number_and_object_arrays_are_coerced():
    from localagents.tools import _coerce

    assert _coerce("t", "n", "1.5", "number") == 1.5
    assert _coerce("t", "n", 3, "number") == 3
    assert _coerce("t", "f", [{"k": 1}], "array", {"type": "object"}) == [{"k": 1}]
    with pytest.raises(ToolError):
        _coerce("t", "n", "abc", "number")


def test_run_variables_win_over_environment(tmp_path, monkeypatch):
    from localagents.mcp_tools import _expand

    monkeypatch.setenv("EVAL_RUN_ID", "from-env")
    s = spec(tmp_path, variables={"EVAL_RUN_ID": "run-42"})
    assert _expand("p=${EVAL_RUN_ID} d=${CONFIG_DIR}", s) == f"p=run-42 d={tmp_path}"
