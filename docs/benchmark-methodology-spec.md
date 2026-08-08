# Benchmark Methodology Spec — Phase 1

Operationalizes Phase 1 of [benchmark-report-remediation-plan.md](benchmark-report-remediation-plan.md) into
rules a Phase 2 harness must follow. Nothing here is a measurement — it's the definition of what a measurement
would have to do to be trustworthy, written down *before* any re-run, per the plan's own reasoning: re-running
without fixing the grading defect just produces prettier numbers with the same defect.

All reference values below were computed just now, directly against the real files at
`workspace/dataset.csv` (307 rows × 16 columns) and `workspace/housing.csv` (5 rows), independently of any LLM
call — this is what "grade from content, not from a self-reported field" means in practice.

---

## 1.1 — Correctness criteria per test

A reference answer key, so Phase 2 can grade "did the system get the right number," not just "did the turn
complete." Every existing test ID from the report is kept for continuity.

### New fact this surfaces: `ethnicgroup` is 100% null

`df['ethnicgroup'].isnull().sum()` is **307 / 307** — the entire column is empty. This changes what "correct"
means for two tests the report treated as routine:

- **C1 (missing-value profiling)**: real completeness is **93.75%**, not the 100% the raw harness's C1 answer
  claimed. One whole column is entirely missing. A pass predicate that only checks "did it report *a*
  completeness percentage" would have let the wrong percentage through — the predicate must check the
  reported number against the real one, per column.
- **A1 (group by gender & ethnicgroup)**: grouping by a column that is 100% null is not a normal aggregation —
  `df.groupby(['gender', 'ethnicgroup'])` silently drops every row, because pandas excludes `NaN` group keys
  by default, so the "correct" result is an **empty table**, not a populated one. The right behavior for the
  system under test is to *notice and say so* ("ethnicgroup has no non-null values, cannot group by it"), not
  to silently return nothing or hallucinate a populated table. A test graded only on "did the shape look like
  a groupby result" would pass a system that got this completely wrong in either direction.

### Reference answers

