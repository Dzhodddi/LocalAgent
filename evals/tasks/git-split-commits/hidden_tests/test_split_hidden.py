import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
REMOTE = os.environ["EVAL_REMOTE"]


def git(*args, cwd=ROOT):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def run_in_remote_branch(branch, code):
    """Clone the pushed branch and run code there: proves what was pushed, not what is local."""
    with tempfile.TemporaryDirectory() as tmp:
        clone = git("clone", "-q", "-b", branch, REMOTE, tmp, cwd=tmp)
        assert clone.returncode == 0, f"branch {branch} not on the remote: {clone.stderr}"
        return subprocess.run([sys.executable, "-c", code], cwd=tmp, capture_output=True, text=True)


def commits():
    out = git("log", "--reverse", "--format=%H %s", "main..fix/two-bugs", cwd=REMOTE).stdout
    return [line.split(" ", 1) for line in out.splitlines()]


def files_in(sha):
    return set(git("show", "--name-only", "--format=", sha, cwd=REMOTE).stdout.split())


def test_fixes_pushed():
    code = "from mathx import mean; from textstats import word_count; assert mean([1, 2, 3]) == 2; assert word_count('a  b\\nc') == 3; assert word_count('') == 0"
    result = run_in_remote_branch("fix/two-bugs", code)
    assert result.returncode == 0, result.stderr


def test_one_commit_per_file():
    found = commits()
    assert len(found) == 2, found
    by_file = {}
    for sha, subject in found:
        code_files = files_in(sha) - {"tests/test_helpers.py"}
        assert len(code_files) == 1, (subject, code_files)
        by_file[code_files.pop()] = subject
    assert set(by_file) == {"textstats.py", "mathx.py"}
    assert "word_count" in by_file["textstats.py"]
    assert "mean" in by_file["mathx.py"]


def test_main_untouched_on_remote():
    assert git("rev-list", "--count", "main", cwd=REMOTE).stdout.strip() == "1"
