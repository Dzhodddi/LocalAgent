"""run_command: shell commands inside the workspace, sandboxed with bubblewrap."""

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from localagents.config import Settings
from localagents.tools import ToolError
from localagents.workspace import Workspace

DENYLIST = ("sudo", "rm -rf /", "| sh", "| bash", "mkfs", "shutdown")


def sandbox_args(ws: Workspace) -> list[str]:
    """bubblewrap prefix: read-only system, writable workspace and /tmp, no network."""
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise ToolError("bubblewrap (bwrap) is not installed, so commands cannot be sandboxed.")
    root = str(ws.root)
    return [
        bwrap,
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--bind", root, root,
        "--chdir", root,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
    ]  # fmt: skip


def command_env(ws: Workspace) -> dict[str, str]:
    # This project's venv comes first on PATH so `python` and `pytest` work inside tasks.
    venv_bin = str(Path(sys.executable).parent)
    return {
        "PATH": f"{venv_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(ws.root),
    }


def run_command(ws: Workspace, settings: Settings, cmd: str, timeout: float | None = None) -> str:
    """Run `cmd` with cwd at the workspace root. Returns exit code plus
    combined stdout/stderr, truncated to the last `settings.max_output_chars`."""
    if not cmd.strip():
        raise ToolError("Command is empty.")
    normalized = " ".join(cmd.split())
    blocked = [word for word in DENYLIST if word in normalized]
    if blocked:
        raise ToolError(f"Command refused: contains {blocked[0]!r}.")

    limit = min(timeout or settings.command_timeout, settings.command_timeout)
    prefix = sandbox_args(ws) if settings.sandbox else []
    proc = subprocess.Popen(
        [*prefix, "bash", "-c", cmd],
        cwd=ws.root,
        env=command_env(ws),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # own process group, so a timeout kills children too
    )
    try:
        raw, _ = proc.communicate(timeout=limit)
        header = f"exit code {proc.returncode}"
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        raw, _ = proc.communicate()
        header = f"timed out after {limit:g}s and was killed"

    output = raw.decode("utf-8", errors="replace")
    if len(output) > settings.max_output_chars:
        output = (
            f"... ({len(output) - settings.max_output_chars} chars cut)\n"
            + output[-settings.max_output_chars :]
        )
    return f"{header}\n{output}".rstrip()
