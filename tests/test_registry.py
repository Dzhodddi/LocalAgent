import pytest

from localagents.tools import ToolError, build_tools


@pytest.fixture
def tools(ws, settings):
    return build_tools(ws, settings)


def test_registers_all_tools(tools):
    assert set(tools) == {
        "read_file",
        "write_file",
        "edit_file",
        "list_files",
        "search",
        "run_command",
        "finish",
    }


def test_schemas_are_valid_ollama_tools(tools):
    for name, tool in tools.items():
        schema = tool.schema()
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == name
        assert fn["description"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert set(params["required"]) <= set(params["properties"])
        for prop in params["properties"].values():
            assert prop["type"] in {"string", "integer", "boolean", "array"}
            assert prop["description"]


def test_tools_are_bound_to_workspace(ws, tools):
    tools["write_file"].call({"path": "src/a.py", "content": "x = 1\n"})
    assert (ws.root / "src/a.py").read_text() == "x = 1\n"
    assert tools["read_file"].call({"path": "src/a.py"}) == "    1\tx = 1"
    tools["edit_file"].call({"path": "src/a.py", "old": "x = 1", "new": "x = 2"})
    assert tools["list_files"].call({}) == "src/a.py"
    assert (ws.root / "src/a.py").read_text() == "x = 2\n"


def test_unknown_argument(tools):
    with pytest.raises(ToolError, match="unknown argument.*file_path"):
        tools["read_file"].call({"file_path": "a.py"})


def test_missing_argument(tools):
    with pytest.raises(ToolError, match="missing required.*content"):
        tools["write_file"].call({"path": "a.py"})


def test_null_counts_as_missing_or_omitted(ws, tools):
    (ws.root / "a.py").write_text("one\ntwo\n")
    with pytest.raises(ToolError, match="missing required"):
        tools["read_file"].call({"path": None})
    assert tools["read_file"].call({"path": "a.py", "start": None, "end": None}) == "    1\tone\n    2\ttwo"


def test_integer_strings_are_coerced(ws, tools):
    (ws.root / "a.py").write_text("one\ntwo\nthree\n")
    assert tools["read_file"].call({"path": "a.py", "start": "2", "end": "2"}).startswith("    2\ttwo")


@pytest.mark.parametrize("bad", ["two", 1.5, True])
def test_bad_integer(ws, tools, bad):
    (ws.root / "a.py").write_text("one\n")
    with pytest.raises(ToolError, match="must be an integer"):
        tools["read_file"].call({"path": "a.py", "start": bad})


def test_bad_string(tools):
    with pytest.raises(ToolError, match="must be a string"):
        tools["write_file"].call({"path": "a.py", "content": 42})


def test_workspace_error_becomes_tool_error(tools):
    with pytest.raises(ToolError, match="outside the project"):
        tools["read_file"].call({"path": "../secret.txt"})


def test_none_arguments_uses_defaults(tools):
    assert tools["list_files"].call(None) == "No files match **/*."


def test_empty_string_optional_is_omitted(ws, tools):
    (ws.root / "a.py").write_text("needle\n")
    assert tools["search"].call({"regex": "needle", "path": ""}) == "a.py:1:needle"


def test_boolean_and_array_coercion():
    from localagents.tools import _coerce

    assert _coerce("t", "b", "true", "boolean") is True
    assert _coerce("t", "b", False, "boolean") is False
    assert _coerce("t", "p", "a.py", "array") == ["a.py"]
    assert _coerce("t", "p", ["a.py", "b.py"], "array") == ["a.py", "b.py"]
    for bad, kind in [("yes", "boolean"), (1, "boolean"), ([1], "array"), (5, "array")]:
        with pytest.raises(ToolError):
            _coerce("t", "x", bad, kind)
