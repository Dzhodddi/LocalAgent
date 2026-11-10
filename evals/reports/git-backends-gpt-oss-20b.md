# Git backends: own tools vs git MCP vs git CLI (gpt-oss:20b)

2026-11-09. 3 git tasks × 3 runs each, `--jobs 3`, gpt-oss:20b on an RTX 3060 Ti (8 GB),
`num_ctx` 16384. Every task ends with pushing a branch to a local bare remote, and the
hidden tests check what reached the remote.

| | Own tools | git MCP | git CLI (shell) |
|---|---|---|---|
| Branch | `feat/git-remote` | `exp/git-mcp` | `exp/git-shell` |
| Git tools given to the model | 6 git tools + `git_push`, `create_pull_request` | 12 from `mcp-server-git` + our `git_push` | none: `git`/`gh` via `run_command` |
| **Passed** | **9/9** | 5/9 | 8/9 |
| find-regression / push-fix / restore-feature | 3/3 · 3/3 · 3/3 | 0/3 · 2/3 · 3/3 | 3/3 · 3/3 · 2/3 |
| Avg steps per task | **12.8** | 14.7 | 15.0 |
| Tool errors (all 9 runs) | 5 | 5 | 7 |
| Avg time per task | **146 s** | 162 s | 179 s |
| Wall time (9 runs) | 507 s | **497 s** | 603 s |
| Avg prompt tokens per task | **28.3k** | 37.6k | 33.9k |
| Peak context | 3.9k | 4.0k | 6.9k |
| First prompt (system + tool schemas) | 1.45k | 1.62k | **1.04k** |
| Push safety | Pinned remote, `main`/`master` blocked, no force push | Same (uses our `git_push`) | None: the shell gets network and a GitHub token |
| Git config can run code? | No, git runs in the sandbox | No, server runs in the sandbox | No locally; on real remotes the shell has network |

## Why runs failed

- **git MCP:** `git_create_branch` creates the branch but does not switch to it, and its
  reply does not say so. The agent then commits to `main`, and the pushed `fix/...` branch
  has no fix (4 of 4 failures). Its `git_log` output is also garbled in 2026.1.14
  (shifted fields, `<git.Actor ...>` objects), so the agent fell back to `git blame`
  in the shell.
- **git CLI:** one run fixed the code and passed the tests, then finished without
  committing. With no `git_commit` tool listed, the commit step is easier to forget.
  Raw git output also cost more steps and almost twice the peak context.

## Verdict

Use our own tools as the default. Small, task-shaped tools with clear replies
("Created and switched to branch ...") work best for a 20B model, and they are the only
option that keeps push safe. MCP is only worth it with a wrapper that fixes its semantics.
The CLI is fine for throwaway sandboxes.

Raw data: `evals/results/20261109-*-gpt-oss_20b-git-*/` in each branch's worktree.
