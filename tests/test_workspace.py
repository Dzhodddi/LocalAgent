import pytest

from localagents.workspace import WorkspaceError


def test_resolves_relative_path(ws):
    assert ws.resolve("src/app.py") == ws.root / "src" / "app.py"


def test_inner_dotdot_that_stays_inside_is_allowed(ws):
    assert ws.resolve("src/../app.py") == ws.root / "app.py"


@pytest.mark.parametrize("path", ["../outside.txt", "src/../../outside.txt", "/etc/passwd", "", "  "])
def test_rejects_paths_outside_or_empty(ws, path):
    with pytest.raises(WorkspaceError):
        ws.resolve(path)


def test_rejects_symlink_pointing_outside(ws, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (ws.root / "link").symlink_to(outside)
    with pytest.raises(WorkspaceError):
        ws.resolve("link/secret.txt")


def test_relative(ws):
    assert ws.relative(ws.root / "a" / "b.py") == "a/b.py"
    assert ws.relative(ws.root) == "."


def test_snapshot_and_changes(ws):
    from localagents.workspace import changes

    (ws.root / "keep.py").write_text("same")
    (ws.root / "edit.py").write_text("old")
    (ws.root / "gone.py").write_text("bye")
    (ws.root / ".venv").mkdir()
    (ws.root / ".venv/ignored.py").write_text("x")
    before = ws.snapshot()
    assert ".venv/ignored.py" not in before

    (ws.root / "edit.py").write_text("new")
    (ws.root / "gone.py").unlink()
    (ws.root / "sub").mkdir()
    (ws.root / "sub/new.py").write_text("hi")
    assert changes(before, ws.snapshot()) == {
        "added": ["sub/new.py"],
        "modified": ["edit.py"],
        "deleted": ["gone.py"],
    }
