"""Eval runner.

For each task in evals/tasks/<name>/:
  1. copy repo/ into a fresh temp folder
  2. run the agent on task.md (step cap + time limit). Like an orchestrator would, the runner
     tells the agent how to check it is done: checks.json, or by default the visible tests
  3. restore the original test files, copy hidden_tests/ in AFTER the run and run pytest
  4. write results + JSONL trajectories to evals/results/<timestamp>/

Usage: uv run python evals/runner.py [--model M] [--repeats N] [--task NAME] [--jobs N] [--num-ctx N]
"""

import argparse
import dataclasses
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from localagents.agent import run_agent
from localagents.checks import Checks
from localagents.config import GIT_BACKENDS, THINK_CHOICES, Settings, parse_think
from localagents.llm import ChatModel, OllamaModel, Usage
from localagents.mcp_tools import load_mcp_config
from localagents.workspace import Workspace, changes

EVALS = Path(__file__).parent
TASKS = EVALS / "tasks"
RESULTS = EVALS / "results"
GRADE_TIMEOUT = 120
SERVICES_TIMEOUT = 600  # services-up.sh may build images and pull them the first time
DEFAULT_CHECKS = Checks(commands=("python -m pytest -q",))


def is_test_file(rel: str) -> bool:
    name = Path(rel).name
    return name.startswith("test_") or name == "conftest.py"


def test_names(path: Path) -> set[str]:
    return set(re.findall(r"^\s*def (test_\w+)", path.read_text(), re.MULTILINE)) if path.exists() else set()


def tampered_tests(original: Path, work: Path, diff: dict[str, list[str]]) -> list[str]:
    """Test files the agent deleted, or edited so that an original test is gone.
    Adding tests is fine (some tasks ask for it)."""
    return [
        rel
        for rel in diff["modified"] + diff["deleted"]
        if is_test_file(rel) and not test_names(original / rel) <= test_names(work / rel)
    ]


def run_script(script: Path, work: Path, env: dict[str, str], timeout: float, check: bool = True) -> None:
    proc = subprocess.run(
        ["bash", str(script)], cwd=work, env=os.environ | env, check=False, capture_output=True, text=True,
        timeout=timeout,
    )  # fmt: skip
    if check and proc.returncode != 0:
        raise RuntimeError(f"{script.name} failed: {(proc.stdout + proc.stderr).strip()[-2000:]}")


def setup_task(task_dir: Path, work: Path, remote: Path) -> None:
    """Copy the starting code; for git tasks, setup.sh then builds history and a bare `origin` at `remote`."""
    shutil.copytree(task_dir / "repo", work)
    if (task_dir / "setup.sh").exists():
        run_script(task_dir / "setup.sh", work, {"EVAL_REMOTE": str(remote)}, timeout=60)


def task_checks(task_dir: Path) -> Checks:
    """checks.json: {"commands": [...], "committed": bool, "pushed": bool}. Default: run the tests."""
    file = task_dir / "checks.json"
    if not file.exists():
        return DEFAULT_CHECKS
    spec = json.loads(file.read_text())
    return Checks(tuple(spec.get("commands", [])), spec.get("committed", False), spec.get("pushed", False))


def grade(work: Path, task_dir: Path, remote: Path | None = None) -> tuple[bool, str]:
    """Run visible + hidden tests on the agent's result. Returns (passed, pytest tail).

    Hidden tests of git tasks find the bare remote through EVAL_REMOTE.
    """
    hidden = work / "hidden_tests"
    shutil.copytree(task_dir / "hidden_tests", hidden)
    env = os.environ | ({"EVAL_REMOTE": str(remote)} if remote else {})
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=30"],
            check=False, cwd=work, env=env, capture_output=True, text=True, timeout=GRADE_TIMEOUT,
        )  # fmt: skip
        output, passed = proc.stdout + proc.stderr, proc.returncode == 0
    except subprocess.TimeoutExpired:
        output, passed = "grading timed out", False
    return passed, "\n".join(output.strip().splitlines()[-15:])


