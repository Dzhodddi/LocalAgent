"""FakeModel: replays scripted assistant messages so loop tests need no Ollama."""

from typing import Any

from localagents.llm import Message


class FakeModel:
    def __init__(self, script: list[Message]):
        self.script = list(script)
        self.calls: list[list[Message]] = []  # messages seen on each call, for assertions

    def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> Message:
        self.calls.append(list(messages))
        if not self.script:
            raise AssertionError("FakeModel ran out of scripted responses")
        return self.script.pop(0)
