"""Every eval task must be well formed and must fail before the agent touches it."""

import os
import shutil
import subprocess
import sys

import pytest

from evals.runner import TASKS, tampered_tests

TASK_DIRS = sorted(d for d in TASKS.iterdir() if d.is_dir())


@pytest.mark.parametrize("task", TASK_DIRS, ids=lambda d: d.name)
def test_task_layout(task):
    assert (task / "task.md").read_text().strip()
    assert any((task / "repo").rglob("*.py"))
    assert any((task / "hidden_tests").glob("test_*.py"))


@pytest.mark.parametrize("task", TASK_DIRS, ids=lambda d: d.name)
def test_task_fails_before_any_change(task, tmp_path):
    from evals.runner import setup_task

    work, remote = tmp_path / "repo", tmp_path / "origin.git"
    setup_task(task, work, remote)
    shutil.copytree(task / "hidden_tests", work / "hidden_tests")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        env=os.environ | {"EVAL_REMOTE": str(remote)},
        check=False,
        cwd=work,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, proc.stdout  # 1 = tests ran and some failed (not a collection error)


def test_tampering_detection(tmp_path):
    original, work = tmp_path / "orig", tmp_path / "work"
    for root in (original, work):
        (root / "tests").mkdir(parents=True)
    (original / "tests/test_a.py").write_text("def test_one(): ...\ndef test_two(): ...\n")
    (work / "tests/test_a.py").write_text("def test_one(): ...\ndef test_two(): ...\ndef test_new(): ...\n")
    diff = {"added": [], "modified": ["tests/test_a.py"], "deleted": []}
    assert tampered_tests(original, work, diff) == []  # adding a test is fine

    (work / "tests/test_a.py").write_text("def test_one(): ...\n")
    assert tampered_tests(original, work, diff) == ["tests/test_a.py"]

    diff = {"added": [], "modified": [], "deleted": ["tests/test_a.py"]}
    (work / "tests/test_a.py").unlink()
    assert tampered_tests(original, work, diff) == ["tests/test_a.py"]


def test_run_task_grades_a_correct_fix(tmp_path):
    """Drive the real runner with a scripted model that fixes fix-pagination."""
    from evals.runner import run_task
    from localagents.config import Settings
    from tests.fakes import FakeModel

    def call(name, **arguments):
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
        }

    model = FakeModel(
        [
            call("edit_file", path="paginate.py", old="len(items) - page_size", new="len(items)"),
            call("finish", summary="fixed"),
        ]
    )
    row = run_task(TASKS / "fix-pagination", model, Settings(), tmp_path / "log.jsonl")
    assert row["passed"], row["pytest"]
    assert row["changed"]["modified"] == ["paginate.py"]


def test_run_one_turns_crash_into_failed_row(tmp_path):
    from evals.runner import run_one
    from localagents.config import Settings

    class Exploding:
        def chat(self, messages, tools):
            raise RuntimeError("boom")

    row = run_one(TASKS / "fix-pagination", 2, Exploding(), Settings(), tmp_path)
    assert (row["passed"], row["status"], row["run"]) == (False, "crashed", 2)


def test_summarize_throughput():
    from evals.runner import summarize

    usage = {"calls": 1, "prompt_tokens": 0, "output_tokens": 100, "peak_context": 900, "prompt_seconds": 0.0,
             "output_seconds": 10.0, "load_seconds": 0.0, "output_tps": 10.0}  # fmt: skip
    rows = [{"passed": True, "usage": usage}, {"passed": False, "usage": usage | {"peak_context": 1200}}]
    s = summarize(rows, wall_seconds=10.0, jobs=2)
    assert (s["passed"], s["runs"], s["pass_rate"], s["jobs"]) == (1, 2, 0.5, 2)
    assert s["throughput_tps"] == 20.0  # 200 tokens in 10s of wall time
    assert s["per_request_tps"] == 10.0
    assert s["peak_context"] == 1200
