"""Eval statistics: how sure are we about a pass rate, and is a difference real or luck?

For every eval run (a results.json folder):
  - pass rate with a 95% Wilson interval;
  - each run compared with the previous run on the same tasks (and any pairs listed in the
    notes file): Fisher's exact test, and how many runs per side would make the difference clear;
  - per task: passes in each run, and tasks that flip between pass and fail.

Usage: uv run python evals/stats.py [RESULT_DIR ...] [--notes FILE] [--html FILE]
With no folders, reads every evals/results/*/results.json.
"""

import argparse
import html
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

RESULTS = Path(__file__).parent / "results"
Z95 = 1.96
Z80_POWER = 0.84


@dataclass
class Run:
    name: str  # results folder name, e.g. 20261110-213341-gpt-oss_20b
    started: datetime
    settings: dict
    checks: bool | None
    rows: list[dict]
    note: str = ""

    @property
    def passed(self) -> int:
        return sum(r["passed"] for r in self.rows)

    @property
    def n(self) -> int:
        return len(self.rows)

    @property
    def tasks(self) -> tuple[str, ...]:
        return tuple(sorted({r["task"] for r in self.rows}))

    @property
    def label(self) -> str:
        s = self.settings
        parts = [s.get("model", "?")]
        if s.get("think") is not None:
            parts.append(f"think {s['think']}")
        if s.get("git_backend"):
            parts.append(f"git {s['git_backend']}")
        if self.checks is not None:
            parts.append("checks on" if self.checks else "checks off")
        return " · ".join(parts)

    def task_passes(self, task: str) -> tuple[int, int]:
        rows = [r for r in self.rows if r["task"] == task]
        return sum(r["passed"] for r in rows), len(rows)

    def mean(self, key: str) -> float:
        values = [r[key] for r in self.rows if key in r]
        return sum(values) / len(values) if values else 0.0


@dataclass
class Comparison:
    a: Run
    b: Run
    p_value: float
    runs_needed: int | None  # per side, for 80% power at 5% significance; None = no difference
    why: str = field(default="previous run on the same tasks")


def load_run(folder: Path) -> Run:
    data = json.loads((folder / "results.json").read_text())
    started = datetime.strptime("-".join(folder.name.split("-")[:2]), "%Y%m%d-%H%M%S")
    return Run(folder.name, started, data.get("settings", {}), data.get("checks"), data["runs"])


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% interval for a pass rate; sensible for small n and for 0% or 100%."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def fisher_exact(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-sided p-value: the chance of a split at least this uneven if both had the same pass rate."""
    total, passes = n1 + n2, k1 + k2

    def prob(k: int) -> float:
        return math.comb(n1, k) * math.comb(n2, passes - k) / math.comb(total, passes)

    observed = prob(k1)
    lowest, highest = max(0, passes - n2), min(n1, passes)
    p = sum(prob(k) for k in range(lowest, highest + 1) if prob(k) <= observed * (1 + 1e-9))
    return min(1.0, p)


def runs_needed(p1: float, p2: float) -> int | None:
    """Runs per side to tell p1 from p2 apart 80% of the time (normal approximation)."""
    if p1 == p2:
        return None
    variance = p1 * (1 - p1) + p2 * (1 - p2) or 0.01  # both 0% or 100%: assume a little noise
    return math.ceil((Z95 + Z80_POWER) ** 2 * variance / (p1 - p2) ** 2)


def compare(a: Run, b: Run, why: str) -> Comparison:
    return Comparison(
        a, b, fisher_exact(a.passed, a.n, b.passed, b.n), runs_needed(a.passed / a.n, b.passed / b.n), why
    )


def comparisons(runs: list[Run], extra: list[tuple[str, str, str]]) -> list[Comparison]:
    """Each run against the previous one on the same tasks, plus pairs from the notes file."""
    found, seen = [], set()
    last_on: dict[tuple[str, ...], Run] = {}
    for run in runs:
        if previous := last_on.get(run.tasks):
            found.append(compare(previous, run, "previous run on the same tasks"))
            seen.add((previous.name, run.name))
        last_on[run.tasks] = run
    by_name = {r.name: r for r in runs}
    for a, b, why in extra:
        if (a, b) in seen:  # already compared: the notes file just names the experiment
            next(c for c in found if (c.a.name, c.b.name) == (a, b)).why = why
        elif a in by_name and b in by_name:
            found.append(compare(by_name[a], by_name[b], why))
    return found


