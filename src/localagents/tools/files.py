"""read_file, write_file, edit_file, list_files."""

import difflib
import re
from pathlib import Path

from localagents.tools import ToolError
from localagents.workspace import SKIP_DIRS, Workspace

MAX_READ_LINES = 2000
MAX_LIST_FILES = 500
MAX_DIFF_LINES = 40
DEF_RE = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)", re.MULTILINE)


def _change_report(before: str, after: str) -> str:
    """A short unified diff, plus a warning if functions or classes disappeared.

    Models often use edit_file to "add after" a snippet and forget to keep the snippet;
    showing what was removed lets them notice and repair it.
    """
    diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(), n=1, lineterm=""))[2:]
    removed = sum(1 for line in diff if line.startswith("-"))
    added = sum(1 for line in diff if line.startswith("+"))
    shown = diff[:MAX_DIFF_LINES]
    if len(diff) > len(shown):
        shown.append(f"... {len(diff) - len(shown)} more diff lines")
    report = f"(-{removed} +{added} lines)\n" + "\n".join(shown)

    lost = sorted(set(DEF_RE.findall(before)) - set(DEF_RE.findall(after)))
    if lost:
        report += (
            f"\nWarning: this removed {', '.join(lost)}. If you meant to add code next to existing "
            "code, put the removed code back: the replacement must contain everything that should remain."
        )
    return report


def _read_text(ws: Workspace, path: str) -> tuple[Path, str]:
    full = ws.resolve(path)
    if not full.exists():
        raise ToolError(f"File not found: {path}")
    if not full.is_file():
        raise ToolError(f"Not a file: {path}")
    data = full.read_bytes()
    if b"\0" in data[:8192]:
        raise ToolError(f"Binary file, cannot show as text: {path}")
    return full, data.decode("utf-8", errors="replace")


def read_file(ws: Workspace, path: str, start: int | None = None, end: int | None = None) -> str:
    """File contents with 1-based line numbers, optionally limited to a line range."""
    _, text = _read_text(ws, path)
    lines = text.splitlines()
    if not lines:
        return f"{path} is empty."

    first = 1 if start is None else start
    last = len(lines) if end is None else end
    if first < 1 or last < first:
        raise ToolError(f"Invalid line range {start}-{end}. Lines are 1-based and start must be <= end.")
    if first > len(lines):
        raise ToolError(f"{path} has only {len(lines)} lines.")
    last = min(last, len(lines), first + MAX_READ_LINES - 1)

    body = "\n".join(f"{n:>5}\t{lines[n - 1]}" for n in range(first, last + 1))
    if last < len(lines):
        body += f"\n... showing lines {first}-{last} of {len(lines)}. Use start/end to read more."
    return body


def write_file(ws: Workspace, path: str, content: str) -> str:
    """Create a new file (or fully overwrite one). Parent folders are created."""
    full = ws.resolve(path)
    if full.is_dir():
        raise ToolError(f"{path} is a directory.")
    before = _read_text(ws, path)[1] if full.exists() else None
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    if before is None:
        return f"Created {ws.relative(full)} ({len(content.splitlines())} lines)."
    return f"Overwrote {ws.relative(full)} {_change_report(before, content)}"


def edit_file(ws: Workspace, path: str, old: str, new: str) -> str:
    """Replace one exact, unique occurrence of `old`. Fails without changes otherwise."""
    if not old:
        raise ToolError(
            "`old` is empty. Copy the exact text to replace from read_file output (without line numbers)."
        )
    if old == new:
        raise ToolError("`old` and `new` are identical; nothing to change.")
    full, text = _read_text(ws, path)

    count = text.count(old)
    if count == 0:
        raise ToolError(
            f"`old` was not found in {path}. It must match exactly, including indentation and "
            "whitespace. Re-read the file and copy the text without line numbers."
        )
    if count > 1:
        raise ToolError(
            f"`old` appears {count} times in {path}. Include more surrounding lines so it is unique."
        )

    index = text.index(old)
    updated = text.replace(old, new, 1)
    full.write_text(updated, encoding="utf-8")
    line = text.count("\n", 0, index) + 1
    return f"Edited {ws.relative(full)} at line {line} {_change_report(text, updated)}"


def list_files(ws: Workspace, pattern: str = "**/*") -> str:
    """Glob relative to the workspace root, skipping .git, .venv and caches."""
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise ToolError("Pattern must be relative to the project root and must not contain `..`.")

    matches = []
    for full in ws.root.glob(pattern):
        rel = full.relative_to(ws.root)
        if SKIP_DIRS.intersection(rel.parts) or not full.is_file():
            continue
        if not full.resolve().is_relative_to(ws.root):  # symlink pointing outside
            continue
        matches.append(rel.as_posix())

    if not matches:
        return f"No files match {pattern}."
    matches.sort()
    shown = matches[:MAX_LIST_FILES]
    result = "\n".join(shown)
    if len(matches) > len(shown):
        result += f"\n... {len(matches) - len(shown)} more. Use a narrower pattern."
    return result
