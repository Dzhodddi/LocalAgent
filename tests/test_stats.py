from datetime import datetime

import pytest

from evals.stats import Run, comparisons, fisher_exact, flaky_tasks, runs_needed, wilson


def run(name, results, **settings):
    rows = [{"task": task, "passed": ok} for task, ok in results]
    return Run(name, datetime.strptime(name, "%Y%m%d-%H%M%S"), {"model": "m", **settings}, None, rows)


def test_wilson_interval():
    assert wilson(9, 9)[1] == 1.0
    lo, hi = wilson(9, 9)
    assert lo == pytest.approx(0.701, abs=0.001)  # 9/9 is consistent with a true rate near 70%
    lo, hi = wilson(36, 39)
    assert lo == pytest.approx(0.797, abs=0.001) and hi == pytest.approx(0.973, abs=0.001)
    assert wilson(0, 0) == (0.0, 1.0)


def test_fisher_exact():
    assert fisher_exact(9, 9, 5, 9) == pytest.approx(0.0824, abs=1e-4)
    assert fisher_exact(36, 39, 35, 39) == pytest.approx(1.0)
    assert fisher_exact(10, 10, 0, 10) < 0.001


def test_runs_needed():
    assert runs_needed(0.5, 0.5) is None
    assert runs_needed(0.9, 0.5) == 17
    assert runs_needed(1.0, 0.0) == 1


def test_comparisons_pair_runs_on_the_same_tasks():
    a = run("20260101-000000", [("t1", True), ("t2", False)])
    b = run("20260102-000000", [("t1", True), ("t2", True)])
    other = run("20260103-000000", [("t3", True)])
    c = run("20260104-000000", [("t1", False), ("t2", False)])
    found = comparisons([a, b, other, c], [(a.name, c.name, "named experiment"), (b.name, c.name, "renamed")])
    assert [(x.a.name, x.b.name, x.why) for x in found] == [
        (a.name, b.name, "previous run on the same tasks"),
        (b.name, c.name, "renamed"),
        (a.name, c.name, "named experiment"),
    ]


def test_flaky_tasks():
    a = run("20260101-000000", [("t1", True), ("t1", False), ("t2", True)])
    b = run("20260102-000000", [("t2", True), ("t3", False)])
    assert flaky_tasks([a, b]) == {"t1": (1, 2)}
