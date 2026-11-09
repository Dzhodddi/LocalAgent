import dataclasses
import shutil
import subprocess

import pytest

from localagents.tools import ToolError, build_tools
from localagents.tools import remote as remote_mod
from localagents.tools.remote import Remote, create_pull_request, git_push, pinned_remote

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not installed")


def sh(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=t@t", *args],
        cwd=cwd, capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip


@pytest.fixture(params=[True, False], ids=["sandbox", "plain"])
def settings(request, settings):
    if request.param and not shutil.which("bwrap"):
        pytest.skip("bubblewrap not installed")
    return dataclasses.replace(settings, sandbox=request.param)


@pytest.fixture
def origin(tmp_path_factory):
    path = tmp_path_factory.mktemp("remote") / "origin.git"
    sh(path.parent, "init", "-q", "--bare", "-b", "main", str(path))
    return path


@pytest.fixture
def repo(ws, origin):
    sh(ws.root, "init", "-q", "-b", "main")
    (ws.root / "app.py").write_text("x = 1\n")
    sh(ws.root, "add", ".")
    sh(ws.root, "commit", "-q", "-m", "initial")
    sh(ws.root, "remote", "add", "origin", str(origin))
    sh(ws.root, "push", "-q", "origin", "main")
    return ws


def commit_on_branch(ws, branch, content="x = 2\n"):
    sh(ws.root, "switch", "-q", "-c", branch)
    (ws.root / "app.py").write_text(content)
    sh(ws.root, "commit", "-qam", f"change on {branch}")
    return sh(ws.root, "rev-parse", "HEAD")


def remote_sha(origin, branch):
    return sh(origin, "rev-parse", f"refs/heads/{branch}")


def test_pinned_remote(repo, origin):
    assert pinned_remote(repo) == Remote("origin", str(origin))


def test_push_current_branch(repo, settings, origin):
    sha = commit_on_branch(repo, "fix/x")
    remote = pinned_remote(repo)
    assert git_push(repo, settings, remote) == f"Pushed fix/x ({sha[:7]}) to origin."
    assert remote_sha(origin, "fix/x") == sha
    assert sh(repo.root, "rev-parse", "refs/remotes/origin/fix/x") == sha  # git_status can see it
    assert "already up to date" in git_push(repo, settings, remote)


def test_push_named_branch_from_elsewhere(repo, settings, origin):
    sha = commit_on_branch(repo, "feature")
    sh(repo.root, "switch", "-q", "main")
    git_push(repo, settings, pinned_remote(repo), branch="feature")
    assert remote_sha(origin, "feature") == sha


def test_protected_and_missing_branches(repo, settings, origin):
    remote = pinned_remote(repo)
    with pytest.raises(ToolError, match="not allowed"):
        git_push(repo, settings, remote)  # on main
    with pytest.raises(ToolError, match="no local branch"):
        git_push(repo, settings, remote, branch="nope")
    with pytest.raises(ToolError, match="Invalid branch"):
        git_push(repo, settings, remote, branch="-f")


def test_no_force_push(repo, settings, origin, tmp_path_factory):
    commit_on_branch(repo, "fix/x")
    remote = pinned_remote(repo)
    git_push(repo, settings, remote)
    # Someone else adds a commit to the remote branch.
    other = tmp_path_factory.mktemp("other") / "clone"
    sh(other.parent, "clone", "-q", "-b", "fix/x", str(origin), str(other))
    (other / "app.py").write_text("x = 99\n")
    sh(other, "commit", "-qam", "theirs")
    sh(other, "push", "-q", "origin", "fix/x")
    theirs = remote_sha(origin, "fix/x")
    # Our diverged commit must be rejected, not forced.
    (repo.root / "app.py").write_text("x = 3\n")
    sh(repo.root, "commit", "-qam", "ours")
    with pytest.raises(ToolError, match="rejected"):
        git_push(repo, settings, remote)
    assert remote_sha(origin, "fix/x") == theirs


def test_remote_is_pinned_at_start(repo, settings, origin, tmp_path_factory):
    evil = tmp_path_factory.mktemp("evil") / "evil.git"
    sh(evil.parent, "init", "-q", "--bare", str(evil))
    tools = build_tools(repo, settings)  # run starts: origin is pinned here
    sh(repo.root, "remote", "set-url", "origin", str(evil))  # the agent redirects origin
    commit_on_branch(repo, "fix/x")
    tools["git_push"].call({})
    assert remote_sha(origin, "fix/x")
    assert sh(evil, "for-each-ref") == ""


def test_hooks_and_config_never_run(repo, settings, tmp_path_factory):
    """A pre-push hook or sshCommand planted in .git must not run: the push uses a clean repository."""
    outside = tmp_path_factory.mktemp("outside")
    hook = repo.root / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\ntouch {outside}/hook-ran\n")
    hook.chmod(0o755)
    sh(repo.root, "config", "core.sshCommand", f"touch {outside}/ssh-ran; false")
    commit_on_branch(repo, "fix/x")
    git_push(repo, settings, pinned_remote(repo))
    assert list(outside.iterdir()) == []


def test_registry(repo, settings, monkeypatch):
    names = build_tools(repo, settings)
    assert "git_push" in names and "create_pull_request" not in names  # local remote: no PRs
    sh(repo.root, "remote", "set-url", "origin", "git@github.com:me/proj.git")
    monkeypatch.setattr(remote_mod, "gh_available", lambda: True)
    assert "create_pull_request" in build_tools(repo, settings)
    monkeypatch.setattr(remote_mod, "gh_available", lambda: False)
    assert "create_pull_request" not in build_tools(repo, settings)


def test_no_remote_no_push(ws, settings):
    sh(ws.root, "init", "-q")
    assert "git_push" not in build_tools(ws, settings)


@pytest.mark.parametrize(
    ("url", "repo", "local"),
    [
        ("git@github.com:me/proj.git", "me/proj", None),
        ("https://github.com/me/proj", "me/proj", None),
        ("https://gitlab.com/me/proj.git", None, None),
        ("/srv/git/proj.git", None, "/srv/git/proj.git"),
        ("file:///srv/git/proj.git", None, "/srv/git/proj.git"),
    ],
)
def test_remote_parsing(url, repo, local):
    remote = Remote("origin", url)
    assert remote.github_repo == repo
    assert (str(remote.local_path) if remote.local_path else None) == local


def test_create_pull_request(repo, settings, monkeypatch):
    commit_on_branch(repo, "fix/x")
    calls = []
    monkeypatch.setattr(
        remote_mod, "_gh", lambda *a: calls.append(a) or (0, "https://github.com/me/proj/pull/7")
    )
    remote = Remote("origin", "git@github.com:me/proj.git")
    out = create_pull_request(repo, settings, remote, "Fix x", "Body", "main")
    assert out == "Opened pull request: https://github.com/me/proj/pull/7"
    assert calls == [
        (
            "pr",
            "create",
            "--repo",
            "me/proj",
            "--head",
            "fix/x",
            "--base",
            "main",
            "--title",
            "Fix x",
            "--body",
            "Body",
        )
    ]


def test_create_pull_request_errors(repo, settings, monkeypatch):
    github = Remote("origin", "git@github.com:me/proj.git")
    with pytest.raises(ToolError, match="feature branch"):
        create_pull_request(repo, settings, github, "t")  # still on main
    commit_on_branch(repo, "fix/x")
    with pytest.raises(ToolError, match="not on GitHub"):
        create_pull_request(repo, settings, Remote("origin", "/srv/x.git"), "t")
    monkeypatch.setattr(
        remote_mod, "_gh", lambda *a: (1, "pull request create failed: No commits between main and fix/x")
    )
    with pytest.raises(ToolError, match="git_push first"):
        create_pull_request(repo, settings, github, "t")
