import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
REMOTE = os.environ["EVAL_REMOTE"]


def git(*args, cwd=ROOT):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def run_python_in_remote_branch(branch, code):
    """Clone the pushed branch and run code there: proves what was pushed, not what is local."""
    with tempfile.TemporaryDirectory() as tmp:
        clone = git("clone", "-q", "-b", branch, REMOTE, tmp, cwd=tmp)
        assert clone.returncode == 0, f"branch {branch} not on the remote: {clone.stderr}"
        return subprocess.run([sys.executable, "-c", code], cwd=tmp, capture_output=True, text=True)


def uncommitted():
    out = git("status", "--porcelain", "--", ".", ":!hidden_tests").stdout
    return [line for line in out.splitlines() if line.strip()]



def test_broken_edits_discarded():
    from calc import add

    assert add(2, 3) == 5
    assert "WIP" not in (ROOT / "calc.py").read_text()


def test_subtract():
    from calc import subtract

    assert subtract(5, 3) == 2


def test_committed_with_a_test():
    assert git("rev-list", "--count", "main").stdout.strip() == "2"
    changed = git("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert "calc.py" in changed and "tests/test_calc.py" in changed
    assert "subtract" in git("show", "HEAD:tests/test_calc.py").stdout
    assert uncommitted() == []
