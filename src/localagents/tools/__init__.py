"""Tool registry: what the model can call, as Ollama tool schemas plus handlers."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from localagents.config import Settings
from localagents.workspace import Workspace, WorkspaceError


class ToolError(Exception):
    """An error reported back to the model as the tool result (never crashes the loop)."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the arguments
    func: Callable[..., str]

    def schema(self) -> dict[str, Any]:
        """The tool in Ollama's `tools` format."""
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }

    def call(self, arguments: dict[str, Any] | None) -> str:
        """Check the model's arguments against the schema and run the tool.

        Every problem (bad arguments, path outside the workspace, tool failure)
        is raised as ToolError so the loop can hand it back to the model.
        """
        args = dict(arguments or {})
        props = self.parameters.get("properties", {})

        unknown = sorted(set(args) - set(props))
        if unknown:
            raise ToolError(
                f"{self.name}: unknown argument(s) {', '.join(unknown)}. Allowed: {', '.join(props)}."
            )
        missing = [name for name in self.parameters.get("required", []) if args.get(name) is None]
        if missing:
            raise ToolError(f"{self.name}: missing required argument(s) {', '.join(missing)}.")

        required = set(self.parameters.get("required", []))
        for name, value in list(args.items()):
            # Small models often send null or "" for optional arguments they mean to leave out.
            if value is None or (value == "" and name not in required):
                del args[name]
            else:
                args[name] = _coerce(self.name, name, value, props[name].get("type"))

        try:
            return self.func(**args)
        except WorkspaceError as e:
            raise ToolError(str(e)) from e


def _coerce(tool: str, name: str, value: Any, kind: str | None) -> Any:
    """Fix the type slips models commonly make, e.g. "12" for an integer."""
    if kind == "integer":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        raise ToolError(f"{tool}: `{name}` must be an integer, got {value!r}.")
    if kind == "string" and not isinstance(value, str):
        raise ToolError(f"{tool}: `{name}` must be a string, got {type(value).__name__}.")
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise ToolError(f"{tool}: `{name}` must be true or false, got {value!r}.")
    if kind == "array":
        if isinstance(value, str):  # a single path instead of a list
            value = [value]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ToolError(f"{tool}: `{name}` must be a list of strings, got {value!r}.")
    return value


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def build_tools(workspace: Workspace, settings: Settings) -> dict[str, Tool]:
    """All tools bound to one workspace: read_file, write_file, edit_file, list_files, search,
    run_command, the git tools when the workspace is a git repository, and finish."""
    # Imported here, not at the top: these modules import ToolError from this one.
    from localagents.tools import files, git, search, shell

    path = {"type": "string", "description": "File path relative to the project root, e.g. src/app.py."}
    tools = [
        Tool(
            name="read_file",
            description=(
                "Read a text file. Output has line numbers in the form `   12\\tcode`; the numbers are "
                "not part of the file. Use start/end to read part of a long file."
            ),
            parameters=_schema(
                {
                    "path": path,
                    "start": {"type": "integer", "description": "First line to show (1-based). Optional."},
                    "end": {"type": "integer", "description": "Last line to show, inclusive. Optional."},
                },
                ["path"],
            ),
            func=partial(files.read_file, workspace),
        ),
        Tool(
            name="write_file",
            description=(
                "Create a new file with the given content, creating folders as needed. Overwrites the "
                "whole file if it exists, so use edit_file to change existing files."
            ),
            parameters=_schema(
                {"path": path, "content": {"type": "string", "description": "The complete file content."}},
                ["path", "content"],
            ),
            func=partial(files.write_file, workspace),
        ),
        Tool(
            name="edit_file",
            description=(
                "Change an existing file by replacing one exact snippet: `old` is removed and `new` is put "
                "in its place. `old` must appear exactly once and match character for character, including "
                "indentation; copy it from read_file output without the line numbers. To ADD code after "
                "existing code, `new` must repeat the existing snippet followed by the new code, otherwise "
                "the existing code is deleted. Use an empty `new` to delete the snippet. Returns a diff."
            ),
            parameters=_schema(
                {
                    "path": path,
                    "old": {"type": "string", "description": "Exact text to replace (unique in the file)."},
                    "new": {
                        "type": "string",
                        "description": "Text that replaces `old`. Include `old` in it to keep that code.",
                    },
                },
                ["path", "old", "new"],
            ),
            func=partial(files.edit_file, workspace),
        ),
        Tool(
            name="list_files",
            description=(
                "List files matching a glob pattern relative to the project root. `**/*.py` finds Python "
                "files in all folders, `*.py` only at the top level. Skips .git, .venv and caches."
            ),
            parameters=_schema(
                {"pattern": {"type": "string", "description": "Glob pattern. Default: **/* (all files)."}},
                [],
            ),
            func=partial(files.list_files, workspace),
        ),
        Tool(
            name="search",
            description=(
                "Search file contents with a regular expression (ripgrep). Returns `file:line:text` "
                "matches. Use it to find definitions and usages without reading every file."
            ),
            parameters=_schema(
                {
                    "regex": {"type": "string", "description": "Regular expression, e.g. `def paginate`."},
                    "path": {
                        "type": "string",
                        "description": "File or folder to search. Default: whole project.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum matches to return. Default 100.",
                    },
                },
                ["regex"],
            ),
            func=partial(search.search, workspace),
        ),
        Tool(
            name="run_command",
            description=(
                "Run a bash command in the project root, e.g. `python -m pytest -q` or `python main.py`. "
                f"No network access; files outside the project are read-only. Times out after "
                f"{settings.command_timeout:g}s. Returns the exit code and output."
            ),
            parameters=_schema(
                {
                    "cmd": {"type": "string", "description": "The bash command to run."},
                    "timeout": {"type": "integer", "description": "Seconds before the command is killed."},
                },
                ["cmd"],
            ),
            func=partial(shell.run_command, workspace, settings),
        ),
    ]
    if git.is_repo(workspace):
        tools += _git_tools(workspace, settings)
    tools += [
        Tool(
            name="finish",
            description=(
                "Call this once the task is complete and the tests pass. Ends your work. The summary "
                "should say what you changed and how you checked it."
            ),
            parameters=_schema(
                {"summary": {"type": "string", "description": "What you changed and how you verified it."}},
                ["summary"],
            ),
            func=lambda summary: summary,  # the agent loop stops when it sees this tool
        ),
    ]
    return {tool.name: tool for tool in tools}


