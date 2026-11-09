"""The agent loop: model -> tool calls -> results -> model, until finish or the step cap."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from localagents.config import Settings
from localagents.llm import USAGE_KEY, ChatModel, Message, ModelError, Usage
from localagents.prompts import SYSTEM_PROMPT
from localagents.tools import ToolError, build_tools
from localagents.workspace import Workspace

MAX_NUDGES = 3  # replies in a row without a tool call before giving up

NUDGE = "Reply with a tool call. If the task is done and checked, call finish with a summary."

Event = dict[str, Any]


@dataclass
class AgentResult:
    status: Literal["finished", "step_limit", "stalled", "error"]
    summary: str
    steps: int
    tool_calls: int = 0
    tool_errors: int = 0
    seconds: float = 0.0
    usage: Usage = field(default_factory=Usage)
    messages: list[Message] = field(default_factory=list)


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


def run_agent(
    task: str,
    workspace: Workspace,
    model: ChatModel,
    settings: Settings,
    log_path: Path | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> AgentResult:
    """Solve `task` in `workspace`. Each step is appended to `log_path` as JSONL."""
    tools = build_tools(workspace, settings)
    schemas = [tool.schema() for tool in tools.values()]
    messages: list[Message] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    started = time.monotonic()
    calls = errors = nudges = 0
    usage = Usage()

    def emit(event: Event) -> None:
        if log_path:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        if on_event:
            on_event(event)

    def result(status, summary: str, steps: int) -> AgentResult:
        emit({"type": "end", "status": status, "summary": summary, "steps": steps, "usage": usage.to_dict()})
        return AgentResult(status, summary, steps, calls, errors, time.monotonic() - started, usage, messages)

    for step in range(1, settings.max_steps + 1):
        try:
            reply = model.chat(messages, schemas)
        except ModelError as e:
            return result("error", str(e), step)
        step_usage = reply.pop(USAGE_KEY, None)
        if step_usage:
            usage.add(step_usage)
        messages.append(reply)
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

    return result(
        "step_limit", f"Stopped after {settings.max_steps} steps without calling finish.", settings.max_steps
    )