| ID | Test | Correct result (computed independently, just now) | Pass predicate |
| :-- | :-- | :-- | :-- |
| **A1** | Mean mathgrade/sciencesgrade by gender & ethnicgroup | **Empty result** — `ethnicgroup` is 100% null, so no groups exist. Correct behavior: flag the column as unusable for grouping, not silently return an empty or fabricated table. | Answer must state `ethnicgroup` has no non-null values. A populated-looking table is an automatic fail regardless of what numbers are in it — those numbers cannot be real. |
| **A2** | Top 10th-percentile englishgrade | 90th-percentile threshold = **3.9**; **67 students** meet or exceed it. | Reported threshold within `check_grounding`'s own rounding tolerance of 3.9; reported count within same tolerance of 67. |
| **A3** | Composite score (mean of mathgrade, sciencesgrade), top 5 | Top 5 by `id`: **286** (4.00), **224** (3.95), **154** (3.95), **303** (3.95), **98** (3.95). Ties beyond rank 2 mean "top 5" is order-dependent — any correct tie-break is acceptable. | Top result must be id 286 at composite 4.00. Remaining four must all be at composite 3.95 (ties are fine; a different set of ids at 3.95 is not). |
| **B1** | Pearson correlation matrix (age, englishgrade, mathgrade, sciencesgrade, languagegrade) | See matrix below. All off-diagonal values are **weak** — the largest magnitude is age↔sciencesgrade at **-0.097**. | Every reported correlation within ±0.01 of the reference matrix. A report describing any of these as a "moderate" or "strong" relationship is a correctness fail independent of the number's precision — nothing in this matrix clears 0.1. |
| **B2** | Variance / std / IQR for mathgrade | var = **0.2274**, std = **0.4768**, IQR = **0.70** | Each within `check_grounding`'s rounding tolerance of these three values. |
| **C1** | Missing-value profiling | Overall completeness **93.75%** (16 columns × 307 rows, 307 nulls, all in `ethnicgroup`). Every column *except* `ethnicgroup` is 100% complete. | Must report `ethnicgroup` specifically as the incomplete column, not a flat "0 missing values" across the board. |
| **C2** | Avg price, 5-row `housing.csv` | **374,000** (mean of 300000, 450000, 200000, 600000, 320000) | Exact match — n=5 leaves no room for a rounding excuse. |
| **C3** | Avg salary (column doesn't exist) | No `salary` column in either `dataset.csv` or `housing.csv`. Correct behavior: state the column doesn't exist and name the columns that do. | Fail if the code runs against a different, silently-substituted column, or if the answer's failure description doesn't correctly identify *which* column is missing (Phase -1.1 found the raw C3 run failed on a `KeyError` for the wrong table, `tables['students']`, and the report's "gracefully handled" description was itself inaccurate). |
| **D1** | Histogram of mathgrade | No single numeric answer. | Code must execute without error, the chart file must be written to `runtime.workspace_path`-derived path (not a literal `/workspace` — see execution architecture notes), and the answer must not state statistics absent from real output. |
| **D2** | Scatter: age vs englishgrade | No single numeric answer. Reference correlation for context: **-0.002** (essentially none). | Same execution/path predicate as D1. If the answer editorializes about a visible trend, that trend must be consistent with a near-zero correlation, or it's a correctness fail even though nothing crashed. |
| **E1–E3** | AST guard vectors | Deterministic: guard verdict, not LLM output. | Already well-defined by `CodeGuard.scan`'s own return value — no change needed, these three are the one category the original report graded correctly. |
| **S1** (enterprise) | Cohort segmentation, portfolio vs refletter | Depends on real `portfoliorating`/`refletterrating` columns, present in the real dataset. | Every number in the answer must appear in real execution output — this is exactly what Phase -1.2 found missing for all three enterprise scenarios. Grade by re-running `check_grounding` against the real execution capture, not by reading the prose. |
| **S2** (enterprise) | Geospatial/demographic correlation, 8×8 matrix | Full matrix must be computed by `df.corr()` and printed to stdout, not narrated from memory. | Every one of the 8×8 = 64 cells quoted in the answer must trace to real printed output. Phase -1.2 found 28+ of these were fabricated in the original run. |
| **S3** (enterprise) | Anomaly detection, high-grade/low-rating disparity | The "X% of students" headline figure must come from a printed count, not asserted. | Same rule — Phase -1.2 found the "15%" figure ungrounded in the original run. |
| Cloud single-turn | Top-5 englishgrade students, mean age | Top 5 by englishgrade (all tied at 4.0): ids 286, 275, 269, 268, 227. **Mean age = 20.6**. | Exact match — this one the original report got right (Phase -1.6). |
| Hybrid single-turn | Avg mathgrade + count by gender | F: 3.394079 (152), M: 3.435099 (151), other: 3.400000 (4) | Exact match to 4+ decimals — this one the original report also got right. |
| Model-speed comparison (§8.3) | Mean/median age & englishgrade, both models | Mean age = **21.964**, median age = **22.0**; mean englishgrade = **3.370**, median englishgrade = **3.5**. | Per Phase -1.5, the 1.5B model's original run reported "mean age 30... English grade 85 points" — wrong by roughly 8 and 25× respectively, and on a scale the real column doesn't use (englishgrade tops out at 4.0, never 85). Any run reporting englishgrade above ~5 is an automatic fail requiring no further checking. |

### Correlation matrix reference (B1)

```
                 age  englishgrade  mathgrade  sciencesgrade  languagegrade
age            1.000        -0.002      0.018         -0.097          0.027
englishgrade  -0.002         1.000     -0.012          0.005          0.032
mathgrade      0.018        -0.012      1.000          0.058         -0.020
sciencesgrade -0.097         0.005      0.058          1.000          0.012
languagegrade  0.027         0.032     -0.020          0.012          1.000
```

### The pattern behind six of the original failures

A1, B1, C1, C2, D1, D2 and both enterprise-scenario table loads all show the same root cause in the raw
harness data: code opening `tables['orders']`, `tables['customers']`, or `tables['students']` — table names
that exist in neither `dataset.csv` nor `housing.csv`. This means Phase 2's harness needs one more thing
beyond a grading fix: **the prompt template used to drive the worker model must state the real table key**
(`tables['dataset']` or whatever `DatasetHandle.table_key` resolves the uploaded file to — the code convention
covered in this repo's session/table-key handling) rather than leaving the model to guess a generic e-commerce
schema (`orders`/`customers`) that has nothing to do with a student dataset. This is a prompt-construction gap
in how the original harness drove the system, not a system defect — worth flagging separately from the
grading-logic fix, since fixing the grader alone would just make these six fail loudly instead of silently,
without addressing why they fail.

---

## 1.2 — Retry accounting

Per Phase -1.1/-1.7: the six failing local-mode runs never triggered `MAX_CORRECTION_RETRIES` because the
original harness scored them as one-shot successes, so the correction loop was never given the chance to
fire. Grading from content (1.1, above) removes the false floor. On top of that:

- **Retries must be counted from the event stream**, not a summary field. Every real turn emits
  `step_start`/`step_end` per iteration and a `correction` counted via the orchestrator's own retry loop —
  count *those* events, not a number the harness writes about itself.
- **A retry count of 0 is only meaningful once 1.1's grading is in place.** Before that fix, "0 retries" was
  measuring "the harness never noticed a failure," not "the model never needed a second attempt." Report the
  two numbers side by side in Phase 2's output — retries-per-content-graded-failure — so a future reader can't
  make the same substitution the original report made.

---

## 1.3 — Grounding: resolved, harness rule only

Per the plan's Phase -1.3 update: `check_grounding` is called unconditionally from one call site in
`orchestrator.py`, gated only by a default-on setting, and no completed real turn skips it. It correctly
flagged fabrication in all three enterprise scenarios. The §8.3 miss is explained by the comparison script
almost certainly calling the model directly rather than through `orchestrator.run()`.

**Harness rule**: every timed comparison in Phase 2 — including single-model speed comparisons — must go
through the real orchestrator turn (`AnalysisOrchestrator.run` or the REST/WebSocket path that calls it), never
a bare model call. This is what makes grounding, retry accounting, and every other per-turn check apply
uniformly regardless of which specific thing is being timed. Timing a bypassed call is not timing the system
under test.

---

## 1.4 — Unmeasured quantitative claims to resolve

Carried from the plan's 1.4, restated as a checklist for Phase 2 to either measure or explicitly label as an
estimate in the rewritten report — no claim ships unlabeled:

- [ ] §11.7 "hybrid Config B saves ~50% fewer API tokens" — measure actual token counts, both configs, same
      task set.
- [ ] §11.7 "semantic caching saves ~20–30% fewer LLM calls" — measure hit rate on a repeated-question workload;
      note the feature is already on by default (Phase 0.6), so this is a threshold-tuning measurement, not an
      enable/disable one.
- [ ] §11.7 "batch similar prompts saves ~30–40% fewer Manager calls" — either design a batching experiment or
      mark as an estimate with no supporting data.
- [ ] §11.4 "lower `CACHE_SIMILARITY_THRESHOLD` [`SEMANTIC_CACHE_THRESHOLD`] 0.92→0.88 for ~20% more cache hits"
      — measure directly; this is cheap since it needs no LLM call, only cache-lookup replay.

---

## 1.5 — Sampling: n ≥ 3 for hybrid and cloud

Per the plan: the original "7.3× faster" claim compares one cloud turn against a 13-run local average. Phase 2
protocol:

- Every mode/config cell (local-only, hybrid Config A, hybrid Config B, cloud-only) runs the **same task set**
  at **n ≥ 3** per cell.
- Report **median and spread** (min–max, or IQR if n is large enough), never a single point estimate presented
  as representative.
- The task set itself should be the corrected 1.1 reference-answer set, so latency and correctness are
  measured on the same runs rather than requiring two separate passes.

---

## 1.6 — Backend comparison: cold vs warm, controlled

Per the plan: Docker (0.418s) vs Host (5.333s) in the original report are not the same operation — image
state, daemon warmth, and interpreter/pandas import time were not controlled for.

Phase 2 protocol per backend (`host`, `docker`, `inprocess`):

1. **Cold**: daemon/container not yet started, image not yet pulled (docker only) — first spawn after a clean
   state.
2. **Warm**: daemon/container already running, second and subsequent spawns in the same session.
3. Report both numbers for every backend, never only one. `inprocess` has no meaningful cold/warm distinction
   (no daemon to warm) — state that explicitly rather than omitting the row.

---

## 1.7 — Host preconditions recorded with every run

Per the plan: without these, latency numbers are uninterpretable — this is what separates "the model is slow"
from "the machine is thrashing." Record at the start of every Phase 2 run:

| Field | Why |
| :-- | :-- |
| Free RAM (GB) at run start | Directly determines which `plan_resident_set` branch applies |
| `plan_resident_set` verdict (resident / swap) | The actual planner decision, not an inference from free RAM |
| `keep_alive` value actually sent per model | Confirms whether `LLM_KEEP_ALIVE` or `LLM_KEEP_ALIVE_SWAP` applied |
| Whether each model was resident before the first call of the run | Distinguishes a cold-load turn from a warm one |
| `EXECUTION_BACKEND` and `HOST_SANDBOX` mode | Same run must not silently cross backends mid-comparison |
| Wall-clock timestamp | Lets a reader correlate against other system activity on a shared laptop |

Measured just now, for context on how much this can move between runs on this exact machine: free RAM was
**3.41 GB** at the original benchmark time and **5.94 GB** when re-checked today — nearly a 2.5 GB swing on
the same idle laptop. Phase 2 must record this per run rather than assuming either figure carries forward.

---

## What Phase 1 deliberately does not do

No harness code is written here — per the plan's standing constraint, Phase 2's harness is a separate,
explicitly code-writing step. This document is the specification that harness must satisfy: grade from
content against the reference answers in 1.1, count retries from the event stream (1.2), always route through
the real orchestrator (1.3), label every unmeasured claim (1.4), sample n≥3 (1.5), report cold and warm
separately (1.6), and record preconditions every run (1.7). Building the harness against this spec is the
first task of Phase 2.
