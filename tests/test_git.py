import dataclasses
import shutil
import subprocess

import pytest

from localagents.tools import ToolError, build_tools
from localagents.tools import git as git_tools
from localagents.tools.git import (
    git_commit,
    git_create_branch,
    git_diff,
    git_log,
    git_restore,
    git_status,
)
from localagents.workspace import WorkspaceError

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not installed")


def sh(ws, *args):
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=t@t", *args],
        cwd=ws.root, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip


@pytest.fixture(params=[True, False], ids=["sandbox", "plain"])
def settings(request, settings):
    if request.param and not shutil.which("bwrap"):
        pytest.skip("bubblewrap not installed")
    return dataclasses.replace(settings, sandbox=request.param)


@pytest.fixture
def repo(ws):
    sh(ws, "init", "-q", "-b", "main")
    (ws.root / "app.py").write_text("x = 1\n")
    (ws.root / "lib.py").write_text("y = 1\n")
    sh(ws, "add", ".")
    sh(ws, "commit", "-q", "-m", "initial")
    return ws


def test_git_tools_only_in_repos(ws, settings):
    assert "git_status" not in build_tools(ws, settings)
    sh(ws, "init", "-q")
    names = list(build_tools(ws, settings))
    assert {"git_status", "git_diff", "git_log", "git_commit", "git_restore", "git_create_branch"} <= set(
        names
    )
    assert names[-1] == "finish"


def test_status(repo, settings):
    assert git_status(repo, settings).endswith("Working tree clean.")
    (repo.root / "app.py").write_text("x = 2\n")
    (repo.root / "new.py").write_text("")
    out = git_status(repo, settings)
    assert "## main" in out and " M app.py" in out and "?? new.py" in out


def test_diff(repo, settings):
    assert git_diff(repo, settings) == "No changes."
    (repo.root / "app.py").write_text("x = 2\n")
    (repo.root / "lib.py").write_text("y = 2\n")
    out = git_diff(repo, settings, path="app.py")
    assert "-x = 1" in out and "+x = 2" in out
    assert "lib.py" not in out


def test_diff_staged(repo, settings):
    (repo.root / "app.py").write_text("x = 2\n")
    assert git_diff(repo, settings, staged=True) == "No changes."
    sh(repo, "add", "app.py")
    assert "+x = 2" in git_diff(repo, settings, staged=True)


def test_long_diff_is_cut(repo, settings):
    small = dataclasses.replace(settings, max_output_chars=50)
    (repo.root / "app.py").write_text("\n".join(f"line {i}" for i in range(100)))
    assert "chars cut" in git_diff(repo, small)


def test_log(repo, settings):
    out = git_log(repo, settings)
    assert out.endswith("Test: initial")
    with pytest.raises(ToolError):
        git_log(repo, settings, count=0)


def test_log_without_commits(ws, settings):
    sh(ws, "init", "-q")
    assert git_log(ws, settings) == "No commits yet."


def test_commit_all_with_agent_as_author(repo, settings):
    (repo.root / "app.py").write_text("x = 2\n")
    (repo.root / "new.py").write_text("z = 1\n")
    out = git_commit(repo, settings, "Change x")
    assert out.startswith("Committed") and "Change x" in out
    assert "new.py" in out
    author = sh(repo, "log", "-1", "--format=%an|%cn")
    assert author.startswith(f"LocalAgents ({settings.model})|")
    assert git_status(repo, settings).endswith("Working tree clean.")


def test_commit_only_given_paths(repo, settings):
    (repo.root / "app.py").write_text("x = 2\n")
    (repo.root / "lib.py").write_text("y = 2\n")
    git_commit(repo, settings, "Only app", paths=["app.py"])
    assert " M lib.py" in git_status(repo, settings)


def test_commit_errors(repo, settings):
    with pytest.raises(ToolError, match="Nothing to commit"):
        git_commit(repo, settings, "nothing")
    with pytest.raises(ToolError, match="empty"):
        git_commit(repo, settings, "  ")
    with pytest.raises(WorkspaceError):
        git_commit(repo, settings, "escape", paths=["../x"])


def test_restore(repo, settings):
    (repo.root / "app.py").write_text("broken(\n")
    assert git_restore(repo, settings, "app.py") == "Restored app.py to the last commit."
    assert (repo.root / "app.py").read_text() == "x = 1\n"


def test_restore_refuses_untracked_and_whole_project(repo, settings):
    (repo.root / "new.py").write_text("")
    with pytest.raises(ToolError, match="not tracked"):
        git_restore(repo, settings, "new.py")
    with pytest.raises(ToolError, match="whole project"):
        git_restore(repo, settings, ".")


def test_create_branch(repo, settings):
    assert git_create_branch(repo, settings, "fix/thing") == "Created and switched to branch fix/thing."
    assert "## fix/thing" in git_status(repo, settings)
    for bad in ["-x", "a b", "../x", "x;rm"]:
        with pytest.raises(ToolError):
            git_create_branch(repo, settings, bad)


def test_file_tools_cannot_touch_dot_git(repo, settings):
    tools = build_tools(repo, settings)
    for call in [
        lambda: tools["read_file"].call({"path": ".git/config"}),
        lambda: tools["write_file"].call({"path": ".git/hooks/pre-commit", "content": "#!/bin/sh\n"}),
        lambda: tools["list_files"].call({"pattern": ".git/*"}),
    ]:
        try:
            out = call()
        except ToolError as e:
            assert ".git" in str(e)
        else:
            assert out.startswith("No files match")  # list_files skips .git
    assert not (repo.root / ".git/hooks/pre-commit").exists()


def test_malicious_git_config_stays_in_sandbox(repo, settings, tmp_path_factory):
    """The agent can edit .git/config with run_command; git must not run that config outside the sandbox."""
    if not settings.sandbox:
        pytest.skip("sandbox only")
    outside = tmp_path_factory.mktemp("outside")
    sh(repo, "config", "core.fsmonitor", f"touch {outside}/pwned; false")
    (repo.root / "app.py").write_text("x = 2\n")
    git_tools.git_status(repo, settings)
    assert not (outside / "pwned").exists()
