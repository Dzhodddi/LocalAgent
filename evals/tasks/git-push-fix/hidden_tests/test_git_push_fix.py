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


def test_fix_was_pushed_on_the_branch():
    result = run_python_in_remote_branch(
        "fix/pagination",
        "from paginate import paginate; assert paginate([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]",
    )
    assert result.returncode == 0, result.stderr


def test_main_untouched_on_remote():
    assert git("rev-list", "--count", "main", cwd=REMOTE).stdout.strip() == "1"


def test_everything_committed():
    assert uncommitted() == []
