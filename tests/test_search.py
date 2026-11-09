import pytest

from localagents.tools import ToolError
from localagents.tools import search as search_module
from localagents.tools.search import search
from localagents.workspace import WorkspaceError


@pytest.fixture
def project(ws):
    (ws.root / "src").mkdir()
    (ws.root / "src/app.py").write_text("def main():\n    return helper()\n")
    (ws.root / "src/util.py").write_text("def helper():\n    return 1\n")
    return ws


def test_finds_matches_with_line_numbers(project):
    assert search(project, "helper") == "src/app.py:2:    return helper()\nsrc/util.py:1:def helper():"


def test_limits_to_path(project):
    assert search(project, "def", path="src/util.py") == "src/util.py:1:def helper():"


def test_no_matches(project):
    assert "No matches" in search(project, "nothing_here")


def test_max_results(project):
    out = search(project, "e", max_results=1)
    assert len(out.splitlines()) == 2
    assert "more matches" in out


def test_long_lines_are_cut(ws, monkeypatch):
    monkeypatch.setattr(search_module, "MAX_LINE_CHARS", 10)
    (ws.root / "a.txt").write_text("x" * 50)
    assert search(ws, "x").endswith("...")


def test_bad_regex_and_paths(project):
    with pytest.raises(ToolError, match="Search failed"):
        search(project, "(unclosed")
    with pytest.raises(ToolError, match="not found"):
        search(project, "x", path="missing")
    with pytest.raises(WorkspaceError):
        search(project, "x", path="..")
