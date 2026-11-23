# Project context and logs/metrics tools, measured

Two features give a small local model information it cannot get from the code alone:

- **Project context**: `AGENTS.md` (or `CLAUDE.md`). The root file goes into the system
  prompt. A subfolder's file is added to a tool's output the first time the agent touches a
  path inside that folder.
- **Logs and metrics through MCP**: read-only tools from an MCP server listed in a config file
  you control, e.g. `query_logs`, `service_logs`, `prometheus_query`.

Each eval task below was run with the feature on and with it off (`--no-context`,
`--no-mcp`); nothing else changed.

## Setup

- 2026-11-23, gpt-oss:20b on an RTX 3060 Ti (8 GB), `num_ctx` 16384, code at `3f62348`.
- Done checks were on: `finish` is refused until the task's tests pass.
- 5 runs per task and side; 3 runs in parallel (2 for Docker).
- Hidden tests check the actual rule or bug, not just that the visible tests pass.

| Task | What the agent needs to know | Where it is |
|---|---|---|
| `context-project-rules` | money is `Decimal` with `ROUND_HALF_UP`; every change gets a `CHANGELOG.md` entry | root `AGENTS.md` |
| `context-folder-rules` | new functions in `legacy/` must call `warn_legacy("<name>")` | `legacy/AGENTS.md` |
| `logs-checkout-errors` | which of several services fails and on what input (`'1,299.00'`) | fake logs/metrics MCP server |
| `docker-orders-incident` | the orders API fails on region IDs like `EU-1003` | real Docker Compose stack: the API, a traffic generator, Prometheus, and an MCP server over `docker compose logs` and the Prometheus API |

## Results

| | Feature on | Feature off | p (Fisher) |
|---|---|---|---|
| **AGENTS.md context** (2 tasks) | **8/10** (49–94%) | 0/10 (0–28%) | **0.0007** |
| — project rules | 4/5 | 0/5 | |
| — folder rules | 4/5 | 0/5 | |
| **Logs/metrics MCP**, fake server | **4/5** (38–96%) | 0/5 (0–43%) | **0.048** |
| **Logs/metrics MCP**, Docker | 0/5 (0–43%) | 0/5 (0–43%) | 1.0 |

The brackets are 95% Wilson intervals. The full table is in `evals/reports/eval-stats.html`
(`uv run python evals/stats.py --notes evals/reports/run-notes.json`).

| | Avg steps | Avg time | Peak context |
|---|---|---|---|
| Context on / off | 13.8 / 12.2 | 289 s / 278 s | 5.1k / 8.7k |
| Logs MCP on / off | 21.6 / 18.2 | 314 s / 362 s | 6.3k / 7.9k |
| Docker MCP on / off | 15.0 / 19.8 | 172 s / 309 s | 6.1k / 8.7k |

## What happened

### AGENTS.md: the rules are followed when the model is told them

- **Without the files, no run passed.** Every run did the coding part right, but the model
  can't guess a house rule:
  - in all 5 project-rules runs, `CHANGELOG.md` was not updated;
  - in all 5 folder-rules runs, the new function did not call `warn_legacy`.
- **With the files, 8/10 runs passed.**
  - The folder file reached the model in all 5 folder-rules runs: one `context` event per run,
    the first time the agent opened `legacy/`.
  - The project file costs ~100 tokens per prompt (1,136 vs 1,038 on the first step), and
    peak context was lower with it (5.1k vs 8.7k).
- **The 2 failures:**
  - In one folder-rules run, the agent hit the known `edit_file` problem: gpt-oss writes `"""`
    as `""` in `old`. After 4 identical failed edits the repeat detector stopped the run
    (`stuck`). This is the same failure as in earlier evals and is unrelated to context.
  - In one project-rules run, the code followed the Decimal rule, but the agent skipped the
    CHANGELOG entry. A rule that is not checked by tests can still be forgotten. If a rule
    matters, add it to the task's done checks.

### Logs MCP: works when the tools are named in the task

- **Without the tools (0/5), the model guessed.** It hardened input parsing against empty or
  odd values, but never against `'1,299.00'`. The input appears only in the logs.
- **With the tools (4/5), 4 runs followed the intended path:**
  1. `list_services`;
  2. `query_logs` for errors;
  3. find `decimal.InvalidOperation ... parse_amount(text='1,299.00')` in `checkout`;
  4. fix `parse_amount`;
  5. add a test with that value.
- **The failure:** the agent called `query_logs(level="ERROR", contains="ERROR")`. The level
  filter was right, but no message contains the word "ERROR", so it got `[]`.
  - It then checked `query_metrics`, saw checkout's error rate jump at 09:00, and guessed at
    the input instead of querying again.
  - An empty result looks like "no errors" to a small model. A server could say what it
    filtered on, e.g. `0 lines matched contains="ERROR"`, which would make the mistake visible.

### Docker: the tools were there but never called

- **The model never called the MCP tools in any of the 5 MCP-on runs.**
  - The tools were offered: the first prompt was ~200 tokens bigger.
  - The stack was up, and its logs held the `Traceback ... 'US-77'` lines.
  - Instead, every run read the code, decided that non-numeric IDs should get a 404, and made
    `parse_order_id` reject them. That is the opposite of the fix: the hidden tests expect
    `EU-1003` to be served.
- **The likely cause is the task wording.**

  | Task | Prompt says | Agent used the tools |
  |---|---|---|
  | Logs | "Use the logs and metrics **tools**" | 5/5 runs |
  | Docker | "Use the container logs and the metrics" | 0/5 runs |

  "Container logs" probably reads as something outside the agent's reach. That makes the
  wording the main suspect, but it hasn't been confirmed: a rerun with the logs task's wording
  would test it.
- **Without MCP, the runs were slower and failed the same way** (309 s vs 172 s). One run also
  broke the check that bad IDs are still rejected.
- **No run tried `docker` through `run_command`.** It wouldn't work anyway: the sandbox has no
  Docker socket.

## Conclusions

1. **AGENTS.md is worth it for local models.** Of all the features measured so far, it is the
   only one with an unambiguous effect (0/10 → 8/10, p < 0.001), and it costs ~100
   tokens. Keep files short and put rules the model can't infer there. Folder files reach the
   model reliably.
2. **Read-only logs/metrics tools work, but a small model doesn't think of them by itself.**
   - When the task named them as tools, 4/5 runs found the cause from the logs.
   - When it only mentioned "container logs", 0/5 runs called them.
   - When delegating an incident to the local agent, say "use the `service_logs` and
     `prometheus_query` tools". The `run_local_agent` MCP tool's caller (Claude) can do that.
3. **Some failures can be fixed outside the model:**
   - empty tool results should show the filter that was applied;
   - rules that matter should be done checks, not just text;
   - the `"""` problem in `edit_file` is still the most common failure.

## Caveats

- 5 runs per side, one model, synthetic projects. The logs result (p = 0.048) is just under
  0.05; the context result is clear.
- The rules were chosen so that the model can't infer them from the code. Real projects have
  rules the code already shows, where the gain will be smaller.
- The Docker result rests on one task wording. It is evidence about the wording, not that the
  tools are useless.