def flaky_tasks(runs: list[Run]) -> dict[str, tuple[int, int]]:
    """Tasks that both passed and failed across all the given runs: task -> (passes, attempts)."""
    totals: dict[str, list[int]] = {}
    for run in runs:
        for task in run.tasks:
            k, n = run.task_passes(task)
            t = totals.setdefault(task, [0, 0])
            t[0] += k
            t[1] += n
    return {task: (k, n) for task, (k, n) in sorted(totals.items()) if 0 < k < n}


def verdict(c: Comparison) -> str:
    if c.p_value < 0.05:
        return "likely real"
    return "could be luck"


def print_text(runs: list[Run], comps: list[Comparison]) -> None:
    print(f"{'run':<44} {'config':<40} {'passed':>8} {'95% interval':>14}")
    for run in runs:
        lo, hi = wilson(run.passed, run.n)
        print(f"{run.name:<44} {run.label:<40} {run.passed:>3}/{run.n:<4} {lo:>6.0%} – {hi:<5.0%}")
    print()
    for c in comps:
        need = f"~{c.runs_needed} runs per side to be sure" if c.runs_needed else "no difference"
        print(
            f"{c.a.passed}/{c.a.n} vs {c.b.passed}/{c.b.n}  p={c.p_value:.2f}  {verdict(c):<13} {need}  ({c.why})"
        )
    flaky = flaky_tasks(runs)
    if flaky:
        print("\nflips between pass and fail: " + ", ".join(f"{t} {k}/{n}" for t, (k, n) in flaky.items()))


# ---------- HTML ----------

CSS = """
/* Layout: one reading column; wide tables scroll inside their own frame. */
:root {
  --bg: #f6f7f9; --surface: #ffffff; --fg: #1b2230; --muted: #5d6676; --line: #dde1e8;
  --accent: #2f5d8a; --pass: #2f7d4f; --pass-bg: #e3f2e8; --fail: #b4403a; --fail-bg: #f8e4e2;
  --mixed: #9a6a12; --mixed-bg: #f6ecd6; --track: #e8ebf0;
  --sans: "IBM Plex Sans", system-ui, sans-serif; --mono: "IBM Plex Mono", ui-monospace, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #12161d; --surface: #1a2029; --fg: #e4e8ee; --muted: #98a2b2; --line: #2c3440;
  --accent: #7fb0e0; --pass: #6cc58f; --pass-bg: #1c3527; --fail: #ec8a83; --fail-bg: #3d2120;
  --mixed: #e2b45a; --mixed-bg: #3a2f17; --track: #262d38; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #12161d; --surface: #1a2029; --fg: #e4e8ee; --muted: #98a2b2; --line: #2c3440;
  --accent: #7fb0e0; --pass: #6cc58f; --pass-bg: #1c3527; --fail: #ec8a83; --fail-bg: #3d2120;
  --mixed: #e2b45a; --mixed-bg: #3a2f17; --track: #262d38; color-scheme: dark }
body { background: var(--bg); color: var(--fg); font: 15px/1.55 var(--sans); }
main { max-width: 1040px; margin: 0 auto; padding-block: 40px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 40px; }
h1 { font-size: 30px; line-height: 1.2; margin: 0; text-wrap: balance; letter-spacing: -0.01em; }
h2 { font-size: 19px; margin: 0; text-wrap: balance; }
p { margin: 0; max-width: 68ch; }
.lede { color: var(--muted); }
.eyebrow { font: 600 12px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--accent); }
section { display: grid; gap: 14px; min-width: 0; }
.frame { overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 6px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: middle; }
tr:last-child td { border-bottom: 0; }
th { font: 600 12px/1.3 var(--mono); color: var(--muted); letter-spacing: .04em; white-space: nowrap; }
td.num, th.num { text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; white-space: nowrap; }
.run { font-family: var(--mono); font-size: 12px; color: var(--muted); white-space: nowrap; }
.cfg { white-space: nowrap; }
.note { color: var(--muted); font-size: 13px; min-width: 220px; }
.ci { position: relative; width: 200px; height: 18px; }
.ci .track { position: absolute; inset: 8px 0; background: var(--track); border-radius: 1px; }
.ci .band { position: absolute; top: 4px; height: 10px; background: color-mix(in srgb, var(--accent) 30%, transparent); border-radius: 2px; }
.ci .dot { position: absolute; top: 2px; width: 3px; height: 14px; margin-left: -1px; background: var(--accent); }
.scale { display: flex; justify-content: space-between; width: 200px; font: 11px var(--mono); color: var(--muted); }
.pill { display: inline-block; padding: 2px 9px; border-radius: 999px; font: 600 12px/1.5 var(--mono); white-space: nowrap; }
.pill.real { background: var(--pass-bg); color: var(--pass); }
.pill.luck { background: var(--mixed-bg); color: var(--mixed); }
.cell { display: inline-block; min-width: 44px; padding: 2px 6px; border-radius: 3px; text-align: center;
  font: 12px/1.5 var(--mono); font-variant-numeric: tabular-nums; }
.cell.pass { background: var(--pass-bg); color: var(--pass); }
.cell.fail { background: var(--fail-bg); color: var(--fail); }
.cell.mixed { background: var(--mixed-bg); color: var(--mixed); font-weight: 600; }
.matrix th.col { writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap; font-weight: 500; padding: 10px 6px; }
.matrix td { text-align: center; padding: 6px; }
.matrix td.task { text-align: left; font-family: var(--mono); font-size: 13px; white-space: nowrap; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; color: var(--muted); font-size: 13px; align-items: center; }
.method { color: var(--muted); font-size: 13px; display: grid; gap: 6px; }
"""


