import ollama
import pytest

from localagents.config import Settings
from localagents.llm import USAGE_KEY, ModelError, OllamaModel, Usage, usage_from


def response(**counts):
    return ollama.ChatResponse(model="m", message=ollama.Message(role="assistant", content="hi"), **counts)


def test_usage_from_response():
    u = usage_from(
        response(
            prompt_eval_count=1000,
            eval_count=50,
            prompt_eval_duration=2e9,
            eval_duration=5e9,
            load_duration=1e9,
        )
    )
    assert (u.calls, u.prompt_tokens, u.output_tokens, u.peak_context) == (1, 1000, 50, 1050)
    assert (u.prompt_seconds, u.output_seconds, u.load_seconds) == (2.0, 5.0, 1.0)
    assert u.output_tps == 10.0


def test_usage_from_response_without_counts():
    assert usage_from(response()) == Usage(calls=1)


def test_add_sums_and_keeps_peak():
    total = Usage()
    total.add(Usage(calls=1, prompt_tokens=100, output_tokens=10, peak_context=110, output_seconds=1.0))
    total.add(Usage(calls=1, prompt_tokens=300, output_tokens=30, peak_context=330, output_seconds=1.0))
    assert (total.calls, total.prompt_tokens, total.output_tokens, total.peak_context) == (2, 400, 40, 330)
    assert total.output_tps == 20.0
    assert total.to_dict()["output_tps"] == 20.0


def test_describe():
    line = Usage(
        calls=2, prompt_tokens=12000, output_tokens=345, peak_context=6100, output_seconds=23.0
    ).describe(65536)
    assert "2 model calls" in line and "12,000 prompt" in line and "peak context 6,100 of 65,536" in line
    assert "15.0 tok/s" in line


def test_ollama_model_attaches_usage(monkeypatch):
    model = OllamaModel(Settings())
    sent = {}

    def fake_chat(**kwargs):
        sent.update(kwargs)
        return response(prompt_eval_count=10, eval_count=2)

    monkeypatch.setattr(model.client, "chat", fake_chat)
    message = model.chat([{"role": "user", "content": "x"}], [])
    assert message["content"] == "hi"
    assert message[USAGE_KEY].peak_context == 12
    assert sent["options"]["num_ctx"] == Settings().num_ctx


def fail_then_answer(failures, error="error parsing tool call: raw='{bad'"):
    seen = []

    def fake_chat(**kwargs):
        seen.append(kwargs["options"]["temperature"])
        if len(seen) <= failures:
            raise ollama.ResponseError(error, 500)
        return response(prompt_eval_count=1, eval_count=1)

    return fake_chat, seen


def test_retries_malformed_tool_calls(monkeypatch):
    model = OllamaModel(Settings(temperature=0.2, model_retries=2))
    fake, temperatures = fail_then_answer(2)
    monkeypatch.setattr(model.client, "chat", fake)
    message = model.chat([], [])
    assert message[USAGE_KEY].retries == 2
    assert temperatures == pytest.approx([0.2, 0.5, 0.8])


def test_gives_up_after_retries(monkeypatch):
    model = OllamaModel(Settings(model_retries=1))
    fake, temperatures = fail_then_answer(5)
    monkeypatch.setattr(model.client, "chat", fake)
    with pytest.raises(ModelError, match="error parsing tool call"):
        model.chat([], [])
    assert len(temperatures) == 2


def test_other_errors_are_not_retried(monkeypatch):
    model = OllamaModel(Settings(model_retries=2))
    fake, temperatures = fail_then_answer(5, error="model 'nope' not found")
    monkeypatch.setattr(model.client, "chat", fake)
    with pytest.raises(ModelError, match="not found"):
        model.chat([], [])
    assert len(temperatures) == 1


def test_think_setting_is_sent(monkeypatch):
    from localagents.config import parse_think

    assert [parse_think(v) for v in (None, "on", "off", "low")] == [None, True, False, "low"]
    for think in (None, False, "low"):
        model = OllamaModel(Settings(think=think))
        sent = {}
        monkeypatch.setattr(model.client, "chat", lambda sent=sent, **kw: sent.update(kw) or response())
        model.chat([], [])
        assert sent["think"] == think
