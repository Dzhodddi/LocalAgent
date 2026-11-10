# Done checks A/B and GPU settings (gpt-oss:20b)

2026-11-10. 13 tasks × 3 runs, `--jobs 3`, RTX 3060 Ti 8 GB + i7-8700 (6 cores).
Both arms have the repeat detector, compaction and the `read_file` size cap; only the
done checks differ.

## Done checks

| | With checks | Without checks |
|---|---|---|
| Passed (as graded) | 36/39 | 35/39 |
| Passed (discount grader fixed, e74bc4c) | **37/39** | 36/39 |
| Avg steps / time per task | 15.3 / 281 s | **13.5 / 240 s** |
| Tool errors | 56 | 36 |
| Finish refused by checks | 1 run (then fixed and passed) | — |
| Stopped as `stuck` | 1 | 2 |
| Step limit | 1 (rename) | 1 (rename) |
| Peak context / compactions | 9.2k / 0 | 8.2k / 0 |

The checks cost about 17% more time per task. They change the pass rate by only one run,
which is within the noise of 3 repeats: gpt-oss already runs the tests itself. They matter
more when the caller needs a guarantee (committed, pushed, lint clean) than for the score.

**Main remaining failure: `edit_file` misses.** In 3 of the 4 real failures, gpt-oss
wrote a closing `"""` as `""` inside `old`. The same edit then failed four times, even
after the hint, until the repeat detector stopped the run. It is a model quirk, so
re-reading the file does not help.

## GPU settings (`scripts/bench_gpu.py`, one request at a time)

| num_gpu | num_ctx | threads | On GPU | VRAM | Prompt tok/s | Output tok/s |
|---|---|---|---|---|---|---|
| auto | 8192 | auto | 33% | 5.2 GB | 524 | **20.1** |
| auto | 16384 | auto | 30% | 4.8 GB | 496 | 19.4 |
| 8 | 16384 | auto | 26% | 4.8 GB | 431 | 12.3 |
| 12 or 16 | any | auto | out of VRAM | | | |
| auto | 16384 | 4 / 6 | 30% | 5.0 GB | 507 | 19.5 |
| auto | 16384 | 12 | 30% | 5.0 GB | 487 | 6.9 |

- Ollama's automatic layer split is already the best one; forcing layers only hurts or runs out of VRAM.
- Use the 6 physical cores (the default). Hyperthreads (12) make generation about 3× slower.
- 8k context instead of 16k gains only 3%, and peak context reached 9.2k, so keep 16k.
- One request gets ~20 tok/s; three in parallel get ~8 tok/s each (~20–24 total). The
  experts run on the CPU, so speed is bound by RAM bandwidth, and parallel requests mostly
  share it. `OLLAMA_NUM_PARALLEL=4` also reserves KV cache for 4 × 16k tokens in VRAM.
  Lowering it to 2 frees some VRAM for model layers. That has not been measured yet: it
  needs an Ollama restart.