def _e(text: object) -> str:
    return html.escape(str(text))


def _ci_bar(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    p = k / n if n else 0
    return (
        f'<div class="ci" role="img" aria-label="{p:.0%}, 95% interval {lo:.0%} to {hi:.0%}">'
        f'<div class="track"></div><div class="band" style="left:{lo:.1%};width:{hi - lo:.1%}"></div>'
        f'<div class="dot" style="left:{p:.1%}"></div></div>'
    )


def _cell(k: int, n: int) -> str:
    if n == 0:
        return ""
    kind = "pass" if k == n else "fail" if k == 0 else "mixed"
    return f'<span class="cell {kind}">{k}/{n}</span>'


def render_html(runs: list[Run], comps: list[Comparison]) -> str:
    attempts = sum(r.n for r in runs)
    first, last = runs[0].started, runs[-1].started
    run_rows = "".join(
        f"<tr><td class='run'>{_e(r.started.strftime('%b %d %H:%M'))}</td><td class='cfg'>{_e(r.label)}</td>"
        f"<td class='num'>{len(r.tasks)}</td><td class='num'>{r.passed}/{r.n}</td>"
        f"<td class='num'>{r.passed / r.n:.0%}</td>"
        f"<td class='num'>{wilson(r.passed, r.n)[0]:.0%}–{wilson(r.passed, r.n)[1]:.0%}</td>"
        f"<td>{_ci_bar(r.passed, r.n)}</td><td class='num'>{r.mean('seconds'):.0f}s</td>"
        f"<td class='note'>{_e(r.note)}</td></tr>"
        for r in runs
    )
    comp_rows = "".join(
        f"<tr><td class='cfg'>{_e(c.a.label)}<div class='run'>{_e(c.a.started.strftime('%b %d %H:%M'))}</div></td>"
        f"<td class='cfg'>{_e(c.b.label)}<div class='run'>{_e(c.b.started.strftime('%b %d %H:%M'))}</div></td>"
        f"<td class='num'>{c.a.passed}/{c.a.n} → {c.b.passed}/{c.b.n}</td>"
        f"<td class='num'>{c.p_value:.2f}</td>"
        f"<td><span class='pill {'real' if c.p_value < 0.05 else 'luck'}'>{verdict(c)}</span></td>"
        f"<td class='num'>{'—' if c.runs_needed is None else f'~{c.runs_needed:,}'}</td>"
        f"<td class='note'>{_e(c.why)}</td></tr>"
        for c in comps
    )
    tasks = sorted({t for r in runs for t in r.tasks})
    flaky = flaky_tasks([r for r in runs if r.settings.get("model") == runs[-1].settings.get("model")])
    cols = "".join(
        f"<th class='col'>{_e(r.started.strftime('%b %d %H:%M'))} · {_e(r.label)}</th>" for r in runs
    )
    matrix_rows = "".join(
        f"<tr><td class='task'>{_e(t)}</td>"
        + "".join(f"<td>{_cell(*r.task_passes(t))}</td>" for r in runs)
        + f"<td>{_cell(*flaky[t]) if t in flaky else ''}</td></tr>"
        for t in tasks
    )
    real = sum(c.p_value < 0.05 for c in comps)
    return f"""<title>LocalAgents Eval Stats</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;600;700&display=swap">
<style>{CSS}</style>
<main>
<header style="display:grid;gap:10px">
  <div class="eyebrow">LocalAgents · local Ollama coding agent</div>
  <h1>Eval stats: which differences are real</h1>
  <p class="lede">{len(runs)} eval runs, {attempts} task attempts, {_e(first.strftime("%b %d"))} – {_e(last.strftime("%b %d %Y"))}.
  Each pass rate has a 95% interval, and each change is tested against luck.
  {real} of {len(comps)} compared changes are clear enough to call real; the rest need more runs.</p>
</header>

<section>
  <h2>Pass rate with its error range</h2>
  <p class="lede">The bar shows the pass rate (line) and the range the true rate most likely sits in (band).
  With 9 or 10 attempts the band is wide: a 100% run is consistent with a true rate near 70%.</p>
  <div class="frame"><table>
    <tr><th>Run</th><th>Config</th><th class="num">Tasks</th><th class="num">Passed</th><th class="num">Rate</th>
    <th class="num">95% interval</th><th><div class="scale"><span>0%</span><span>50%</span><span>100%</span></div></th>
    <th class="num">Avg time</th><th>Note</th></tr>
    {run_rows}
  </table></div>
</section>

<section>
  <h2>Real improvement or luck?</h2>
  <p class="lede">Each run is compared with the previous run on the same tasks, plus the experiments below.
  The p-value is the chance of seeing a gap at least this big if both setups were equally good.
  "Runs needed" is how many attempts per side would show the observed gap 80% of the time.</p>
  <div class="frame"><table>
    <tr><th>Before</th><th>After</th><th class="num">Passed</th><th class="num">p</th><th>Verdict</th>
    <th class="num">Runs needed</th><th>Why compared</th></tr>
    {comp_rows}
  </table></div>
</section>

<section>
  <h2>Task stability</h2>
  <p class="lede">Passes per task in each run. Amber cells mixed pass and fail within one run; the last column
  counts all {_e(runs[-1].settings.get("model", ""))} runs for tasks that flipped.</p>
  <div class="legend"><span class="cell pass">3/3</span> always passed <span class="cell mixed">2/3</span> flipped
  <span class="cell fail">0/3</span> always failed</div>
  <div class="frame"><table class="matrix">
    <tr><th>Task</th>{cols}<th class="col">Flips, all {_e(runs[-1].settings.get("model", ""))} runs</th></tr>
    {matrix_rows}
  </table></div>
</section>

<section class="method">
  <h2 style="color:var(--fg)">Method</h2>
  <p>Intervals: Wilson score, 95%. Comparisons: Fisher's exact test, two-sided, on passed and failed attempts.
  Runs needed: normal approximation, 5% significance, 80% power. Runs on different task sets are never compared.
  The code changed between runs, so a comparison measures everything that changed, not only the named setting.</p>
  <p>Generated by <code>evals/stats.py</code> from <code>evals/results/*/results.json</code>.</p>
</section>
</main>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Pass-rate intervals, run comparisons and flaky tasks.")
    parser.add_argument(
        "folders", nargs="*", type=Path, help="Result folders. Default: all in evals/results."
    )
    parser.add_argument(
        "--notes", type=Path, help='JSON: {"notes": {run: text}, "comparisons": [[a, b, why]]}.'
    )
    parser.add_argument("--html", type=Path, help="Also write an HTML report here.")
    args = parser.parse_args()

    folders = args.folders or [p.parent for p in RESULTS.glob("*/results.json")]
    runs = sorted((load_run(f) for f in folders if (f / "results.json").exists()), key=lambda r: r.started)
    if not runs:
        raise SystemExit("No results.json found.")
    notes = json.loads(args.notes.read_text()) if args.notes else {}
    for run in runs:
        run.note = notes.get("notes", {}).get(run.name, "")
    comps = comparisons(runs, [tuple(c) for c in notes.get("comparisons", [])])

    print_text(runs, comps)
    if args.html:
        args.html.write_text(render_html(runs, comps))
        print(f"\nwrote {args.html}")


if __name__ == "__main__":
    main()
