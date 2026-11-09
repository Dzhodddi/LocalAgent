"""git_status, git_diff, git_log, git_commit, git_restore, git_create_branch.

Git runs inside the same bubblewrap sandbox as run_command: the agent can edit .git/config
through the shell, and settings such as core.fsmonitor run commands, so git must never run
with more access than the agent already has. No push, pull, reset or rebase: nothing that
talks to the network or rewrites history.
"""

import functools
import re
import subprocess

from localagents.config import Settings
from localagents.tools import ToolError
from localagents.tools.shell import command_env, sandbox_args
from localagents.workspace import Workspace

AGENT_NAME = "LocalAgents"
AGENT_EMAIL = "localagents@localhost"
GIT_TIMEOUT = 30
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def is_repo(ws: Workspace) -> bool:
    return (ws.root / ".git").exists()


@functools.cache
def _host_identity() -> tuple[str, str]:
    """Your global git identity, read once outside the workspace so repo config cannot affect it."""

    def get(key: str) -> str:
        proc = subprocess.run(
            ["git", "config", "--global", key], cwd="/", capture_output=True, text=True, check=False
        )
        return proc.stdout.strip()

    return get("user.name") or AGENT_NAME, get("user.email") or AGENT_EMAIL


def _git(ws: Workspace, settings: Settings, *args: str) -> tuple[int, str]:
    name, email = _host_identity()
    env = command_env(ws) | {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "GIT_CONFIG_NOSYSTEM": "1",
        # The agent authors its commits; you are the committer.
        "GIT_AUTHOR_NAME": f"{AGENT_NAME} ({settings.model})",
        "GIT_AUTHOR_EMAIL": AGENT_EMAIL,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }
    prefix = sandbox_args(ws) if settings.sandbox else []
    try:
        proc = subprocess.run(
            [*prefix, "git", "--no-pager", *args],
            cwd=ws.root, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=GIT_TIMEOUT, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"git {args[0]} timed out.") from e
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _run(ws: Workspace, settings: Settings, *args: str) -> str:
    code, output = _git(ws, settings, *args)
    if code != 0:
        raise ToolError(f"git {args[0]} failed: {output or f'exit code {code}'}")
    return output


def _cut(text: str, settings: Settings) -> str:
    limit = settings.max_output_chars
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... ({len(text) - limit} chars cut). Pass a path to see one file."


def _paths(ws: Workspace, paths: list[str] | None) -> list[str]:
    return [ws.relative(ws.resolve(p)) for p in paths or []]


def git_status(ws: Workspace, settings: Settings) -> str:
    """Current branch and changed files."""
    out = _run(ws, settings, "status", "--short", "--branch")
    return out if "\n" in out else out + "\nWorking tree clean."


def git_diff(ws: Workspace, settings: Settings, path: str | None = None, staged: bool = False) -> str:
    """Uncommitted changes (or staged ones), optionally for one path."""
    args = ["diff", "--stat", "--patch"]
    if staged:
        args.append("--cached")
    args += ["--", *_paths(ws, [path] if path else None)]
    out = _run(ws, settings, *args)
    return _cut(out, settings) if out else "No changes."


def git_log(ws: Workspace, settings: Settings, count: int = 10, path: str | None = None) -> str:
    """Recent commits, newest first."""
    if not 1 <= count <= 100:
        raise ToolError("count must be between 1 and 100.")
    args = [
        "log",
        f"-{count}",
        "--format=%h %ad %an: %s",
        "--date=short",
        "--",
        *_paths(ws, [path] if path else None),
    ]
    code, out = _git(ws, settings, *args)
    if code != 0:
        if "does not have any commits" in out:
            return "No commits yet."
        raise ToolError(f"git log failed: {out}")
    return out or "No commits."


def git_commit(ws: Workspace, settings: Settings, message: str, paths: list[str] | None = None) -> str:
    """Stage the given paths (default: every change) and commit them."""
    if not message.strip():
        raise ToolError("Commit message is empty.")
    targets = _paths(ws, paths)
    _run(ws, settings, "add", "--all", "--", *(targets or ["."]))
    code, out = _git(ws, settings, "commit", "--message", message.strip())
    if code != 0:
        if "nothing to commit" in out or "no changes added" in out:
            raise ToolError("Nothing to commit: there are no changes in those paths.")
        raise ToolError(f"git commit failed: {out}")
    return _run(ws, settings, "show", "--stat", "--format=Committed %h: %s", "HEAD")


def git_restore(ws: Workspace, settings: Settings, path: str) -> str:
    """Throw away uncommitted changes to one file or folder (back to the last commit)."""
    target = _paths(ws, [path])[0]
    if target == ".":
        raise ToolError("Refusing to restore the whole project. Name a file or folder.")
    code, _ = _git(ws, settings, "ls-files", "--error-unmatch", "--", target)
    if code != 0:
        raise ToolError(f"{target} is not tracked by git, so there is no committed version to go back to.")
    _run(ws, settings, "restore", "--staged", "--worktree", "--source=HEAD", "--", target)
    return f"Restored {target} to the last commit."


def git_create_branch(ws: Workspace, settings: Settings, name: str) -> str:
    """Create a new branch from the current commit and switch to it. Uncommitted changes come along."""
    if not BRANCH_RE.match(name) or name.startswith(("-", "/")) or ".." in name:
        raise ToolError("Branch names may only use letters, digits, '.', '_', '-' and '/'.")
    _run(ws, settings, "switch", "--create", name)
    return f"Created and switched to branch {name}."
