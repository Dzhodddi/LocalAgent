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


def bad_commit():
    return git("log", "--format=%H", "--grep=Refactor discount calculation", "main", cwd=REMOTE).stdout.strip()


def test_fix_was_pushed():
    result = run_python_in_remote_branch(
        "fix/regression", "from pricing import final_price; assert final_price(200, 10) == 180"
    )
    assert result.returncode == 0, result.stderr


def test_message_mentions_bad_commit():
    messages = git("log", "--format=%B", "main..fix/regression", cwd=REMOTE).stdout
    full = bad_commit()
    assert any(full[:n] in messages for n in range(7, 13)), messages


def test_main_untouched_on_remote():
    assert git("rev-list", "--count", "main", cwd=REMOTE).stdout.strip() == "3"
