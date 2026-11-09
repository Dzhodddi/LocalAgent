"""search: ripgrep over the workspace."""

import subprocess

from localagents.tools import ToolError
from localagents.workspace import Workspace

MAX_LINE_CHARS = 300


def search(ws: Workspace, regex: str, path: str = ".", max_results: int = 100) -> str:
    """`file:line: text` matches for `regex`, via `rg`."""
    target = ws.resolve(path)
    if not target.exists():
        raise ToolError(f"Path not found: {path}")
    if max_results < 1:
        raise ToolError("max_results must be at least 1.")

    cmd = [
        "rg",
        "--line-number",
        "--with-filename",
        "--no-heading",
        "--color=never",
        "--smart-case",
        "--sort=path",
    ]
    cmd += ["--", regex]
    if target != ws.root:  # without a path rg prints `src/a.py`, with `.` it prints `./src/a.py`
        cmd.append(ws.relative(target))
    try:
        proc = subprocess.run(cmd, check=False, cwd=ws.root, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as e:
        raise ToolError("ripgrep (rg) is not installed.") from e
    except subprocess.TimeoutExpired as e:
        raise ToolError("Search timed out. Use a narrower path or pattern.") from e

    if proc.returncode == 1:
        return f"No matches for {regex!r} in {ws.relative(target)}."
    if proc.returncode != 0:
        raise ToolError(f"Search failed: {proc.stderr.strip()}")

    lines = proc.stdout.splitlines()
    shown = [
        line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + "..." for line in lines[:max_results]
    ]
    result = "\n".join(shown)
    if len(lines) > max_results:
        result += f"\n... {len(lines) - max_results} more matches. Use a narrower pattern or path."
    return result
