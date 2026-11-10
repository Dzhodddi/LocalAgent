import pytest

from localagents.tools import ToolError, files
from localagents.tools.files import edit_file, list_files, read_file, write_file
from localagents.workspace import WorkspaceError


def make(ws, path, content):
    full = ws.root / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    return full


# read_file


def test_read_numbers_lines(ws):
    make(ws, "a.py", "x = 1\ny = 2\n")
    assert read_file(ws, "a.py") == "    1\tx = 1\n    2\ty = 2"


def test_read_line_range(ws):
    make(ws, "a.py", "one\ntwo\nthree\nfour\n")
    out = read_file(ws, "a.py", start=2, end=3)
    assert out.startswith("    2\ttwo\n    3\tthree")
    assert "showing lines 2-3 of 4" in out


def test_read_truncates_long_files(ws, monkeypatch):
    monkeypatch.setattr(files, "MAX_READ_LINES", 3)
    make(ws, "a.txt", "\n".join(str(i) for i in range(10)))
    out = read_file(ws, "a.txt")
    assert out.count("\t") == 3
    assert "showing lines 1-3 of 10" in out


def test_read_empty_file(ws):
    make(ws, "empty.txt", "")
    assert "empty" in read_file(ws, "empty.txt")


@pytest.mark.parametrize(("start", "end"), [(0, 2), (3, 1), (99, None)])
def test_read_bad_range(ws, start, end):
    make(ws, "a.py", "one\ntwo\n")
    with pytest.raises(ToolError):
        read_file(ws, "a.py", start=start, end=end)


def test_read_missing_directory_and_binary(ws):
    (ws.root / "dir").mkdir()
    (ws.root / "bin").write_bytes(b"\x00\x01\x02")
    for path in ["missing.py", "dir", "bin"]:
        with pytest.raises(ToolError):
            read_file(ws, path)


def test_read_outside_workspace(ws):
    with pytest.raises(WorkspaceError):
        read_file(ws, "../secret.txt")


# write_file


def test_write_creates_file_and_parents(ws):
    msg = write_file(ws, "pkg/sub/mod.py", "a\nb\n")
    assert (ws.root / "pkg/sub/mod.py").read_text() == "a\nb\n"
    assert msg == "Created pkg/sub/mod.py (2 lines)."


def test_write_overwrites(ws):
    make(ws, "a.py", "old\n")
    assert write_file(ws, "a.py", "new\n").startswith("Overwrote")
    assert (ws.root / "a.py").read_text() == "new\n"


def test_write_rejects_directory_and_outside(ws):
    (ws.root / "dir").mkdir()
    with pytest.raises(ToolError):
        write_file(ws, "dir", "x")
    with pytest.raises(WorkspaceError):
        write_file(ws, "../evil.py", "x")


# edit_file


def test_edit_replaces_unique_snippet(ws):
    make(ws, "a.py", "def f():\n    return 1\n")
    msg = edit_file(ws, "a.py", "    return 1", "    return 2")
    assert (ws.root / "a.py").read_text() == "def f():\n    return 2\n"
    assert (
        msg == "Edited a.py at line 2 (-1 +1 lines)\n@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 2"
    )


def test_edit_missing_snippet_changes_nothing(ws):
    original = "def f():\n    return 1\n"
    make(ws, "a.py", original)
    with pytest.raises(ToolError, match="not found"):
        edit_file(ws, "a.py", "return 1\n  ", "return 2")  # wrong whitespace
    assert (ws.root / "a.py").read_text() == original


def test_edit_ambiguous_snippet_changes_nothing(ws):
    original = "x = 1\nx = 1\n"
    make(ws, "a.py", original)
    with pytest.raises(ToolError, match="2 times"):
        edit_file(ws, "a.py", "x = 1", "x = 2")
    assert (ws.root / "a.py").read_text() == original


@pytest.mark.parametrize(("old", "new"), [("", "x"), ("same", "same")])
def test_edit_rejects_empty_or_noop(ws, old, new):
    make(ws, "a.py", "same\n")
    with pytest.raises(ToolError):
        edit_file(ws, "a.py", old, new)


def test_edit_can_delete(ws):
    make(ws, "a.py", "keep\ndrop\n")
    edit_file(ws, "a.py", "drop\n", "")
    assert (ws.root / "a.py").read_text() == "keep\n"


# list_files


def test_list_recursive_sorted_and_skips_junk(ws):
    for path in ["b.py", "src/a.py", ".git/config", ".venv/lib/x.py", "src/__pycache__/a.pyc"]:
        make(ws, path, "")
    assert list_files(ws) == "b.py\nsrc/a.py"


def test_list_pattern(ws):
    make(ws, "a.py", "")
    make(ws, "notes.md", "")
    make(ws, "src/b.py", "")
    assert list_files(ws, "**/*.py") == "a.py\nsrc/b.py"
    assert list_files(ws, "*.md") == "notes.md"


def test_list_no_matches(ws):
    assert "No files match" in list_files(ws, "*.rs")


def test_list_truncates(ws, monkeypatch):
    monkeypatch.setattr(files, "MAX_LIST_FILES", 2)
    for i in range(5):
        make(ws, f"f{i}.py", "")
    out = list_files(ws)
    assert out.splitlines()[:2] == ["f0.py", "f1.py"]
    assert "3 more" in out


@pytest.mark.parametrize("pattern", ["/etc/*", "../*", "src/../../*"])
def test_list_rejects_escaping_patterns(ws, pattern):
    with pytest.raises(ToolError):
        list_files(ws, pattern)


def test_list_skips_symlink_outside(ws, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.txt").write_text("s")
    (ws.root / "link").symlink_to(outside)
    make(ws, "a.py", "")
    assert list_files(ws) == "a.py"


# change reports


def test_edit_warns_when_a_function_disappears(ws):
    make(ws, "t.py", "def test_old():\n    assert 1\n")
    msg = edit_file(ws, "t.py", "def test_old():\n    assert 1", "def test_new():\n    assert 2")
    assert "-def test_old():" in msg
    assert "Warning: this removed test_old" in msg


def test_edit_that_keeps_the_anchor_has_no_warning(ws):
    make(ws, "t.py", "def test_old():\n    assert 1\n")
    msg = edit_file(ws, "t.py", "    assert 1", "    assert 1\n\n\ndef test_new():\n    assert 2")
    assert "(-0 +4 lines)" in msg
    assert "Warning" not in msg


def test_overwrite_reports_diff_and_lost_definitions(ws):
    make(ws, "a.py", "class A:\n    pass\n\n\nasync def run():\n    pass\n")
    msg = write_file(ws, "a.py", "class A:\n    pass\n")
    assert msg.startswith("Overwrote a.py (-4 +0 lines)")
    assert "Warning: this removed run" in msg


def test_long_diffs_are_cut(ws, monkeypatch):
    monkeypatch.setattr(files, "MAX_DIFF_LINES", 3)
    make(ws, "a.txt", "\n".join(f"line {i}" for i in range(20)))
    msg = write_file(ws, "a.txt", "")
    assert "more diff lines" in msg
    assert len(msg.splitlines()) == 5  # header, 3 diff lines, "... more"


def test_read_file_stops_at_char_budget(ws):
    from localagents.tools.files import MAX_READ_CHARS

    (ws.root / "big.py").write_text("".join(f"value_{i} = {'x' * 60}\n" for i in range(1000)))
    out = read_file(ws, "big.py")
    assert len(out) < MAX_READ_CHARS + 200
    assert out.splitlines()[-1].startswith("... showing lines 1-")
    assert "of 1000. Use start/end" in out
