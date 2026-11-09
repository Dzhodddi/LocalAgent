"""Eval runner.

For each task in evals/tasks/<name>/:
  1. copy repo/ into a fresh temp folder
  2. run the agent on task.md (step cap + time limit)
  3. restore the original test files, copy hidden_tests/ in AFTER the run and run pytest
  4. write results + JSONL trajectories to evals/results/<timestamp>/

Usage: uv run python evals/runner.py [--model M] [--repeats N] [--task NAME] [--jobs N] [--num-ctx N]
"""

import argparse
import dataclasses
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from localagents.agent import run_agent
from localagents.config import THINK_CHOICES, Settings, parse_think
from localagents.llm import ChatModel, OllamaModel, Usage
from localagents.workspace import Workspace, changes

EVALS = Path(__file__).parent
TASKS = EVALS / "tasks"
RESULTS = EVALS / "results"
GRADE_TIMEOUT = 120


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


def grade(work: Path, task_dir: Path) -> tuple[bool, str]:
    """Run visible + hidden tests on the agent's result. Returns (passed, pytest tail)."""
    hidden = work / "hidden_tests"
    shutil.copytree(task_dir / "hidden_tests", hidden)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=30"],
            check=False, cwd=work, capture_output=True, text=True, timeout=GRADE_TIMEOUT,
        )  # fmt: skip
        output, passed = proc.stdout + proc.stderr, proc.returncode == 0
    except subprocess.TimeoutExpired:
        output, passed = "grading timed out", False
    return passed, "\n".join(output.strip().splitlines()[-15:])


def run_task(task_dir: Path, model: ChatModel, settings: Settings, log_path: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"eval-{task_dir.name}-") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(task_dir / "repo", work)
        ws = Workspace(work)
        before = ws.snapshot()

        result = run_agent((task_dir / "task.md").read_text(), ws, model, settings, log_path=log_path)
        diff = changes(before, ws.snapshot())

        # The agent must not pass by removing tests: put those files back before grading.
        tampered = tampered_tests(task_dir / "repo", work, diff)
        for rel in tampered:
            shutil.copy2(task_dir / "repo" / rel, work / rel)

        passed, tail = grade(work, task_dir)
        return {
            "task": task_dir.name,
            "passed": passed and not tampered,
            "status": result.status,
            "steps": result.steps,
            "tool_calls": result.tool_calls,
            "tool_errors": result.tool_errors,
            "seconds": round(result.seconds, 1),
            "usage": result.usage.to_dict(),
            "changed": diff,
            "tampered_tests": tampered,
            "summary": result.summary,
            "pytest": tail,
            "log": str(log_path),
        }


def run_one(task_dir: Path, run: int, model: ChatModel, settings: Settings, out: Path) -> dict:
    """run_task, but a crash becomes a failed row instead of stopping the whole eval."""
    try:
        row = run_task(task_dir, model, settings, out / f"{task_dir.name}-{run}.jsonl")
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
    header = f"{'task':<22} {'run':>3} {'pass':<4} {'status':<10} {'steps':>5} {'err':>3} {'secs':>6} {'tokens out':>10} {'peak ctx':>8} {'tok/s':>6}"
    print("\n" + header)
    for r in rows:
        u = r["usage"]
        mark = "yes" if r["passed"] else "NO"
        print(
            f"{r['task']:<22} {r['run']:>3} {mark:<4} {r['status']:<10} {r['steps']:>5} {r['tool_errors']:>3} "
            f"{r['seconds']:>6} {u['output_tokens']:>10,} {u['peak_context']:>8,} {u['output_tps']:>6}"
        )
    s = summary
    print(
        f"\npassed {s['passed']}/{s['runs']} ({s['pass_rate']:.0%}) | jobs {s['jobs']} | wall {s['wall_seconds']:.0f}s | "
        f"throughput {s['throughput_tps']} tok/s (per request {s['per_request_tps']}) | "
        f"peak context {s['peak_context']:,} of {num_ctx:,}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LocalAgents evals.")
    parser.add_argument("--model", help=f"Ollama model. Default: {Settings().model}.")
    parser.add_argument("--repeats", type=int, default=1, help="Runs per task (results vary between runs).")
    parser.add_argument("--task", action="append", help="Only run this task (repeatable).")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument(
        "--num-ctx", type=int, help=f"Context window in tokens. Default: {Settings().num_ctx}."
    )
    parser.add_argument(
        "--jobs", type=int, default=1,
        help="Runs in parallel. Only faster if Ollama serves that many at once (OLLAMA_NUM_PARALLEL).",
    )  # fmt: skip
    parser.add_argument("--think", choices=THINK_CHOICES, help="Model reasoning before each reply.")
    args = parser.parse_args()

    overrides = {
        "model": args.model,
        "max_steps": args.max_steps,
        "num_ctx": args.num_ctx,
        "think": parse_think(args.think),
    }
    settings = dataclasses.replace(Settings(), **{k: v for k, v in overrides.items() if v is not None})
    model = OllamaModel(settings)

    task_dirs = sorted(d for d in TASKS.iterdir() if (d / "task.md").exists())
    if args.task:
        task_dirs = [d for d in task_dirs if d.name in args.task]
        if not task_dirs:
            sys.exit(f"No such task. Available: {', '.join(d.name for d in sorted(TASKS.iterdir()))}")

    label = settings.model.replace(":", "_").replace("/", "_") + (
        f"-think-{args.think}" if args.think else ""
    )
    out = RESULTS / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}"
    out.mkdir(parents=True)
    work = [(task_dir, run) for task_dir in task_dirs for run in range(1, args.repeats + 1)]
    print(
        f"{len(work)} runs, {args.jobs} at a time, model {settings.model}, num_ctx {settings.num_ctx}, think {settings.think}",
        flush=True,
    )

    started = time.monotonic()
    rows = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_one, task_dir, run, model, settings, out) for task_dir, run in work]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            verdict = "PASS" if row["passed"] else "FAIL"
            print(f"[{len(rows)}/{len(work)}] {verdict} {row['task']} #{row['run']} ({row['status']}, "
                  f"{row['steps']} steps, {row['seconds']:.0f}s)", flush=True)  # fmt: skip

    rows.sort(key=lambda r: (r["task"], r["run"]))
    summary = summarize(rows, time.monotonic() - started, args.jobs)
    (out / "results.json").write_text(
        json.dumps({"settings": dataclasses.asdict(settings), "summary": summary, "runs": rows}, indent=2)
    )
    print_table(rows, summary, settings.num_ctx)
    print(f"details: {out}")


if __name__ == "__main__":
    main()
