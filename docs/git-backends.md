# Git backends: own tools vs git MCP vs git CLI

How should a small local model work with git? We gave gpt-oss:20b the same git tasks with three
different sets of git tools, each built on its own branch, and measured the results.

| Backend | Branch | What the model gets |
|---|---|---|
| **Own tools** | `feat/git-remote` | 6 task-shaped git tools (`git_status`, `git_diff`, `git_log`, `git_commit`, `git_restore`, `git_create_branch`) + `git_push`, `create_pull_request` |
| **git MCP** | `exp/git-mcp` | the 12 tools of the official [`mcp-server-git`](https://github.com/modelcontextprotocol/servers/tree/main/src/git) (2026.1.14) + our `git_push`, because the server cannot push |
| **git CLI** | `exp/git-shell` | no git tools: `git` and `gh` through `run_command` |

## Setup

- 2026-11-09, gpt-oss:20b on an RTX 3060 Ti (8 GB), `num_ctx` 16384, 3 runs in parallel.
- 3 tasks × 3 runs each. Every task ends by pushing a branch to a local bare remote, and hidden
  tests check what reached the remote, not the local copy:
  - `git-push-fix`: fix a bug on a new branch, commit, push;
  - `git-find-regression`: find the commit that broke the tests in the history, fix it, and
    name that commit's hash in the message;
  - `git-restore-feature`: throw away broken uncommitted changes, add a function and a test,
    commit on `main`.

## Results

| | Own tools | git MCP | git CLI |
|---|---|---|---|
| **Passed** | **9/9** | 5/9 | 8/9 |
| 95% interval of the pass rate | 70–100% | 27–81% | 56–98% |
| find-regression / push-fix / restore-feature | 3/3 · 3/3 · 3/3 | 0/3 · 2/3 · 3/3 | 3/3 · 3/3 · 2/3 |
| Avg steps per task | **12.8** | 14.7 | 15.0 |
| Tool errors (all 9 runs) | 5 | 5 | 7 |
| Avg time per task | **146 s** | 162 s | 179 s |
| Avg prompt tokens per task | **28.3k** | 37.6k | 33.9k |
| Peak context | 3.9k | 4.0k | 6.9k |
| First prompt (system + tool schemas) | 1.45k | 1.62k | **1.04k** |

### Is the difference real?

Fisher's exact test on passed and failed runs (from `evals/stats.py`):

| Comparison | p-value | Runs per side to be sure |
|---|---|---|
| Own tools vs git MCP (9/9 vs 5/9) | 0.08 | ~10 |
| git MCP vs git CLI (5/9 vs 8/9) | 0.29 | ~25 |
| Own tools vs git CLI (9/9 vs 8/9) | 1.00 | ~63 |

Nine runs per backend are not enough to call any of these real by the usual p < 0.05 rule.
Own tools vs MCP comes closest, and unlike the others it has a clear cause behind it (next
section). Own tools vs CLI is a tie on pass rate; the CLI only loses on cost: more steps,
more time and almost twice the peak context.

## Why runs failed

**git MCP: `git_create_branch` does not switch branches.** It creates the branch, replies
"Created branch 'fix/regression' from 'main'", and stays on `main`. The model then commits
on `main`, and the pushed `fix/...` branch has no fix. This caused all 4 failures. In the runs
that passed, the model happened to call `git_checkout` as well. The server's `git_log` output
was also garbled in this version: fields were shifted (a commit hash under "Author") and Python
objects such as `<git.Actor ...>` leaked into the text, so the model fell back to `git blame`
through the shell.

**git CLI: forgot to commit.** One run fixed the code, passed the tests and finished without
committing. Nothing went wrong with the tools: without a `git_commit` tool in the list, the
commit step is easier to forget. Raw git output also costs more steps and context.

**Own tools:** no failures. Replies say exactly what happened ("Created and switched to branch
fix/regression"), which is what a small model needs.

## Safety

| | Own tools | git MCP | git CLI |
|---|---|---|---|
| Push target | remote pinned when the run starts | same (our `git_push`) | anything the shell can reach |
| `main` / `master` | refused | refused | allowed |
| Force push | never | never | allowed |
| Credentials | used outside the sandbox, never visible to the model | same | a GitHub token inside the shell |
| Code in `.git/config` (e.g. `core.fsmonitor`) | git runs in the sandbox | server runs in the sandbox | sandboxed locally; with network on real remotes |

Pushing from our own tools never runs git on the agent's `.git`: the branch is packed into a
bundle inside the sandbox and pushed from a clean temporary repository.

## Conclusion

- **Use our own git tools by default.** They had the best pass rate, the fewest steps and the
  lowest cost, and they are the only option that keeps pushing safe.
- **Do not hand a small model an MCP server as it is.** Its tools follow the server's design,
  not the task: one surprising behaviour (create without switching) was enough to lose 4 of 9
  runs. If you use MCP, wrap it: allow a few tools, rewrite their descriptions and fix such
  behaviour in the wrapper. That is how the logs and metrics MCP support in this project
  works (allowlist, short descriptions, compact output).
- **The CLI is fine for a throwaway sandbox**, but costs more context and gives up the push
  guarantees.
- **To make these differences certain**, rerun with about 10 runs per backend for own tools
  vs MCP:

```bash
uv run python evals/runner.py --task 'git-*' --repeats 10 --jobs 3 --git-backend native
```

Raw data: `evals/results/20261109-*-gpt-oss_20b-git-*/` in each branch's worktree (not in git).
