# LocalAgents

A coding agent that runs on local Ollama models (default `gpt-oss:20b`), plus unit tests and evals.

## Layout

```
src/localagents/
  config.py        Settings (model, num_ctx, step cap, timeouts)
  workspace.py     Confines every path to one project folder
  llm.py           ChatModel protocol + OllamaModel
  prompts.py       System prompt
  agent.py         The loop: model -> tool calls -> results, until finish / step cap
  tools/
    __init__.py    Tool registry and Ollama tool schemas
    files.py       read_file, write_file, edit_file, list_files
    search.py      search (ripgrep)
    shell.py       run_command (bubblewrap, timeout, output truncation)
    git.py         git_status, git_diff, git_log, git_commit, git_restore, git_create_branch
                   (only offered when the workspace is a git repository)
  mcp_server.py    Exposes run_local_agent(task, workdir) to Claude Code
  cli.py           `localagents run "task" --workdir PATH`
tests/             Unit tests; fakes.py has a scripted FakeModel (no Ollama needed)
evals/
  runner.py        Runs tasks, grades with hidden tests, writes evals/results/
  tasks/<name>/
    task.md        Prompt the agent sees
    repo/          Starting code
    hidden_tests/  Grading tests, copied in only after the agent finishes
```

## Setup

```bash
uv add ollama mcp
uv add --dev pytest pytest-timeout ruff
export OLLAMA_CONTEXT_LENGTH=16384
```

## Commands

```bash
uv run pytest                                             # unit tests (no Ollama needed)
uv run localagents run "fix the failing test" --workdir ~/some/project
uv run python evals/runner.py                             # all evals, default model
uv run python evals/runner.py --model qwen3:8b --repeats 3 --task fix-pagination
```

Eval results and per-run JSONL trajectories go to `evals/results/<timestamp>-<model>/`.

## Use from Claude Code

```bash
claude mcp add --scope user localagents -- uv run --project /path/to/LocalAgents localagents-mcp
```

This adds a `run_local_agent(task, workdir)` tool. `workdir` must be an absolute path.

## Safety

- Every path is checked against the workspace root (no absolute paths, `..` or outbound symlinks),
  and `.git/` is off limits to the file tools.
- `run_command` runs under bubblewrap: read-only system, writable workspace and `/tmp`, no network,
  killed after `command_timeout` seconds. A small deny list rejects obviously dangerous commands.
- Git commands run inside the same sandbox. The agent can edit `.git/config` from the shell, and
  settings such as `core.fsmonitor` execute commands, so git never gets more access than the agent.
  There is no push, pull, reset or rebase. Agent commits are authored by
  `LocalAgents (<model>)`, with you as the committer.
