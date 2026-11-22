"""Done checks: what must be true before the agent may finish.

The caller (Claude, the CLI user or the eval runner) knows how to verify the task, so it
passes the checks in; a small model should not have to work that out. When the model calls
finish, every check runs, and if one fails, finish is refused with the reason.
"""

from dataclasses import dataclass

from localagents.config import Settings
from localagents.tools import ToolError
from localagents.tools.git import _git, is_repo
from localagents.tools.shell import run_command
from localagents.workspace import SKIP_DIRS, Workspace

REPORT_LINES = 30  # tail of a failed command shown to the model


@dataclass(frozen=True)
class Checks:
    commands: tuple[str, ...] = ()  # each must exit 0, e.g. "python -m pytest -q"
    committed: bool = False  # no uncommitted or untracked changes
    pushed: bool = False  # the current branch is pushed to origin as it is now

    def __bool__(self) -> bool:
        return bool(self.commands or self.committed or self.pushed)

    def describe(self) -> str:
        """Told to the model with the task, so it knows what finish will check."""
        lines = [f"- `{cmd}` must succeed" for cmd in self.commands]
        if self.committed:
            lines.append("- every change must be committed (git status clean)")
        if self.pushed:
            lines.append("- the current branch must be pushed to origin with git_push")
        return "When you call finish, these checks run, and finish is refused until they pass:\n" + "\n".join(
            lines
        )


def _uncommitted(ws: Workspace, settings: Settings) -> list[str]:
    code, out = _git(ws, settings, "status", "--porcelain", "--untracked-files=all")
    if code != 0:
        return [f"git status failed: {out}"]
    return [
        line
        for line in out.splitlines()
        if line.strip() and not SKIP_DIRS & set(line[3:].strip('"').split("/"))
    ]


def _push_problem(ws: Workspace, settings: Settings) -> str | None:
    code, branch = _git(ws, settings, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0 or branch == "HEAD":
        return "you are not on a branch"
    _, head = _git(ws, settings, "rev-parse", "HEAD")
    code, pushed = _git(ws, settings, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}")
    if code != 0:
        return f"branch {branch} is not pushed to origin"
    if pushed != head:
        return f"origin/{branch} is behind your latest commit; push again"
    return None


def run_checks(ws: Workspace, settings: Settings, checks: Checks) -> list[str]:
    """Failed checks, each with its reason. Empty when everything passed."""
    failures = []
    for cmd in checks.commands:
        try:
            out = run_command(ws, settings, cmd)
        except ToolError as e:
            failures.append(f"`{cmd}` could not run: {e}")
            continue
        if not out.startswith("exit code 0"):
            tail = "\n".join(out.splitlines()[-REPORT_LINES:])
            failures.append(f"`{cmd}` failed:\n{tail}")
    if (checks.committed or checks.pushed) and not is_repo(ws):
        return [*failures, "this folder is not a git repository"]
    if checks.committed and (dirty := _uncommitted(ws, settings)):
        failures.append("uncommitted changes:\n" + "\n".join(dirty[:20]))
    if checks.pushed and (problem := _push_problem(ws, settings)):
        failures.append(problem)
    return failures