def _git_tools(workspace: Workspace, settings: Settings) -> list[Tool]:
    from localagents.tools import git

    def bound(func):
        return partial(func, workspace, settings)

    path = {"type": "string", "description": "File or folder relative to the project root. Optional."}
    return [
        Tool(
            name="git_status",
            description="Show the current git branch and which files are modified, staged or untracked.",
            parameters=_schema({}, []),
            func=bound(git.git_status),
        ),
        Tool(
            name="git_diff",
            description=(
                "Show uncommitted changes to tracked files as a diff (new untracked files are listed by "
                "git_status instead). Use it to review your work before committing or finishing."
            ),
            parameters=_schema(
                {
                    "path": path,
                    "staged": {
                        "type": "boolean",
                        "description": "Show staged changes instead. Default false.",
                    },
                },
                [],
            ),
            func=bound(git.git_diff),
        ),
        Tool(
            name="git_log",
            description="Show recent commits, newest first: short hash, date, author and message.",
            parameters=_schema(
                {
                    "count": {"type": "integer", "description": "How many commits (1-100). Default 10."},
                    "path": path,
                },
                [],
            ),
            func=bound(git.git_log),
        ),
        Tool(
            name="git_commit",
            description=(
                "Stage and commit changes. Without `paths` every change in the project is committed. "
                "Only commit when the task asks for it, after the tests pass."
            ),
            parameters=_schema(
                {
                    "message": {"type": "string", "description": "Commit message: a short summary line."},
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Files or folders to commit. Default: all changes.",
                    },
                },
                ["message"],
            ),
            func=bound(git.git_commit),
        ),
        Tool(
            name="git_restore",
            description=(
                "Undo all uncommitted changes to one tracked file or folder, putting back the last "
                "committed version. Use it to recover from a broken edit. Cannot be undone."
            ),
            parameters=_schema(
                {"path": {"type": "string", "description": "File or folder relative to the project root."}},
                ["path"],
            ),
            func=bound(git.git_restore),
        ),
        Tool(
            name="git_create_branch",
            description="Create a new branch from the current commit and switch to it. Uncommitted changes stay.",
            parameters=_schema(
                {"name": {"type": "string", "description": "Branch name, e.g. fix/pagination."}},
                ["name"],
            ),
            func=bound(git.git_create_branch),
        ),
    ]
