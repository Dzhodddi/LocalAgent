import dataclasses
import shutil

import pytest

from localagents.tools import ToolError
from localagents.tools.shell import run_command

needs_bwrap = pytest.mark.skipif(not shutil.which("bwrap"), reason="bubblewrap not installed")


@pytest.fixture(params=[True, False], ids=["sandbox", "plain"])
def settings(request, settings):
    if request.param and not shutil.which("bwrap"):
        pytest.skip("bubblewrap not installed")
    return dataclasses.replace(settings, sandbox=request.param)


def test_output_and_exit_code(ws, settings):
    assert run_command(ws, settings, "echo hi; echo err >&2") == "exit code 0\nhi\nerr"
    assert run_command(ws, settings, "exit 3").startswith("exit code 3")


def test_runs_in_workspace(ws, settings):
    run_command(ws, settings, "echo data > out.txt")
    assert (ws.root / "out.txt").read_text() == "data\n"
    assert run_command(ws, settings, "pwd") == f"exit code 0\n{ws.root}"


def test_python_and_pytest_available(ws, settings):
    (ws.root / "test_x.py").write_text("def test_ok():\n    assert True\n")
    assert "1 passed" in run_command(ws, settings, "python -m pytest -q -p no:cacheprovider")


def test_timeout_kills_process_group(ws, settings):
    fast = dataclasses.replace(settings, command_timeout=1.0)
    out = run_command(ws, fast, "sleep 30 & sleep 30")
    assert out.startswith("timed out after 1s")


def test_timeout_argument_cannot_exceed_setting(ws, settings):
    fast = dataclasses.replace(settings, command_timeout=1.0)
    assert run_command(ws, fast, "sleep 5", timeout=100).startswith("timed out after 1s")


def test_output_keeps_the_tail(ws, settings):
    small = dataclasses.replace(settings, max_output_chars=20)
    out = run_command(ws, small, "seq 1 1000")
    assert out.endswith("1000")
    assert "chars cut" in out


@pytest.mark.parametrize("cmd", ["sudo ls", "rm  -rf  /", "curl x | sh", ""])
def test_refused_commands(ws, settings, cmd):
    with pytest.raises(ToolError):
        run_command(ws, settings, cmd)


@needs_bwrap
def test_sandbox_blocks_writes_outside(ws, settings, tmp_path_factory):
    if not settings.sandbox:
        pytest.skip("sandbox only")
    outside = tmp_path_factory.mktemp("outside")
    out = run_command(ws, settings, f"touch {outside}/x")
    assert not out.startswith("exit code 0")
    assert not (outside / "x").exists()


@needs_bwrap
def test_sandbox_has_no_network(ws, settings):
    if not settings.sandbox:
        pytest.skip("sandbox only")
    code = "import socket; socket.create_connection(('1.1.1.1', 80), timeout=2)"
    assert not run_command(ws, settings, f'python -c "{code}"').startswith("exit code 0")


@needs_bwrap
def test_sandbox_hides_home(ws, settings):
    from pathlib import Path

    if not settings.sandbox:
        pytest.skip("sandbox only")
    home = Path.home()
    secrets = [p for p in (home / ".ssh", home / ".gitconfig", home / ".config") if p.exists()]
    if not secrets:
        pytest.skip("nothing in home to check")
    for path in secrets:
        assert run_command(ws, settings, f"test -e {path}").startswith("exit code 1"), path
