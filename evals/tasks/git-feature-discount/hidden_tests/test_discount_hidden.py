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


def test_discount_pushed():
    code = (
        "from customer import Customer; from order import Order\n"
        "o = Order(Customer('bo', discount_pct=10)); o.add('tea', 3, 3.33)\n"
        "assert o.total() == 8.99, o.total()\n"
        "p = Order(Customer('cy')); p.add('tea', 1, 2.0)\n"
        "assert p.total() == 2.0"
    )
    result = run_in_remote_branch("feat/customer-discount", code)
    assert result.returncode == 0, result.stderr


def test_new_test_pushed():
    tests = git("show", "feat/customer-discount:tests/test_order.py", cwd=REMOTE).stdout
    assert "discount" in tests and "def test_total" in tests


def test_main_untouched_on_remote():
    assert git("rev-list", "--count", "main", cwd=REMOTE).stdout.strip() == "1"
