import json

from localagents.agent import MAX_NUDGES, run_agent
from localagents.llm import ModelError
from tests.fakes import FakeModel


def call(name, **arguments):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
    }


def text(content):
    return {"role": "assistant", "content": content}


def test_runs_tools_until_finish(ws, settings):
    model = FakeModel(
        [
            call("write_file", path="a.py", content="x = 1\n"),
            call("read_file", path="a.py"),
            call("finish", summary="Created a.py"),
        ]
    )
    result = run_agent("make a.py", ws, model, settings)

    assert (result.status, result.summary, result.steps) == ("finished", "Created a.py", 3)
    assert (result.tool_calls, result.tool_errors) == (3, 0)
    assert (ws.root / "a.py").read_text() == "x = 1\n"
    # The model saw the read_file result before its last turn.
    last_seen = model.calls[-1][-1]
    assert last_seen == {"role": "tool", "tool_name": "read_file", "content": "    1\tx = 1"}


def test_first_messages_are_system_and_task(ws, settings):
    model = FakeModel([call("finish", summary="done")])
    run_agent("the task", ws, model, settings)
    system, user = model.calls[0]
    assert system["role"] == "system"
    assert user == {"role": "user", "content": "the task"}


def test_tool_errors_go_back_to_the_model(ws, settings):
    model = FakeModel([call("read_file", path="missing.py"), call("finish", summary="ok")])
    result = run_agent("t", ws, model, settings)
    error = model.calls[1][-1]
    assert error["role"] == "tool"
    assert error["content"].startswith("Error: File not found")
    assert result.tool_errors == 1


def test_unknown_tool_and_bad_arguments(ws, settings):
    bad_json = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "list_files", "arguments": "{oops"}}],
    }
    model = FakeModel([call("delete_everything"), bad_json, call("finish", summary="ok")])
    result = run_agent("t", ws, model, settings)
    assert "Unknown tool 'delete_everything'" in model.calls[1][-1]["content"]
    assert "not valid JSON" in model.calls[2][-1]["content"]
    assert result.tool_errors == 2


def test_arguments_as_json_string(ws, settings):
    as_string = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "write_file", "arguments": json.dumps({"path": "a.txt", "content": "hi"})}}
        ],
    }
    run_agent("t", ws, FakeModel([as_string, call("finish", summary="ok")]), settings)
    assert (ws.root / "a.txt").read_text() == "hi"


def test_several_calls_in_one_reply(ws, settings):
    both = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "write_file", "arguments": {"path": "a.txt", "content": "1"}}},
            {"function": {"name": "write_file", "arguments": {"path": "b.txt", "content": "2"}}},
        ],
    }
    result = run_agent("t", ws, FakeModel([both, call("finish", summary="ok")]), settings)
    assert (ws.root / "a.txt").exists() and (ws.root / "b.txt").exists()
    assert result.tool_calls == 3


def test_finish_without_summary_does_not_stop(ws, settings):
    model = FakeModel([call("finish"), call("finish", summary="really done")])
    result = run_agent("t", ws, model, settings)
    assert result.summary == "really done"
    assert result.tool_errors == 1


def test_text_reply_gets_nudged(ws, settings):
    model = FakeModel([text("I will now edit the file."), call("finish", summary="ok")])
    result = run_agent("t", ws, model, settings)
    assert result.status == "finished"
    assert model.calls[1][-1]["role"] == "user"
    assert "tool call" in model.calls[1][-1]["content"]


def test_stalls_after_repeated_text_replies(ws, settings):
    model = FakeModel([text("hmm")] * MAX_NUDGES)
    result = run_agent("t", ws, model, settings)
    assert result.status == "stalled"
    assert result.steps == MAX_NUDGES


def test_step_limit(ws, settings):
    model = FakeModel([call("list_files")] * settings.max_steps)
    result = run_agent("t", ws, model, settings)
    assert result.status == "step_limit"
    assert result.steps == settings.max_steps


def test_model_error(ws, settings):
    class Broken:
        def chat(self, messages, tools):
            raise ModelError("Ollama is down")

    result = run_agent("t", ws, Broken(), settings)
    assert (result.status, result.summary) == ("error", "Ollama is down")


def test_writes_jsonl_log_and_events(ws, settings, tmp_path_factory):
    log = tmp_path_factory.mktemp("logs") / "run.jsonl"
    events = []
    run_agent(
        "t", ws, FakeModel([call("list_files"), call("finish", summary="ok")]), settings, log, events.append
    )
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert lines == events
    assert [e["type"] for e in lines] == ["assistant", "tool", "assistant", "tool", "end"]
    assert lines[-1]["status"] == "finished"


def test_sends_all_tool_schemas(ws, settings):
    seen = {}

    class Spy(FakeModel):
        def chat(self, messages, tools):
            seen["names"] = [t["function"]["name"] for t in tools]
            return super().chat(messages, tools)

    run_agent("t", ws, Spy([call("finish", summary="ok")]), settings)
    assert seen["names"] == [
        "read_file",
        "write_file",
        "edit_file",
        "list_files",
        "search",
        "run_command",
        "finish",
    ]


def test_usage_is_summed_and_not_sent_back(ws, settings, tmp_path_factory):
    from localagents.llm import USAGE_KEY, Usage

    first = call("list_files") | {
        USAGE_KEY: Usage(calls=1, prompt_tokens=500, output_tokens=20, peak_context=520)
    }
    last = call("finish", summary="ok") | {
        USAGE_KEY: Usage(calls=1, prompt_tokens=600, output_tokens=30, peak_context=630)
    }
    model = FakeModel([first, last])
    log = tmp_path_factory.mktemp("logs") / "run.jsonl"

    result = run_agent("t", ws, model, settings, log)

    assert (result.usage.calls, result.usage.output_tokens, result.usage.peak_context) == (2, 50, 630)
    assert all(USAGE_KEY not in m for m in model.calls[-1])  # never resent to the model
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert events[0]["usage"]["prompt_tokens"] == 500
    assert events[-1]["usage"]["output_tokens"] == 50