def run_task(
    task_dir: Path,
    model: ChatModel,
    settings: Settings,
    log_path: Path,
    use_checks: bool = True,
    use_mcp: bool = True,
) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"eval-{task_dir.name}-") as tmp:
        work, remote = Path(tmp) / "repo", Path(tmp) / "origin.git"
        setup_task(task_dir, work, remote)
        ws = Workspace(work)
        before = ws.snapshot()

        # Tasks with services-up.sh run real services (e.g. Docker Compose) during the run.
        # Each run gets its own id, so parallel runs and their MCP servers do not mix.
        run_id = f"eval-{task_dir.name}-{uuid.uuid4().hex[:8]}"
        up, down = task_dir / "services-up.sh", task_dir / "services-down.sh"
        mcp = task_dir / "mcp.json"
        servers = []
        if use_mcp and mcp.exists():
            servers = [
                dataclasses.replace(s, variables={"EVAL_RUN_ID": run_id}) for s in load_mcp_config(mcp)
            ]
        try:
            if up.exists() and servers:
                run_script(up, work, {"EVAL_RUN_ID": run_id}, timeout=SERVICES_TIMEOUT)
            checks = task_checks(task_dir) if use_checks else None
            result = run_agent(
                (task_dir / "task.md").read_text(), ws, model, settings, log_path=log_path, checks=checks,
                mcp_servers=servers or None,
            )  # fmt: skip
        finally:
            if down.exists():
                run_script(down, work, {"EVAL_RUN_ID": run_id}, timeout=120, check=False)
        diff = changes(before, ws.snapshot())

        # The agent must not pass by removing tests: put those files back before grading.
        tampered = tampered_tests(task_dir / "repo", work, diff)
        for rel in tampered:
            shutil.copy2(task_dir / "repo" / rel, work / rel)

        passed, tail = grade(work, task_dir, remote if remote.exists() else None)
        return {
            "task": task_dir.name,
            "passed": passed and not tampered,
            "status": result.status,
            "steps": result.steps,
            "tool_calls": result.tool_calls,
            "tool_errors": result.tool_errors,
            "seconds": round(result.seconds, 1),
            "compactions": result.compactions,
            "usage": result.usage.to_dict(),
            "changed": diff,
            "tampered_tests": tampered,
            "summary": result.summary,
            "pytest": tail,
            "log": str(log_path),
        }


def run_one(
    task_dir: Path,
    run: int,
    model: ChatModel,
    settings: Settings,
    out: Path,
    use_checks: bool = True,
    use_mcp: bool = True,
) -> dict:
    """run_task, but a crash becomes a failed row instead of stopping the whole eval."""
    try:
        row = run_task(task_dir, model, settings, out / f"{task_dir.name}-{run}.jsonl", use_checks, use_mcp)
    except Exception as e:  # noqa: BLE001 - any crash is recorded as a failed run
        row = {"task": task_dir.name, "passed": False, "status": "crashed", "steps": 0, "tool_calls": 0,
               "tool_errors": 0, "seconds": 0.0, "usage": Usage().to_dict(), "summary": repr(e)}  # fmt: skip
    return {**row, "run": run}


def summarize(rows: list[dict], wall_seconds: float, jobs: int) -> dict:
    usage = Usage()
    for r in rows:
        usage.add(Usage(**{k: v for k, v in r["usage"].items() if k != "output_tps"}))
    passed = sum(r["passed"] for r in rows)
    return {
        "passed": passed,
        "runs": len(rows),
        "pass_rate": round(passed / len(rows), 3),
        "jobs": jobs,
        "wall_seconds": round(wall_seconds, 1),
        # Total generated tokens over wall time: rises with batching even when per-request speed drops.
        "throughput_tps": round(usage.output_tokens / wall_seconds, 1) if wall_seconds else 0.0,
        "per_request_tps": round(usage.output_tps, 1),
        "peak_context": usage.peak_context,
        "usage": usage.to_dict(),
    }


def print_table(rows: list[dict], summary: dict, num_ctx: int) -> None:
    header = f"{'task':<22} {'run':>3} {'pass':<4} {'status':<13} {'steps':>5} {'err':>3} {'secs':>6} {'tokens out':>10} {'peak ctx':>8} {'tok/s':>6}"
    print("\n" + header)
    for r in rows:
        u = r["usage"]
        mark = "yes" if r["passed"] else "NO"
        print(
            f"{r['task']:<22} {r['run']:>3} {mark:<4} {r['status']:<13} {r['steps']:>5} {r['tool_errors']:>3} "
            f"{r['seconds']:>6} {u['output_tokens']:>10,} {u['peak_context']:>8,} {u['output_tps']:>6}"
        )
    s = summary
    print(
        f"\npassed {s['passed']}/{s['runs']} ({s['pass_rate']:.0%}) | jobs {s['jobs']} | wall {s['wall_seconds']:.0f}s | "
        f"throughput {s['throughput_tps']} tok/s (per request {s['per_request_tps']}) | "
        f"peak context {s['peak_context']:,} of {num_ctx:,}"
    )


