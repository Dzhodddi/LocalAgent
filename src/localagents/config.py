"""Settings shared by the agent, tools and evals."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    ollama_host: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model: str = os.environ.get("LOCALAGENTS_MODEL", "gpt-oss:20b")
    num_ctx: int = (
        16384  # measured peak was ~6.7k tokens; keep equal to OLLAMA_CONTEXT_LENGTH to avoid reloads
    )
    temperature: float = 0.2
    max_steps: int = 30
    command_timeout: float = 60.0
    max_output_chars: int = 8000
    sandbox: bool = True  # run_command under bubblewrap: read-only system, no network
    model_timeout: float = 600.0  # seconds for one model response
    model_retries: int = 2  # extra attempts when Ollama cannot parse the model's tool call
    # Reasoning before each reply: None = model default, True/False (e.g. qwen3), or a level
    # "low"/"medium"/"high" (gpt-oss, which cannot turn it off).
    think: bool | str | None = None
    git_backend: str = "native"  # which git tools the model gets; see tools.build_tools
    protected_branches: tuple[str, ...] = ("main", "master")  # git_push refuses these
    # Trailer added to every agent commit ({model} is filled in); "" turns it off.
    commit_trailer: str = os.environ.get(
        "LOCALAGENTS_COMMIT_TRAILER", "Generated-by: local LLM {model} via LocalAgents"
    )


THINK_CHOICES = ("on", "off", "low", "medium", "high")
GIT_BACKENDS = ("native",)  # git tool sets the model can be given


def parse_think(value: str | None) -> bool | str | None:
    """CLI value -> Settings.think."""
    return {"on": True, "off": False}.get(value, value) if value else None
