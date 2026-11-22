import dataclasses

from localagents.agent import run_agent
from localagents.context import MAX_ROOT_CHARS, FolderInstructions, project_instructions
from tests.fakes import FakeModel
from tests.test_agent import call


def test_no_context_file(ws):
    assert project_instructions(ws) is None


def test_agents_md_wins_over_claude_md(ws):
    (ws.root / "CLAUDE.md").write_text("from claude")
    assert "from claude" in project_instructions(ws)
    (ws.root / "AGENTS.md").write_text("Run tests with `make test`.\n")
    text = project_instructions(ws)
    assert text.startswith("Project instructions from AGENTS.md")
    assert text.endswith("Run tests with `make test`.") and "from claude" not in text


def test_long_file_is_cut(ws):
    (ws.root / "AGENTS.md").write_text("x" * (MAX_ROOT_CHARS + 500))
    text = project_instructions(ws)
    assert text.endswith(f"[... AGENTS.md cut at {MAX_ROOT_CHARS} characters]")
    assert len(text) < MAX_ROOT_CHARS + 200


def test_folder_instructions_once_per_folder(ws):
    (ws.root / "AGENTS.md").write_text("root rules")
    (ws.root / "legacy" / "old").mkdir(parents=True)
    (ws.root / "legacy" / "AGENTS.md").write_text("camelCase here")
    (ws.root / "legacy" / "old" / "CLAUDE.md").write_text("even older")
    (ws.root / "legacy" / "old" / "a.py").write_text("")
    folders = FolderInstructions(ws)

    assert folders.for_path("main.py") is None  # root rules are in the system prompt
    text = folders.for_path("legacy/old/a.py")
    assert text.index("legacy/AGENTS.md") < text.index("legacy/old/CLAUDE.md")
    assert "camelCase here" in text and "even older" in text
    assert folders.for_path("legacy/old/b.py") is None  # already shown
    assert folders.for_path("../outside.py") is None


def test_agent_gets_root_and_folder_instructions(ws, settings):
    (ws.root / "AGENTS.md").write_text("Always run make check.")
    (ws.root / "pkg").mkdir()
    (ws.root / "pkg" / "AGENTS.md").write_text("Use tabs in pkg.")
    (ws.root / "pkg" / "m.py").write_text("x = 1\n")
    model = FakeModel(
        [call("read_file", path="pkg/m.py"), call("read_file", path="pkg/m.py"), call("finish", summary="ok")]
    )
    run_agent("t", ws, model, settings)

    assert model.calls[0][0]["content"].endswith("Always run make check.")
    first, second = model.calls[1][-1]["content"], model.calls[2][-1]["content"]
    assert first.startswith("    1\tx = 1") and first.endswith("Use tabs in pkg.")
    assert "Use tabs" not in second


def test_context_can_be_turned_off(ws, settings):
    (ws.root / "AGENTS.md").write_text("Always run make check.")
    model = FakeModel([call("finish", summary="ok")])
    run_agent("t", ws, model, dataclasses.replace(settings, project_context=False))
    assert "make check" not in model.calls[0][0]["content"]
