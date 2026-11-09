"""The folder an agent is confined to. Every tool path goes through here."""

import hashlib
from pathlib import Path

# Folders hidden from list_files and ignored by snapshot().
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
}


class WorkspaceError(Exception):
    """A path escaped the workspace or is otherwise not allowed."""


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def resolve(self, path: str) -> Path:
        """Return an absolute path inside the workspace, or raise WorkspaceError.

        Rejects absolute paths, `..` escapes and symlinks pointing outside.
        """
        if not path or not path.strip():
            raise WorkspaceError("Path is empty.")
        if Path(path).is_absolute():
            raise WorkspaceError(
                f"Absolute paths are not allowed: {path}. Use a path relative to the project root."
            )
        # resolve() follows symlinks, so a link pointing outside is caught here too.
        full = (self.root / path).resolve()
        if not full.is_relative_to(self.root):
            raise WorkspaceError(f"Path is outside the project folder: {path}")
        if ".git" in full.relative_to(self.root).parts:
            # Writing hooks or config there could run code later; use the git tools instead.
            raise WorkspaceError(f"Files inside .git are off limits: {path}. Use the git tools.")
        return full

    def relative(self, path: Path) -> str:
        """Display form of a resolved path, relative to the root (`.` for the root itself)."""
        return path.relative_to(self.root).as_posix() or "."

    def snapshot(self) -> dict[str, str]:
        """Content hash of every file, keyed by relative path. Compare two with `changes()`."""
        hashes = {}
        for folder, dirs, names in self.root.walk():
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]  # prune, so .venv is never walked
            for name in names:
                full = folder / name
                if full.is_file() and not full.is_symlink():
                    hashes[full.relative_to(self.root).as_posix()] = hashlib.sha256(
                        full.read_bytes()
                    ).hexdigest()
        return hashes


def changes(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    """Files added, modified and deleted between two snapshots."""
    return {
        "added": sorted(after.keys() - before.keys()),
        "modified": sorted(p for p in before.keys() & after.keys() if before[p] != after[p]),
        "deleted": sorted(before.keys() - after.keys()),
    }
