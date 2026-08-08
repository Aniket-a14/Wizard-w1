# Benchmark harness (Phase 2 / Phase 3)

Built per [docs/benchmark-methodology-spec.md](../../docs/benchmark-methodology-spec.md) and
[docs/benchmark-report-remediation-plan.md](../../docs/benchmark-report-remediation-plan.md).

## What ran already (no live model inference needed)

| Script | What it does | Result |
| :-- | :-- | :-- |
| `guard_coverage.py` | 2.4 — AST guard negative controls, including the classes §9 never tested | 12/12 passed — `results/guard_coverage_results.json` |
| `backend_microbench.py` | 2.3/1.6 — cold vs warm spawn/exec/teardown, per backend | `results/backend_microbench_{host,docker,inprocess}.json` |
| `validate_model_pairs.py` | 3.1 — §11.2's model pairs against the real memory planner | `results/model_pair_validation.json` — 2/5 pairs land in SWAP |
| `generate_cheatsheet.py` | 3.2 — §12 generated from live `Settings`, not memory | `results/cheatsheet_section12.md` |

Run any of them again with `python scripts/benchmark_harness/<script>.py` from the repo root.
`backend_microbench.py` reads its backend from the `EXECUTION_BACKEND` env var (one process per
backend, since `Settings` is built at import time):

```bash
EXECUTION_BACKEND=host python scripts/benchmark_harness/backend_microbench.py
EXECUTION_BACKEND=docker python scripts/benchmark_harness/backend_microbench.py
EXECUTION_BACKEND=inprocess python scripts/benchmark_harness/backend_microbench.py
```

## What still needs you (live model inference)

`run_benchmark.py` drives real `AnalysisOrchestrator.run()` turns and grades them against
`reference_answers.py` via `grading.py` — this is the one piece the standing "no live model
workloads in this session" constraint keeps out of scope here. It's built and smoke-tested
(imports, regex, host-precondition capture all verified working), just never executed end-to-end.

```bash
python scripts/benchmark_harness/run_benchmark.py \
    --mode local-only \
    --manager-provider ollama --manager-model qwen2.5:3b \
    --worker-provider ollama --worker-model qwen2.5-coder:1.5b \
    --dataset workspace/dataset.csv \
    --cases A1 A2 A3 B1 B2 C1 C2 C3 \
    --n 3
```

Repeat per mode/model-pair cell per 1.5 (n≥3, median + spread). Grading is entirely automatic —
a case fails if the answer narrates its own error, if any reference number isn't traceable to
real execution output, or if a known fabrication pattern (`forbidden_if_present` in
`reference_answers.py`) shows up in the prose. This is what closes the exact gap that produced
the original report's false "13/13, 100%": grading here can never diverge from what actually ran,
because it never looks at anything except the answer and the execution output.

## Findings worth folding into the report beyond what Phase -1 already found

- **`guard_coverage.py`: 12/12, including the hard classes.** The originally-untested classes
  (computed/dunder reflection, bare `__builtins__`, drive-letter path folding both ways) all hold.
  This *upgrades* Phase 0.10 from "withdraw the false claim" to "the claim holds, now with real
  coverage" — a rare case where digging in produced good news.
- **Docker has a real cold-start race**, distinct from the Antigravity session's CUDA/llama-server
  crash. The very first `execute()` call immediately after container spawn can fail with "Runtime
  closed the connection unexpectedly" — the daemon needs roughly 1–1.5s to finish starting after
  the container reports "started." A real turn never notices because an LLM round-trip always
  separates spawn from the first execution; this synthetic benchmark's back-to-back calls exposed
  it. Not a reason to distrust the backend — a reason the spawn number alone isn't the whole
  latency story.
- **`inprocess`'s cold exec is 1.19s, not the ~8.5ms the original report used for its "moderate"
  grading** — that 8.5ms is a warm-call number (this run measured 0.5ms warm, same order of
  magnitude). The 1.19s is dominated by `matplotlib` import on first use in that process.
- **2 of 5 §11.2 model pairs land in SWAP** against the codebase's own memory-planning arithmetic,
  at their own stated RAM figures — see `validate_model_pairs.py`'s output. Caveat: the planner
  only reasons about system RAM, not VRAM, so this is sharpest for CPU-resident inference; a
  fully GPU-offloaded pair may behave differently since the weights would live in VRAM instead.
- **The generated §12 (`cheatsheet_section12.md`) is the one to publish**, not a hand-edited
  version of the original — it's read from the live `Settings` object, so an invented field name
  fails the generation step instead of shipping silently.
