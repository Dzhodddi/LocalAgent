"""Project instructions for the agent, like CLAUDE.md for Claude Code.

The agent reads AGENTS.md (or CLAUDE.md when there is none):
  - from the project root, once, into the system prompt;
  - from a subfolder, the first time a tool touches a path inside it, appended to that
    tool's output, so instructions about one part of the project cost nothing elsewhere.

A small model has a small context, so each file is capped and a cut file says so.
"""

from pathlib import Path

from localagents.workspace import Workspace, WorkspaceError

CONTEXT_FILES = ("AGENTS.md", "CLAUDE.md")  # first one found in a folder wins
MAX_ROOT_CHARS = 6000  # ~1.5k tokens of a 16k context
MAX_FOLDER_CHARS = 3000


def _context_file(folder: Path) -> Path | None:
    return next((folder / name for name in CONTEXT_FILES if (folder / name).is_file()), None)


def _read(file: Path, limit: int) -> str:
    text = file.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + f"\n[... {file.name} cut at {limit} characters]"
    return text


def project_instructions(ws: Workspace) -> str | None:
    """The root AGENTS.md / CLAUDE.md, ready to append to the system prompt."""
    file = _context_file(ws.root)
    if not file:
        return None
    text = _read(file, MAX_ROOT_CHARS)
    return f"Project instructions from {file.name}. Follow them; the task wins if they conflict:\n\n{text}"


class FolderInstructions:
    """Hands out each subfolder's AGENTS.md / CLAUDE.md once, the first time the agent goes there."""

    def __init__(self, ws: Workspace):
        self.ws = ws
        self.seen: set[Path] = {ws.root}  # the root file is already in the system prompt

    def for_path(self, path: str) -> str | None:
        """Instructions for folders between the root and `path` that the agent has not seen yet."""
        try:
            target = self.ws.resolve(path)
        except WorkspaceError:  # a bad path is the tool's error to report, not ours
            return None
        folder = target if target.is_dir() else target.parent
        if not folder.is_relative_to(self.ws.root):
            return None
        chain = [folder, *folder.parents]
        new = [f for f in reversed(chain[: chain.index(self.ws.root)]) if f not in self.seen]
        parts = []
        for f in new:
            self.seen.add(f)
            if file := _context_file(f):
                rel = self.ws.relative(file)
                parts.append(
                    f"Instructions from {rel} for files in {self.ws.relative(f)}/:\n{_read(file, MAX_FOLDER_CHARS)}"
                )
        return "\n\n".join(parts) or None
