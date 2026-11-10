"""The agent loop: model -> tool calls -> results -> model, until finish or the step cap."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from localagents.checks import Checks, run_checks
from localagents.config import Settings
from localagents.llm import USAGE_KEY, ChatModel, Message, ModelError, Usage
from localagents.prompts import SYSTEM_PROMPT
from localagents.tools import ToolError, build_tools
from localagents.workspace import Workspace

MAX_NUDGES = 3  # replies in a row without a tool call before giving up

NUDGE = "Reply with a tool call. If the task is done and checked, call finish with a summary."

MAX_FINISH_REFUSALS = 3  # finish refused by the checks this many times ends the run
REPEAT_HINT_AT = 2  # the same failing call this many times gets a hint...
REPEAT_STOP_AT = 4  # ...and this many times ends the run
REPEAT_HINT = (
    "You already made this exact call and it failed the same way. Do not repeat it. "
    "Read the file again (read_file) to see its exact current text, or try another approach."
)

TRIM_MIN_CHARS = 600  # old tool outputs longer than this get cut when compacting
TRIM_KEEP_CHARS = 300
TRIMMED = "[older output trimmed to save context; run the tool again if you need it]"

Event = dict[str, Any]


@dataclass
class AgentResult:
    status: Literal["finished", "step_limit", "stalled", "stuck", "checks_failed", "error"]
    summary: str
    steps: int
    tool_calls: int = 0
    tool_errors: int = 0
    seconds: float = 0.0
    usage: Usage = field(default_factory=Usage)
    messages: list[Message] = field(default_factory=list)
    compactions: int = 0


def _arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments arrive as a dict, but some models send a JSON string."""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ToolError(f"Arguments are not valid JSON: {e}") from e
    if not isinstance(raw, dict):
        raise ToolError("Arguments must be a JSON object.")
    return raw


def _context_size(messages: list[Message]) -> int:
    """Rough token count (4 chars per token), for models that report no usage."""
    return sum(len(str(m.get("content") or "")) + len(str(m.get("thinking") or "")) for m in messages) // 4


def compact(messages: list[Message], keep_recent: int) -> int:
    """Shrink what the model no longer needs: long old tool outputs and old reasoning.
    The system prompt, the task and the last `keep_recent` messages stay as they are.
    Returns how many characters were removed."""
    saved = 0
    for message in messages[2:-keep_recent]:
        if message.get("thinking"):
            saved += len(message.pop("thinking"))
        content = message.get("content") or ""
        if message["role"] == "tool" and len(content) > TRIM_MIN_CHARS and TRIMMED not in content:
            message["content"] = f"{content[:TRIM_KEEP_CHARS]}\n{TRIMMED}"
            saved += len(content) - len(message["content"])
    return saved


def run_agent(
    task: str,
    workspace: Workspace,
    model: ChatModel,
    settings: Settings,
    log_path: Path | None = None,
    on_event: Callable[[Event], None] | None = None,
    checks: Checks | None = None,
) -> AgentResult:
    """Solve `task` in `workspace`. Each step is appended to `log_path` as JSONL.

    `checks` run when the model calls finish; finish is refused until they pass."""
    tools = build_tools(workspace, settings)
    schemas = [tool.schema() for tool in tools.values()]
    messages: list[Message] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{task.rstrip()}\n\n{checks.describe()}" if checks else task},
    ]
    started = time.monotonic()
    calls = errors = nudges = refusals = compactions = 0
    failed_calls: dict[str, int] = {}
    usage = Usage()

    def emit(event: Event) -> None:
        if log_path:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        if on_event:
            on_event(event)

    def result(status, summary: str, steps: int) -> AgentResult:
        emit({"type": "end", "status": status, "summary": summary, "steps": steps, "usage": usage.to_dict()})
        return AgentResult(
            status, summary, steps, calls, errors, time.monotonic() - started, usage, messages, compactions
        )

    for step in range(1, settings.max_steps + 1):
        try:
            reply = model.chat(messages, schemas)
        except ModelError as e:
            return result("error", str(e), step)
        step_usage = reply.pop(USAGE_KEY, None)
        if step_usage:
            usage.add(step_usage)
        messages.append(reply)
        size = step_usage.peak_context if step_usage else _context_size(messages)
        if size > settings.compact_at * settings.num_ctx:
            saved = compact(messages, settings.keep_recent)
            if saved:
                compactions += 1
                emit({"type": "compact", "step": step, "context": size, "saved_chars": saved})
        emit(
            {
                "type": "assistant",
                "step": step,
                "message": reply,
                "usage": step_usage.to_dict() if step_usage else None,
            }
        )

        tool_calls = reply.get("tool_calls") or []
        if not tool_calls:
            nudges += 1
            if nudges >= MAX_NUDGES:
                return result("stalled", reply.get("content") or "Model stopped calling tools.", step)
            messages.append({"role": "user", "content": NUDGE})
            continue
        nudges = 0

        for call in tool_calls:
            function = call.get("function", {})
            name = function.get("name", "")
            calls += 1
            try:
                tool = tools.get(name)
                if tool is None:
                    raise ToolError(f"Unknown tool {name!r}. Available: {', '.join(tools)}.")
                output = tool.call(_arguments(function.get("arguments")))
                ok = True
            except ToolError as e:
                output, ok = f"Error: {e}", False
                errors += 1
            repeats = 0
            if not ok:
                key = f"{name} {json.dumps(function.get('arguments'), sort_keys=True, default=str)}"
                repeats = failed_calls[key] = failed_calls.get(key, 0) + 1
                if repeats >= REPEAT_HINT_AT:
                    output += f"\n{REPEAT_HINT}"
            finish_failures = (
                run_checks(workspace, settings, checks) if name == "finish" and ok and checks else []
            )
            if finish_failures:
                refusals += 1
                errors += 1
                ok = False
                output = "Error: finish refused, these checks failed:\n" + "\n".join(
                    f"- {f}" for f in finish_failures
                )
            messages.append({"role": "tool", "tool_name": name, "content": output})
            emit(
                {
                    "type": "tool",
                    "step": step,
                    "name": name,
                    "arguments": function.get("arguments"),
                    "ok": ok,
                    "output": output,
                }
            )
            if name == "finish" and ok:
                return result("finished", output, step)
            if refusals >= MAX_FINISH_REFUSALS:
                return result("checks_failed", output, step)
            if repeats >= REPEAT_STOP_AT:
                return result(
                    "stuck", f"Stopped: the model repeated a failing {name} call {repeats} times.", step
                )

    return result(
        "step_limit", f"Stopped after {settings.max_steps} steps without calling finish.", settings.max_steps
    )
