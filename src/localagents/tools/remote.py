"""git_push and create_pull_request: the only tools that talk to the outside world.

The agent controls the workspace's .git (hooks, config, remotes), so pushing never runs git
on it with network access. Instead:
  1. the remote URL is read once, before the agent starts, and pinned;
  2. inside the sandbox, the branch is packed into a git bundle;
  3. outside, a fresh bare repository with no agent-controlled config fetches the bundle
     and pushes it to the pinned URL with your normal credentials. Never with --force,
     never to a protected branch.
"""

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from localagents.config import Settings
from localagents.tools import ToolError
from localagents.tools.git import BRANCH_RE, _git, _run
from localagents.workspace import Workspace

PUSH_TIMEOUT = 120
GITHUB_RE = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


@dataclass(frozen=True)
class Remote:
    name: str
    url: str

    @property
    def github_repo(self) -> str | None:
        """owner/repo when the remote is on GitHub."""
        match = GITHUB_RE.search(self.url)
        return f"{match[1]}/{match[2]}" if match else None

    @property
    def local_path(self) -> Path | None:
        """The folder, when the remote is a repository on this machine (used by evals)."""
        if self.url.startswith("file://"):
            return Path(self.url.removeprefix("file://"))
        if "://" in self.url or ":" in self.url.split("/")[0]:  # a URL, or scp-style user@host:path
            return None
        return Path(self.url)


def pinned_remote(ws: Workspace, name: str = "origin") -> Remote | None:
    """Read the remote URL straight from .git/config (no includes, nothing executed)."""
    config = ws.root / ".git" / "config"
    if not config.is_file():
        return None
    proc = subprocess.run(
        ["git", "config", "--file", str(config), "--get", f"remote.{name}.url"],
        capture_output=True, text=True, check=False, cwd="/",
    )  # fmt: skip
    url = proc.stdout.strip()
    return Remote(name, url) if url else None


def _trusted_git(*args: str, cwd: Path, timeout: float = PUSH_TIMEOUT) -> tuple[int, str]:
    """git outside the sandbox, in a folder the agent never touched, with your credentials."""
    env = os.environ | {"GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"}
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"git {args[0]} timed out after {timeout:g}s.") from e
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _current_branch(ws: Workspace, settings: Settings) -> str:
    branch = _run(ws, settings, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        raise ToolError("Not on a branch (detached HEAD). Create or switch to a branch first.")
    return branch


def git_push(ws: Workspace, settings: Settings, remote: Remote, branch: str | None = None) -> str:
    """Push a branch to the pinned remote, creating it there if needed."""
    branch = branch or _current_branch(ws, settings)
    if not BRANCH_RE.match(branch) or branch.startswith("-") or ".." in branch:
        raise ToolError(f"Invalid branch name: {branch!r}.")
    if branch in settings.protected_branches:
        raise ToolError(
            f"Pushing to {branch} is not allowed. Create a branch with git_create_branch, "
            "commit there and push that branch."
        )
    code, sha = _git(ws, settings, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}")
    if code != 0:
        raise ToolError(f"There is no local branch {branch!r}. Commit on it before pushing.")

    bundle = ws.root / ".git" / "localagents-push.bundle"
    try:
        _run(ws, settings, "bundle", "create", "--quiet", str(bundle), f"refs/heads/{branch}")
        with tempfile.TemporaryDirectory(prefix="localagents-push-") as tmp:
            clean = Path(tmp)
            _trusted_git("init", "--quiet", "--bare", str(clean), cwd=clean)
            code, out = _trusted_git(
                "fetch",
                "--quiet",
                "--no-tags",
                str(bundle),
                f"refs/heads/{branch}:refs/heads/{branch}",
                cwd=clean,
            )
            if code != 0:
                raise ToolError(f"Could not read the branch for pushing: {out}")
            code, fetched = _trusted_git("rev-parse", f"refs/heads/{branch}", cwd=clean)
            if fetched != sha:
                raise ToolError("The packed branch does not match the local branch; try again.")
            code, out = _trusted_git(
                "push", "--porcelain", remote.url, f"refs/heads/{branch}:refs/heads/{branch}", cwd=clean
            )
    finally:
        bundle.unlink(missing_ok=True)

    if code != 0:
        if "non-fast-forward" in out or "rejected" in out or "fetch first" in out:
            raise ToolError(
                f"Push of {branch} was rejected: the remote branch has commits you don't have. "
                "Force pushing is not allowed; push to a new branch name instead."
            )
        raise ToolError(f"git push failed: {out}")
    # Let git_status/git_log in the workspace see the remote branch.
    _git(ws, settings, "update-ref", f"refs/remotes/{remote.name}/{branch}", sha)
    up_to_date = "[up to date]" in out
    return f"Pushed {branch} ({sha[:7]}) to {remote.name}." + (
        " It was already up to date." if up_to_date else ""
    )


def _gh(*args: str, timeout: float = 60) -> tuple[int, str]:
    """gh outside the sandbox, from an empty folder so the workspace cannot influence it."""
    with tempfile.TemporaryDirectory(prefix="localagents-gh-") as tmp:
        env = os.environ | {"GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1"}
        try:
            proc = subprocess.run(
                ["gh", *args], cwd=tmp, env=env, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=timeout, check=False,
            )  # fmt: skip
        except subprocess.TimeoutExpired as e:
            raise ToolError(f"gh {args[0]} timed out.") from e
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def gh_available() -> bool:
    return shutil.which("gh") is not None


def create_pull_request(
    ws: Workspace, settings: Settings, remote: Remote, title: str, body: str = "", base: str = "main"
) -> str:
    """Open a GitHub pull request from the current (already pushed) branch."""
    repo = remote.github_repo
    if not repo:
        raise ToolError("The remote is not on GitHub, so pull requests are not available.")
    if not title.strip():
        raise ToolError("Pull request title is empty.")
    head = _current_branch(ws, settings)
    if head == base:
        raise ToolError(f"You are on {base}. Open pull requests from a feature branch.")
    if not BRANCH_RE.match(base):
        raise ToolError(f"Invalid base branch: {base!r}.")
    code, out = _gh(
        "pr",
        "create",
        "--repo",
        repo,
        "--head",
        head,
        "--base",
        base,
        "--title",
        title.strip(),
        "--body",
        body,
    )
    if code != 0:
        if "No commits between" in out or "must first push" in out or "not found" in out.lower():
            raise ToolError(f"Could not open the pull request: {out}. Push the branch with git_push first.")
        raise ToolError(f"gh pr create failed: {out}")
    return f"Opened pull request: {out.splitlines()[-1]}"
