import shutil
import subprocess

import pytest

from localagents.agent import MAX_FINISH_REFUSALS, run_agent
from localagents.checks import Checks, run_checks
from tests.fakes import FakeModel
from tests.test_agent import call

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not installed")


def sh(ws, *args):
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=t@t", *args],
        cwd=ws.root, capture_output=True, text=True, check=True,
    )  # fmt: skip


@pytest.fixture
def repo(ws):
    sh(ws, "init", "-q", "-b", "main")
    (ws.root / "app.py").write_text("x = 1\n")
    sh(ws, "add", ".")
    sh(ws, "commit", "-q", "-m", "initial")
    return ws


def test_no_checks_is_falsy():
    assert not Checks()
    assert Checks(commands=("true",))


def test_commands_must_succeed(ws, settings):
    assert run_checks(ws, settings, Checks(commands=("true",))) == []
    [failure] = run_checks(ws, settings, Checks(commands=("echo broken; exit 3",)))
    assert failure.startswith("`echo broken; exit 3` failed:") and "broken" in failure


def test_committed(repo, settings):
    checks = Checks(committed=True)
    assert run_checks(repo, settings, checks) == []
    (repo.root / "__pycache__").mkdir()
    (repo.root / "__pycache__" / "app.pyc").write_text("")
    assert run_checks(repo, settings, checks) == []  # caches do not count
    (repo.root / "new.py").write_text("")
    [failure] = run_checks(repo, settings, checks)
    assert "uncommitted" in failure and "new.py" in failure


def test_pushed(repo, settings):
    checks = Checks(pushed=True)
    assert run_checks(repo, settings, checks) == ["branch main is not pushed to origin"]
    sh(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert run_checks(repo, settings, checks) == []
    sh(repo, "commit", "-q", "--allow-empty", "-m", "more")
    assert run_checks(repo, settings, checks) == ["origin/main is behind your latest commit; push again"]


def test_git_checks_outside_a_repo(ws, settings):
    assert run_checks(ws, settings, Checks(committed=True)) == ["this folder is not a git repository"]


def test_checks_are_told_to_the_model(ws, settings):
    model = FakeModel([call("finish", summary="done")])
    run_agent("the task", ws, model, settings, checks=Checks(commands=("true",), committed=False))
    task = model.calls[0][1]["content"]
    assert task.startswith("the task\n\nWhen you call finish") and "`true` must succeed" in task


def test_finish_is_refused_until_checks_pass(ws, settings):
    checks = Checks(commands=("test -f done.txt",))
    model = FakeModel(
        [
            call("finish", summary="too early"),
            call("write_file", path="done.txt", content="ok\n"),
            call("finish", summary="done"),
        ]
    )
    result = run_agent("t", ws, model, settings, checks=checks)
    assert (result.status, result.summary, result.tool_errors) == ("finished", "done", 1)
    refusal = model.calls[1][-1]["content"]
    assert refusal.startswith("Error: finish refused") and "test -f done.txt" in refusal


def test_run_ends_after_repeated_refusals(ws, settings):
    model = FakeModel([call("finish", summary=f"try {i}") for i in range(MAX_FINISH_REFUSALS)])
    result = run_agent("t", ws, model, settings, checks=Checks(commands=("false",)))
    assert result.status == "checks_failed"
    assert result.steps == MAX_FINISH_REFUSALS
