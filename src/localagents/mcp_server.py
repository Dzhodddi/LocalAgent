"""MCP server exposing `run_local_agent(task, workdir)` to Claude Code.

Register it with:
    claude mcp add --scope user localagents -- uv run --project /path/to/LocalAgents localagents-mcp
"""

import asyncio
import dataclasses
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from localagents.agent import run_agent
from localagents.checks import Checks
from localagents.config import Settings
from localagents.llm import OllamaModel
from localagents.workspace import Workspace, changes

server = MCPServer("localagents", instructions="Delegate small coding tasks to a local Ollama model.")


def _run(task: str, workdir: str, model: str | None, max_steps: int | None, checks: Checks) -> str:
    root = Path(workdir).expanduser()
    if not root.is_absolute() or not root.is_dir():
        return f"workdir must be an absolute path to an existing folder, got {workdir!r}."
    if root.resolve() in (Path("/"), Path.home()):
        return "Refusing to run in / or the home folder. Point workdir at a project folder."

    overrides = {k: v for k, v in {"model": model, "max_steps": max_steps}.items() if v}
    settings = dataclasses.replace(Settings(), **overrides)
    ws = Workspace(root)
    before = ws.snapshot()
    result = run_agent(task, ws, OllamaModel(settings), settings, checks=checks)
    diff = changes(before, ws.snapshot())

    lines = [
        (
            f"status: {result.status} ({result.steps} steps, {result.tool_calls} tool calls, "
            f"{result.tool_errors} tool errors, {result.seconds:.0f}s, model {settings.model})"
        ),
        f"usage: {result.usage.describe(settings.num_ctx)}",
    ]
    lines += [f"{kind}: {p}" for kind, paths in diff.items() for p in paths] or ["no files changed"]
    lines += ["", "agent summary:", result.summary]
    return "\n".join(lines)


@server.tool()
async def run_local_agent(
    task: str,
    workdir: str,
    check_commands: list[str] | None = None,
    require_committed: bool = False,
    require_pushed: bool = False,
    model: str | None = None,
    max_steps: int | None = None,
) -> str:
    """Run a coding agent on a local Ollama model (default gpt-oss:20b) inside `workdir`.

    The agent can read, write and edit files, search, run sandboxed shell commands (no network)
    and use git in that folder only. Good for small, well-specified tasks: fix a bug with a
    failing test, implement a function, add a test. Give a complete task description.

    Always say how to verify the work: the local model is small and may not work it out.
    `check_commands` (e.g. ["python -m pytest -q", "ruff check ."]) must all succeed, and with
    `require_committed` / `require_pushed` the work must be committed / pushed to origin,
    before the agent may finish; otherwise finish is refused with the failure. Returns the
    status ("checks_failed" if it gave up), the files it changed and its summary. Review the
    changes afterwards.
    """
    checks = Checks(tuple(check_commands or ()), require_committed, require_pushed)
    return await asyncio.to_thread(_run, task, workdir, model, max_steps, checks)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
