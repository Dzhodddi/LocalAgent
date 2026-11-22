# LocalAgents

A coding agent that runs on local Ollama models (default `gpt-oss:20b`), plus unit tests and evals.

## Layout

```
src/localagents/
  config.py        Settings (model, num_ctx, step cap, timeouts)
  workspace.py     Confines every path to one project folder
  llm.py           ChatModel protocol + OllamaModel
  prompts.py       System prompt
  agent.py         The loop: model -> tool calls -> results, until finish / step cap;
                   repeat detector and context compaction
  context.py       Project instructions: AGENTS.md / CLAUDE.md, root and per folder
  checks.py        Done checks (commands, committed, pushed) run when the model calls finish
  tools/
    __init__.py    Tool registry and Ollama tool schemas
    files.py       read_file, write_file, edit_file, list_files
    search.py      search (ripgrep)
    shell.py       run_command (bubblewrap, timeout, output truncation)
    git.py         git_status, git_diff, git_log, git_commit, git_restore, git_create_branch
                   (only offered when the workspace is a git repository)
    remote.py      git_push (pinned remote, no force, no main/master) and
                   create_pull_request (GitHub remotes, via gh)
  mcp_server.py    Exposes run_local_agent(task, workdir) to Claude Code
  cli.py           `localagents run "task" --workdir PATH`
tests/             Unit tests; fakes.py has a scripted FakeModel (no Ollama needed)
evals/
  runner.py        Runs tasks, grades with hidden tests, writes evals/results/
  tasks/<name>/
    task.md        Prompt the agent sees
    repo/          Starting code
    hidden_tests/  Grading tests, copied in only after the agent finishes
    setup.sh       Optional: git history and a bare `origin` remote for git tasks
    checks.json    Optional done checks; default: the visible tests must pass
  reports/         Written comparisons of eval runs
scripts/
  bench_gpu.py     Ollama speed for different GPU layers / context / threads
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
uv run localagents run "fix the failing test" --workdir ~/some/project --check "python -m pytest -q"
uv run python evals/runner.py                             # all evals, default model
uv run python evals/runner.py --model qwen3:8b --repeats 3 --task fix-pagination
uv run python evals/runner.py --task 'git-*' --git-backend native   # git tasks use local bare remotes
uv run python evals/runner.py --no-checks                 # let the agent finish without done checks
uv run python evals/runner.py --task 'context-*' --repeats 5 --no-context   # A/B the project instructions
uv run python scripts/bench_gpu.py --num-gpu auto,20,24 --num-ctx 8192,16384
```

Eval results and per-run JSONL trajectories go to `evals/results/<timestamp>-<model>/`.

## Use from Claude Code

```bash
claude mcp add --scope user localagents -- uv run --project /path/to/LocalAgents localagents-mcp
```

This adds a `run_local_agent(task, workdir, check_commands, require_committed, require_pushed)`
tool. `workdir` must be an absolute path.

## Project instructions (AGENTS.md)

Like CLAUDE.md for Claude Code: put `AGENTS.md` (or `CLAUDE.md`) in the project, and the agent
follows it without you repeating the rules in every task.

- The root file goes into the system prompt, cut at 6,000 characters (~1.5k tokens).
- A file in a subfolder is added to a tool's output the first time the agent touches a path
  in that folder (cut at 3,000 characters), so folder rules cost nothing elsewhere.
- In a folder, `AGENTS.md` wins over `CLAUDE.md`. `--no-context` turns both off.

Write it for a small model: short, imperative, exact commands, no background reading.

```markdown
# Billing service
- Tests: `python -m pytest -q`. Lint: `ruff check .`
- Money is always `decimal.Decimal`, rounded with `ROUND_HALF_UP`.
- Every change gets a line in CHANGELOG.md under `## Unreleased`.
- Never edit `migrations/` by hand.
```

## How the agent copes with a small model

- **Done checks.** The caller says how to verify the work (`check_commands`, `--check`,
  `checks.json`); the checks are added to the task, and `finish` is refused with the failure
  until they pass. Three refusals end the run as `checks_failed`.
- **Repeat detector.** The same failing tool call twice gets a hint to re-read and change
  approach; four times ends the run as `stuck`.
- **Context compaction.** Past 60% of `num_ctx`, old tool outputs are cut to their first
  lines and old reasoning is dropped. The system prompt, task and last 6 messages stay whole.
- `read_file` stops at about 12k characters, so one read cannot fill the context.

## Safety

- Every path is checked against the workspace root (no absolute paths, `..` or outbound symlinks),
  and `.git/` is off limits to the file tools.
- `run_command` runs under bubblewrap: read-only system, writable workspace and `/tmp`, no network,
  killed after `command_timeout` seconds. A small deny list rejects obviously dangerous commands.
- Git commands run inside the same sandbox. The agent can edit `.git/config` from the shell, and
  settings such as `core.fsmonitor` execute commands, so git never gets more access than the agent.
  There is no pull, reset or rebase. Agent commits are authored by `LocalAgents (<model>)`,
  with you as the committer, and their messages end with a
  `Generated-by: local LLM <model> via LocalAgents` trailer (change it with
  `LOCALAGENTS_COMMIT_TRAILER`, using `{model}` for the model name; set it empty to turn it off).
- `git_push` never runs git on the agent's `.git`: the branch is bundled inside the sandbox and
  pushed from a clean temporary repository, to the remote URL read when the run started.
  Protected branches (`main`, `master`) and force pushes are refused.
- The sandbox hides your home folder (only the Python install and the project are visible),
  so nothing like `~/.ssh` can end up in a pushed commit.
