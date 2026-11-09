"""Model interface. The agent depends on `ChatModel`, so tests can swap in a fake."""

from dataclasses import asdict, dataclass
from typing import Any, Protocol

import ollama

from localagents.config import Settings

Message = dict[str, Any]  # {"role": ..., "content": ..., "tool_calls": [...]}

TOOL_PARSE_ERROR = "error parsing tool call"  # Ollama's 500 when the model writes malformed tool JSON
RETRY_TEMPERATURE_STEP = 0.3

USAGE_KEY = "usage"  # set on replies by models that report it; the agent removes it before resending


@dataclass
class Usage:
    """Token counts and timings for one or more model calls."""

    calls: int = 0
    prompt_tokens: int = 0  # full prompt length per call, cached part included
    output_tokens: int = 0
    peak_context: int = 0  # largest prompt + output in one call: what num_ctx must hold
    prompt_seconds: float = 0.0  # small when the prompt prefix was cached
    output_seconds: float = 0.0
    load_seconds: float = 0.0
    retries: int = 0  # requests repeated because the model wrote a tool call Ollama could not parse

    def add(self, other: "Usage") -> None:
        self.calls += other.calls
        self.prompt_tokens += other.prompt_tokens
        self.output_tokens += other.output_tokens
        self.peak_context = max(self.peak_context, other.peak_context)
        self.prompt_seconds += other.prompt_seconds
        self.output_seconds += other.output_seconds
        self.load_seconds += other.load_seconds
        self.retries += other.retries

    @property
    def output_tps(self) -> float:
        """Generation speed in tokens per second."""
        return self.output_tokens / self.output_seconds if self.output_seconds else 0.0

    def describe(self, num_ctx: int) -> str:
        """One line for people: totals, peak context against num_ctx, speed."""
        return (
            f"{self.calls} model calls, {self.prompt_tokens:,} prompt / {self.output_tokens:,} output tokens, "
            f"peak context {self.peak_context:,} of {num_ctx:,}, {self.output_tps:.1f} tok/s, "
            f"{self.prompt_seconds:.0f}s prompt + {self.output_seconds:.0f}s generation, "
            f"{self.retries} retries"
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "output_tps": round(self.output_tps, 1)}


class ModelError(Exception):
    """The model could not produce a response (Ollama down, unknown model, timeout)."""


class ChatModel(Protocol):
    def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> Message:
        """Return the assistant message (possibly with tool_calls)."""
        ...


class OllamaModel:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = ollama.Client(host=settings.ollama_host, timeout=settings.model_timeout)

    def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> Message:
        for attempt in range(self.settings.model_retries + 1):
            # Sample a little hotter on retries so the model doesn't repeat the same broken output.
            temperature = self.settings.temperature + RETRY_TEMPERATURE_STEP * attempt
            try:
                response = self.client.chat(
                    model=self.settings.model,
                    messages=messages,
                    tools=tools,
                    options={"num_ctx": self.settings.num_ctx, "temperature": temperature},
                    think=self.settings.think,
                )
                break
            except ollama.ResponseError as e:
                if TOOL_PARSE_ERROR in str(e.error) and attempt < self.settings.model_retries:
                    continue
                raise ModelError(f"Ollama error for {self.settings.model}: {e.error}") from e
            except Exception as e:  # connection refused, timeouts
                raise ModelError(f"Cannot reach Ollama at {self.settings.ollama_host}: {e}") from e
        # Keep `thinking`: reasoning models such as gpt-oss expect it back on later turns.
        message = response.message.model_dump(exclude_none=True)
        message[USAGE_KEY] = usage_from(response)
        message[USAGE_KEY].retries = attempt
        return message


def usage_from(response: ollama.ChatResponse) -> Usage:
    prompt, output = response.prompt_eval_count or 0, response.eval_count or 0
    return Usage(
        calls=1,
        prompt_tokens=prompt,
        output_tokens=output,
        peak_context=prompt + output,
        prompt_seconds=(response.prompt_eval_duration or 0) / 1e9,
        output_seconds=(response.eval_duration or 0) / 1e9,
        load_seconds=(response.load_duration or 0) / 1e9,
    )
