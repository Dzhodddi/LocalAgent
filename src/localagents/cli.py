"""Command line: `localagents run "task" --workdir PATH`."""

import argparse
import dataclasses
import sys
from pathlib import Path

from localagents.agent import Event, run_agent
from localagents.config import THINK_CHOICES, Settings, parse_think
from localagents.llm import OllamaModel
from localagents.workspace import Workspace, changes


def settings_from(args: argparse.Namespace) -> Settings:
    overrides = {
        "model": args.model,
        "max_steps": args.max_steps,
        "num_ctx": args.num_ctx,
        "think": parse_think(args.think),
    }
    if args.no_sandbox:
        overrides["sandbox"] = False
    return dataclasses.replace(Settings(), **{k: v for k, v in overrides.items() if v is not None})


def print_event(event: Event) -> None:
    """One short line per step on stderr, so you can watch the agent work."""
    if event["type"] == "assistant":
        text = (event["message"].get("content") or "").strip()
        if text:
            print(f"[{event['step']}] model: {text[:200]}", file=sys.stderr)
    elif event["type"] == "tool":
        mark = "ok " if event["ok"] else "ERR"
        first_line = event["output"].splitlines()[0] if event["output"] else ""
        print(
            f"[{event['step']}] {mark} {event['name']}({event['arguments']}) -> {first_line[:120]}",
            file=sys.stderr,
        )


def cmd_run(args: argparse.Namespace) -> int:
    task = Path(args.task_file).read_text() if args.task_file else args.task
    if not task:
        print("Give a task or --task-file.", file=sys.stderr)
        return 2
    workdir = Path(args.workdir)
    if not workdir.is_dir():
        print(f"Not a folder: {workdir}", file=sys.stderr)
        return 2

    settings = settings_from(args)
    ws = Workspace(workdir)
    before = ws.snapshot()
    result = run_agent(
        task, ws, OllamaModel(settings), settings,
        log_path=Path(args.log) if args.log else None,
        on_event=None if args.quiet else print_event,
    )  # fmt: skip

    diff = changes(before, ws.snapshot())
    print(f"\nstatus: {result.status} ({result.steps} steps, {result.tool_calls} tool calls, "
          f"{result.tool_errors} errors, {result.seconds:.0f}s, model {settings.model})")  # fmt: skip
    print(f"usage: {result.usage.describe(settings.num_ctx)}")
    for kind, paths in diff.items():
        for p in paths:
            print(f"  {kind}: {p}")
    print(f"\n{result.summary}")
    return 0 if result.status == "finished" else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="localagents", description="Coding agent on a local Ollama model.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the agent on a task.")
    run.add_argument("task", nargs="?", help="What to do.")
    run.add_argument("--task-file", help="Read the task from a file instead.")
    run.add_argument(
        "--workdir", default=".", help="Project folder the agent works in. Default: current folder."
    )
    run.add_argument("--model", help=f"Ollama model. Default: {Settings().model}.")
    run.add_argument("--max-steps", type=int, help=f"Step cap. Default: {Settings().max_steps}.")
    run.add_argument("--num-ctx", type=int, help=f"Context window in tokens. Default: {Settings().num_ctx}.")
    run.add_argument(
        "--think", choices=THINK_CHOICES, help="Model reasoning before each reply. Default: model default."
    )
    run.add_argument("--log", help="Write the full trajectory to this JSONL file.")
    run.add_argument("--no-sandbox", action="store_true", help="Run commands without bubblewrap.")
    run.add_argument("--quiet", action="store_true", help="Only print the result.")

    args = parser.parse_args()
    sys.exit(cmd_run(args))


if __name__ == "__main__":
    main()