def code_version() -> str:
    """Commit the eval ran on, +dirty with uncommitted changes to the agent or tasks."""
    git = ["git", "-C", str(EVALS.parent)]
    sha = subprocess.run([*git, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False)
    dirty = subprocess.run(
        [*git, "status", "--porcelain", "--", "src", "evals/tasks"],
        capture_output=True,
        text=True,
        check=False,
    )
    return sha.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LocalAgents evals.")
    parser.add_argument("--model", help=f"Ollama model. Default: {Settings().model}.")
    parser.add_argument("--repeats", type=int, default=1, help="Runs per task (results vary between runs).")
    parser.add_argument(
        "--task", action="append", help="Only run tasks matching this name or glob, e.g. 'git-*'."
    )
    parser.add_argument("--git-backend", choices=GIT_BACKENDS, help="Which git tools the model gets.")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument(
        "--num-ctx", type=int, help=f"Context window in tokens. Default: {Settings().num_ctx}."
    )
    parser.add_argument(
        "--jobs", type=int, default=1,
        help="Runs in parallel. Only faster if Ollama serves that many at once (OLLAMA_NUM_PARALLEL).",
    )  # fmt: skip
    parser.add_argument("--think", choices=THINK_CHOICES, help="Model reasoning before each reply.")
    parser.add_argument(
        "--no-mcp", action="store_true", help="Do not start the tasks' MCP servers (mcp.json)."
    )
    parser.add_argument(
        "--no-context", action="store_true", help="Ignore AGENTS.md / CLAUDE.md in the tasks."
    )
    parser.add_argument(
        "--no-checks", action="store_true", help="Let the agent finish without running the done checks."
    )
    args = parser.parse_args()

    overrides = {
        "model": args.model,
        "max_steps": args.max_steps,
        "num_ctx": args.num_ctx,
        "think": parse_think(args.think),
        "git_backend": args.git_backend,
    }
    settings = dataclasses.replace(Settings(), **{k: v for k, v in overrides.items() if v is not None})
    if args.no_context:
        settings = dataclasses.replace(settings, project_context=False)
    model = OllamaModel(settings)

    task_dirs = sorted(d for d in TASKS.iterdir() if (d / "task.md").exists())
    if args.task:
        task_dirs = [d for d in task_dirs if any(fnmatch.fnmatch(d.name, pattern) for pattern in args.task)]
        if not task_dirs:
            sys.exit(f"No such task. Available: {', '.join(d.name for d in sorted(TASKS.iterdir()))}")

    label = settings.model.replace(":", "_").replace("/", "_") + (
        f"-think-{args.think}" if args.think else ""
    )
    label += f"-git-{settings.git_backend}" if args.git_backend else ""
    label += "-no-checks" if args.no_checks else ""
    label += "-no-context" if args.no_context else ""
    label += "-no-mcp" if args.no_mcp else ""
    out = RESULTS / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}"
    out.mkdir(parents=True)
    work = [(task_dir, run) for task_dir in task_dirs for run in range(1, args.repeats + 1)]
    print(
        f"{len(work)} runs, {args.jobs} at a time, model {settings.model}, num_ctx {settings.num_ctx}, think {settings.think}, git {settings.git_backend}, checks {not args.no_checks}",
        flush=True,
    )

    started = time.monotonic()
    rows = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [
            pool.submit(run_one, task_dir, run, model, settings, out, not args.no_checks, not args.no_mcp)
            for task_dir, run in work
        ]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            verdict = "PASS" if row["passed"] else "FAIL"
            print(f"[{len(rows)}/{len(work)}] {verdict} {row['task']} #{row['run']} ({row['status']}, "
                  f"{row['steps']} steps, {row['seconds']:.0f}s)", flush=True)  # fmt: skip

    rows.sort(key=lambda r: (r["task"], r["run"]))
    summary = summarize(rows, time.monotonic() - started, args.jobs)
    (out / "results.json").write_text(
        json.dumps(
            {
                "settings": dataclasses.asdict(settings),
                "checks": not args.no_checks,
                "mcp": not args.no_mcp,
                "commit": code_version(),
                "summary": summary,
                "runs": rows,
            },
            indent=2,
        )
    )
    print_table(rows, summary, settings.num_ctx)
    print(f"details: {out}")


if __name__ == "__main__":
    main()
