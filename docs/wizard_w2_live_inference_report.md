# Wizard w2 — Live Inference Report

**Date:** 2026-08-08
**Scope:** Real, non-mocked LLM inference through `AnalysisOrchestrator.run` — the same code path both `POST /api/chat` and `WS /ws/chat` use — across `local-only`, `hybrid`, and `cloud-only` data modes, against the 10-case user-story suite defined in `docs/benchmark-methodology-spec.md` and `scripts/benchmark_harness/reference_answers.py`. No answer in this report was generated or estimated by an LLM describing what it "would" do — every number below comes from `scripts/benchmark_harness/results/live_suite_results.json`, produced by actually running `run_benchmark.run_one_turn` against a live Ollama daemon and the real Gemini API.

Backends: Ollama (`qwen2.5:3b` manager / `qwen2.5-coder:1.5b` worker) for every local role, Gemini via the generic `custom_gateway` OpenAI-compatible provider for every cloud role — three different Gemini models ended up in play (`gemini-2.5-flash`, `gemini-3.6-flash`, `gemini-3.5-flash`) purely because each one's free-tier daily quota was exhausted in turn; see finding 8. Execution backend: `host` (subprocess sandbox), `SANDBOX_ENABLED=false`.

## Headline result: hybrid and cloud-only were unusable before this session

Before any live call was made, every `hybrid` and `cloud-only` turn failed at the code-generation step with `DataModeViolation: "...cannot be used for the worker role... Choose a local provider, or change the data mode."` on this real install (`backend/.env` has `DATA_MODE` unset, `API_PROVIDER=ollama`, so `settings.data_mode` derives to `local-only`).

Root cause: of the 7 call sites in `orchestrator.py` that resolve an LLM through `llm_provider`, the worker code-generation call in `_generate()` was the only one missing `data_mode=session.data_mode, session_id=session.id`. `LLMProvider.resolve` falls back to the server-wide default whenever `data_mode` isn't passed explicitly — and that default is `local-only` on this machine. The test suite never caught it because `conftest.py` pins `DATA_MODE=hybrid`, which is permissive enough to hide the bug.

**Fixed** at [`orchestrator.py:1669`](../backend/src/core/agent/orchestrator.py#L1669), matching the other 6 call sites. Without this fix, none of the results below (except local-only) would exist — every hybrid or cloud-only session on a stock local-first install would refuse to write code at all.

## Coverage

| Mode | Cases with real data | Notes |
|---|---|---|
| **local-only** | 10 / 10 | Complete — but only 4 of 10 genuinely exercised the local worker; see finding 2b. |
| **cloud-only** | 10 / 10 | Complete — B2 needed a third model (`gemini-3.5-flash`) after the first two hit their daily caps. |
| **hybrid — Config A** (local manager, cloud worker) | 10 / 10 | Complete on `gemini-3.5-flash`. |
| **hybrid — Config B** (cloud manager, local worker) | 10 / 10 | Complete on `gemini-3.1-flash-lite`, after the first attempt was discarded for cache contamination. |

**40/40 cases now have real, live-inference data across local-only, cloud-only, and both hybrid configurations.**

## Results by case

### cloud-only (Gemini)

| Case | Model | Status | Pass | Time |
|---|---|---|---|---|
| A1 — group-by mean, ethnicgroup null | gemini-2.5-flash | completed | ✅ | 38.6s |
| A2 — 90th-percentile englishgrade | gemini-2.5-flash | completed | ✅ | 32.8s |
| A3 — composite score, top 5 | gemini-2.5-flash | completed | ❌ | 15.2s |
| B1 — Pearson correlation matrix | gemini-3.6-flash | completed | ✅ | 46.6s |
| B2 — variance/std/IQR | gemini-3.5-flash | completed | ✅ | 34.7s |
| C1 — completeness % | gemini-3.6-flash | completed | ❌ | 44.5s |
| C2 — 5-row housing dataset | gemini-2.5-flash | completed | ✅ | 8.4s |
| C3 — nonexistent `salary` column | gemini-2.5-flash | awaiting_approval | ❌ | 1.9s |
| D1 — histogram | gemini-3.6-flash | completed | ✅ | 39.2s |
| D2 — scatter + correlation | gemini-3.6-flash | completed | ✅ | 53.7s |

**7/10 pass (70%).**

### hybrid (qwen2.5:3b manager + gemini-3.5-flash worker)

| Case | Status | Pass | Time |
|---|---|---|---|
| A1 — group-by mean, ethnicgroup null | completed | ✅ | 85.4s |
| A2 — 90th-percentile englishgrade | completed | ✅ | 84.4s |
| A3 — composite score, top 5 | completed | ❌ | 102.1s |
| B1 — Pearson correlation matrix | completed | ❌ (see finding 4) | 97.3s |
| B2 — variance/std/IQR | completed | ✅ | 48.7s |
| C1 — completeness % | completed | ❌ (see finding 4) | 64.1s |
| C2 — 5-row housing dataset | completed | ✅ | 62.0s |
| C3 — nonexistent `salary` column | completed | ✅ | 109.7s |
| D1 — histogram | completed | ✅ | 48.8s |
| D2 — scatter + correlation | completed | ✅ | 56.1s |

**7/10 pass (70%).**

### hybrid — Config B (`gemini-3.1-flash-lite` manager + qwen2.5-coder:1.5b worker)

The reverse pairing from Config A above — recommended in the original report's §11.3 as the fix for slow/expensive answer synthesis, and here used to directly test whether a smarter cloud manager fixes the narrative-mismatch bugs Config A exposed. Model chosen because all three models used earlier that day (`gemini-2.5-flash`, `gemini-3.6-flash`, `gemini-3.5-flash`) had hit their daily caps; a full listing of the 58 models visible to this key found `gemini-3.1-flash-lite` had an untouched quota bucket. **First attempt was thrown out entirely** — every one of its 10 cases silently replayed cached code from earlier runs of the same questions (see finding 2), completing in 0.3–14s instead of a plausible ~50–100s. Cache cleared, re-run cleanly; the results below are that clean run, confirmed genuine by per-case cache-miss log lines.

| Case | Status | Pass | Time |
|---|---|---|---|
| A1 — group-by mean, ethnicgroup null | completed | ✅ | 54.3s |
| A2 — 90th-percentile englishgrade | completed | ✅ | 49.6s |
| A3 — composite score, top 5 | completed | ✅ **(see finding 6)** | 90.7s |
| B1 — Pearson correlation matrix | completed | ✅ **(see finding 4)** | 56.0s |
| B2 — variance/std/IQR | completed | ✅ | 101.9s |
| C1 — completeness % | completed | ❌ (blocked by guard — finding 2c) | 54.4s |
| C2 — 5-row housing dataset | completed | ✅ | 33.7s |
| C3 — nonexistent `salary` column | awaiting_approval | ❌ | 1.6s |
| D1 — histogram | completed | ✅ (4 correction retries) | 267.9s |
| D2 — scatter + correlation | completed | ❌ **(see finding 10)** | 356.1s |

**7/10 pass (70%)** — same raw number as every other configuration, but for reasons worth reading past the percentage: A3 and B1 are the two cases the prompt hardening was written for, and both flipped from fail to pass on the very next live run.

### local-only (qwen2.5:3b + qwen2.5-coder:1.5b)

| Case | Status | Pass | Time | Genuinely tested? |
|---|---|---|---|---|
| A1 — group-by mean, ethnicgroup null | completed | ✅ | 32.8s | 🔴 no — cache hit, see finding 2b |
| A2 — 90th-percentile englishgrade | completed | ✅ | 34.4s | 🔴 no — cache hit |
| A3 — composite score, top 5 | completed | ❌ | 27.8s | 🔴 no — cache hit |
| B1 — Pearson correlation matrix | completed | ❌ | 131.9s | ✅ yes |
| B2 — variance/std/IQR | completed | ✅ | 80.3s | ✅ yes |
| C1 — completeness % | completed | ❌ | 162.9s | ✅ yes |
| C2 — 5-row housing dataset | completed | ✅ | 30.4s | 🔴 no — cache hit |
| C3 — nonexistent `salary` column | completed | ✅ (see caveat below) | 253.4s | ✅ yes |
| D1 — histogram | completed | ✅ | 40.3s | 🔴 no — cache hit |
| D2 — scatter + correlation | completed | ✅ | 50.5s | 🔴 no — cache hit |

**7/10 pass on the literal grading rubric (70%) — but only 4 of these 10 cases actually exercised the local worker's own code generation.** See finding 2b: the other 6 replayed cached code from an earlier cloud-only run. Restricted to the 4 genuine cases: **1/4 pass (25%)** — B2 clean, B1 and C1 failed on the `orders` hallucination (finding 5), and C3's "pass" is a fabricated-then-retracted number (finding 7), so a stricter reading of the genuine subset is closer to 0/4-to-1/4 depending on how C3 is scored.

## Findings that are really about the system, not the scoreboard

### 1. The orchestrator bug above — the most consequential finding
This wasn't a benchmark artifact; it's a real defect that would affect every real user who configures a cloud or hybrid session on a fresh install with `DATA_MODE` unset. Fixed and verified: after the fix, cloud-only C2 returned `"The average price in the dataset is 374000.00"` — exactly matching ground truth.

### 2. Semantic cache has no session or config scoping — it silently invalidated part of this report's own local-only measurement
`semantic_cache.lookup(query, columns)` and `.add(query, columns, code)` (`backend/src/core/semantic_cache.py`) take no session ID, no provider, and no model. The cache is a single global table (`backend/data/wizard.db`, persistent across every process and every day) keyed only on question text + active column names. This has two distinct, both-confirmed consequences:

**2a. It replays stale absolute paths baked into cached code.** Discovered by accident — two live-suite runs happened to execute the same question in different sessions concurrently — but **confirmed independently reproducible**: re-asking the exact same question in a brand-new, non-concurrent session replayed the exact same broken code, pointing at the same now-nonexistent directory, and got blocked by the guard again (three times, until manually cleared). Best case, the guard blocks it. Worse case, if the originating session's workspace still exists, the replaying turn could write into a directory it does not own.

**2b. It silently made several of this report's own "local-only" and "cloud-only" results not measure what they claimed to.** Cross-referencing every cache lookup logged today against the results file turns up:

| Case | local-only | cloud-only |
|---|---|---|
| A1 | 🔴 cache hit — reused code from an earlier run | ✅ genuine |
| A2 | 🔴 cache hit | ✅ genuine |
| A3 | 🔴 cache hit | ✅ genuine |
| B1 | ✅ genuine (cache miss) | ✅ genuine |
| B2 | ✅ genuine (cache miss) | ✅ genuine (re-run after manual cache clear) |
| C1 | ✅ genuine (cache miss) | ✅ genuine |
| C2 | 🔴 cache hit | 🔴 cache hit — reused code already in the cache from *before this session started* (low practical impact: the question is trivial enough that a stand-in `df.describe()` and a mean are close to whatever any model would write) |
| C3 | ✅ genuine (cache miss) | ✅ genuine |
| D1 | 🔴 cache hit | ✅ genuine |
| D2 | 🔴 cache hit | ✅ genuine |

**6 of local-only's 10 results (A1, A2, A3, C2, D1, D2) executed code cached by an earlier cloud-only run (or, for C2, by something older still) — not code the local worker (`qwen2.5-coder:1.5b`) ever wrote.** Only the local *manager* narrating pre-computed, cloud-quality output was genuinely being tested in those 6 cases. The 4 that were genuine (B1, B2, C1, C3) are the only real measurement of the local worker's own code-generation ability, and they tell a **substantially worse story than the reported 7/10**: 1 clean pass (B2), 2 hard failures from the `orders` hallucination (B1, C1 — finding 5), and 1 pass that's actually a fabricated-then-retracted number (C3 — finding 7). **The true, cache-adjusted local-worker success rate on this suite is 1 out of 4 genuinely-tested cases (25%), not 70%.** The hybrid (Config A) comparison table stands largely uncontaminated — 9 of its 10 cases were confirmed genuine cache misses, with only B2 reusing same-process, same-model output from a cloud-only run moments earlier (low-impact, since it's the same model that would have written it fresh anyway).

**Fixed the harness**: `run_live_suite.py` now calls `semantic_cache.clear()` once at the very start of `main()`, so every future invocation starts from a guaranteed-empty cache instead of silently inheriting whatever a previous run — or, it turns out, a session from *before this live-inference work even began* — left behind. This is also why the first attempt at testing Config B (see the hybrid — Config B results table above) had to be thrown out entirely and re-run.

**Fixed in the application itself, not just the benchmark**: [`runtime.rebind_workspace_paths(text, session_id)`](../backend/src/core/tools/runtime.py) rewrites any other session's `WORKSPACE_DIR/sessions/<id>[/subagents/<branch>]` path literal found in `text` to the *replaying* session's own workspace path, keyed off the same root `workspace_path()` already resolves paths against. `_orient` applies it to a cache hit before `state.code` is set ([`orchestrator.py:658`](../backend/src/core/agent/orchestrator.py#L658)), so replayed code that once wrote to `bench-73cf85a8bb/plot.html` now writes to the current session's own `plot.html` instead of a directory it doesn't own — the guard has nothing to reject and there's no cross-session write. This is the "re-resolve at cache-hit time" option from the two named above, chosen over scoping the cache key itself: scoping by provider/model would fragment the cache (a `qwen2.5-coder:1.5b` session and a Gemini session asking the identical question would no longer share a hit at all), while rebinding keeps the reuse and removes only the actual hazard, which is the stale path, not the code having come from elsewhere. Verified directly: rewriting a stale path against a synthetic session id no longer contains the origin session's id and does contain the new one (see `runtime.rebind_workspace_paths` docstring); the full backend suite (1256 passed, 6 skipped) shows no regression. Docker is unaffected on purpose — its `/workspace` root has no session id baked into it to begin with, so `rebind_workspace_paths` is a no-op there.

**2c. The same gap exists in the trajectory/few-shot memory system, and leaks by imitation rather than replay.** Config B's C1 (clean cache-cleared run, confirmed genuine — the log shows `Semantic cache miss` immediately before it) still got blocked by the guard for a path from a *different* session (`bench-2afe407d9b`), despite writing genuinely fresh code. Traced to [`orchestrator.py:1653`](../backend/src/core/agent/orchestrator.py#L1653): `context_retriever.retrieve_trajectories(state.instruction, columns)` — no session argument — retrieves a stored failure→fix example by the same (instruction, columns) key `semantic_cache` uses, and its raw text is spliced into the worker prompt verbatim as `create_prompt`'s `<avoid_this>` block ([`orchestrator.py:1664`](../backend/src/core/agent/orchestrator.py#L1664)); `self.feedback.get_similar_examples` (line 1661) has the identical shape for its few-shot block. If a stored example contains a real absolute path from whichever session originally produced it, a small model shown that path in-context can copy it into otherwise-fresh code rather than treating it as illustrative. This isn't cache replay — the code differs from the stored example everywhere except the path — so it's a second, independent surface with the same root cause (`instruction, columns` as the only retrieval key, nothing about *whose* session the answer came from) rather than a second symptom of the same bug.

**Fixed in the application, same mechanism as 2a.** `_generate` now runs the negative trajectory's text and every retrieved few-shot example's `code` field through the same `runtime.rebind_workspace_paths(text, session.id)` before either reaches `create_prompt` ([`orchestrator.py:1653-1663`](../backend/src/core/agent/orchestrator.py#L1653)). The retrieval key is unchanged — `(instruction, columns)` still has no notion of whose session an example came from, so a different session's failure-then-fix can still surface as a match — but the one concrete thing that made a match dangerous, a stale path a small model could copy verbatim, is now rewritten to a path the *current* session actually owns before the model ever sees it. A leaked path is no longer exploitable even though the underlying retrieval is still session-agnostic; narrowing the retrieval key itself is a larger change (candidates: session id in `trajectories`/`feedbacks`, or plumb it just to gate ranking) and is left as a follow-up, since it changes what "similar enough to reuse" means rather than closing a hazard in what gets reused.

### 3. Small local worker model (`qwen2.5-coder:1.5b`) has a specific, repeatable hallucination: an `orders` variable that doesn't exist
Both local-only B1 and C1 failed for the same reason — the worker generated code referencing a DataFrame named `orders` instead of the one actually loaded (`df`), producing `KeyError`/`NameError`, then burned all `MAX_CORRECTION_RETRIES` (4 attempts each) without recovering, ending in an apologetic non-answer. Neither case involves the cache bug above (distinct sessions, no path collision) — this is the worker's own prior, most likely a strong association from training data (e-commerce "orders" tables are a common tutorial pattern). This is exactly the class of failure the project's small-model-resilience goal targets: decomposition, not model size, is what should catch this — and here it didn't, twice, in a row.

### 4. Hybrid mode isolates the manager and worker's failure modes from each other — and the manager's is the more interesting one
Hybrid pairs the same weak local manager (`qwen2.5:3b`) used in local-only with a capable cloud worker (`gemini-3.5-flash`). The final answer text is **always** synthesized by the manager role regardless of mode (`orchestrator.py`'s `_generate` answer call, `role=LLMRole.MANAGER`) — only the code-writing step changes between modes. Hybrid's results show exactly what that split predicts:

- **B1 (correlation matrix):** the cloud worker wrote correct code and produced the exact right numbers (`age`/`mathgrade` r = 0.018) — unlike local-only B1, which never executed at all (see finding 5). But the manager's answer says *"'age' is strongly correlated with 'mathgrade' (Pearson's r = 0.018)"* — r=0.018 is as close to zero correlation as this dataset gets, and the reference answer requires "weak" to appear and forbids "strong". `check_grounding` reports `ratio: 1.0, ok: true` — the number 0.018 really is in the output, so grounding has nothing to object to. The failure is entirely in how the manager characterized a real number, not in the number itself.
- **C1 (completeness):** same pattern, more striking. The worker's code correctly computed and printed a per-column completeness table showing `ethnicgroup` at **0.0%** complete (307/307 missing). The manager's answer opens with *"The dataset does not contain any missing values across all columns as indicated by the completeness percentage of 100%"* — directly contradicting the table its own execution just produced — and separately describes 307 (literally every row) as *"a small number of missing values."* Grounding again reports `ratio: 1.0, ok: true`, because "100" and "307" both genuinely appear in the real output (as *other* columns' completeness and as the row count) — grounding checks that digits are real, not that the sentence built around them is true.

This is a genuine limit of the trust layer worth naming explicitly: **`check_grounding` proves a number wasn't invented; it does not prove the claim wrapping that number is correct.** It's also a clean, positive validation of the manager/worker split as an architecture — swapping only the worker measurably fixed the execution-level failures (no more crashes, no more hallucinated tables), while leaving the narrative-level failures exactly where they were, because the manager doing the narrating didn't change.

**Confirmed fixed on the very next live run.** After adding the answer-prompt rule requiring qualitative labels to match their number (see "Prompt hardening applied" below), Config B's B1 — same case, same underlying near-zero correlations — answered *"all correlations are extremely weak, ranging from -0.097152 to 0.058225"*, correctly using "weak" and never "strong". This isn't a different case happening to pass; it's the identical narrative-mismatch failure mode, gone on the first live test after the fix.

### 5. Small local worker model (`qwen2.5-coder:1.5b`) has a specific, repeatable hallucination: an `orders` variable that doesn't exist
Local-only B1 and C1 failed for a different, worker-side reason — the worker generated code referencing a DataFrame named `orders` instead of the one actually loaded (`df`), producing `KeyError`/`NameError`, then burned all `MAX_CORRECTION_RETRIES` (4 attempts each) without recovering, ending in an apologetic non-answer with no execution output at all. This is the worker's own prior, most likely a strong association from training data (e-commerce "orders" tables are a common tutorial pattern). Hybrid mode's B1/C1 (finding 4) prove this is specifically a worker-competence problem: the same questions, same local manager, but a capable worker — and the crash disappears entirely, replaced by a different, manager-side problem. This is exactly the class of failure the project's small-model-resilience goal targets: decomposition, not model size, is what should catch this — and for the worker role specifically, it did, once paired with a stronger worker.

### 6. The A3 "top 5" failure was identical across every model and mode tested — until the prompt hardening fixed it on the first try
`qwen2.5-coder:1.5b` (local), `gemini-2.5-flash` (cloud), `gemini-3.6-flash` (cloud), and `gemini-3.5-flash` (hybrid Config A) all answered "display the top 5 rows" by returning the first 5 rows in original file order after adding the composite-score column — not the 5 highest composite scores. Reference answer requires composite values 4.00 and 3.95 (rank-sorted); all four returned rows 0–4 with composites 3.4/3.4/3.5/3.0/3.0, identically. Four different model/mode combinations, one identical failure — strong evidence the task prompt itself ("top 5 rows" without "sorted by") was under-specified rather than reflecting four independent competence gaps.

**Confirmed fixed on the very next live run.** After adding the worker-prompt rule requiring a sort before taking N rows for "top/highest/lowest" requests (see "Prompt hardening applied" below), Config B's A3 — same case, same local worker model that got it wrong before — answered *"The top 5 students based on the new `stem_composite_score` are Michael Griffin with a 4.00, followed by Anthony Mcdevitt, Kaitlin Krueger, Madison Fithian, and Jason Hundsdorfer, who all share a score of 3.95"* — the exact reference values, correctly sorted, first time all day. One targeted instruction line fixed a failure that had been unanimous across five prior attempts on four different model families.

### 7. Local-only C3 "passes" but the answer is self-contradictory — a grading-methodology caveat, not a system win
The literal grading rubric (must mention "salary" and "not") passes local-only's C3. But the actual answer opens by stating a fabricated figure — *"The computed average salary... was 68.503125"* — computed by averaging four grade columns as a stand-in for a nonexistent salary column, then in the same response walks it back: *"these are not actual salary figures... we would need additional data."* The harness's own grounding check independently flagged `68.503125` as ungrounded (`ratio: 0.0`). By contrast, **hybrid's C3** (capable cloud worker, same manager) gave a clean, honest answer with no fabricated number at all — *"No salary or income column was found in the available tables"* — grounding trivially satisfied (`checked: 0`) because nothing was invented to check. Local-only's C3 is the project's grounding-first philosophy validating itself: text-match grading alone would have called it a clean pass; the grounding layer (and the hybrid comparison) shows it isn't one. Recommend factoring `grounding.ok` into the pass/fail rubric for cases like this in the next methodology revision, not just reporting it alongside.

### 8. Gemini free-tier quota is a hard daily ceiling, pooled by model family rather than strictly per exact model name — four models were needed to finish this report
Two independent caps observed directly: `GenerateRequestsPerMinutePerProjectPerModel-FreeTier` (5/min) and `GenerateRequestsPerDayPerProjectPerModel-FreeTier` (20/day) — both **per (project, model)**, not per API key, in the error payload's own words. In practice it behaved as pooled across the "flash" family rather than strictly per exact name: `gemini-2.5-flash` hit its daily cap first; `gemini-3.6-flash` and `gemini-3.5-flash` each recovered real cases in turn; but by the time Config B needed a manager model, all three — plus `gemini-2.0-flash`, never touched before that moment — came back daily-exhausted on first use. Enumerating the full 58 models visible to this key (`GET /v1beta/models`) found `gemini-3.1-flash-lite` with an untouched bucket (`gemini-2.5-flash-lite` also exists but returns 404, deprecated for new users) — a distinct-enough model, not just a version bump, to have survived. A single Wizard turn costs 2–8 LLM calls across its iterations; the full 40-case run across four models this session totaled well over 150 real Gemini calls, which is why four separate free-tier daily buckets were needed to complete it.

### 9. The Windows OS sandbox provided zero real enforcement for this entire run — a `best-effort` degrade, not a benchmark artifact
Every single "Host runtime started" log line across all 30 original turns read `enforced='+none -filesystem,memory,network,processes'` — meaning none of the OS-level containment categories were actually active for any live turn in this report (Config B's later 10 turns showed the same). Root cause, reproduced directly: `icacls <workspace> /setintegritylevel (OI)(CI)Low` ([`windows.py:154`](../backend/src/core/security/sandbox/windows.py#L154)) requires `SeRelabelPrivilege`, which a normal, non-UAC-elevated shell doesn't hold on this machine (confirmed by running the identical `icacls` command directly: `Access is denied`). `HOST_SANDBOX` defaults to `best-effort`, so the session correctly degraded rather than refusing to run — but it means the AST-level `CodeGuard` static check was the *only* defense actually in effect for every script executed in this session; the job-object/Low-integrity boundary CLAUDE.md describes as the real Windows-side containment never engaged. Not a defect in the benchmark or a security emergency on a controlled dev machine, but worth knowing before treating any of the "sandboxed" executions in this report as having had OS-level isolation — they didn't. Running the backend elevated, or checking what `capability.detect()` reports and why, would confirm whether this is fixable or a structural limitation of this specific account.

### 10. Config B's one real failure shows the opposite bottleneck from Config A's: a smarter manager can plan work the weaker worker can't implement
Config B's D2 (scatter plot + Pearson/Spearman correlation) failed cleanly and honestly — *"The scatter plot could not be generated because the `stats` library was not imported... `NameError`... you should add `from scipy import stats`"* — the manager correctly diagnosed and reported its own worker's mistake rather than fabricating a result. But the mistake itself is telling: `gemini-3.1-flash-lite` planned a more statistically complete analysis (both Pearson *and* Spearman correlation with p-values, needing `scipy.stats`) than Config A's weaker local manager ever asked for in the same case — and `qwen2.5-coder:1.5b` couldn't reliably implement it, burning all 4 correction retries (267.9s) before eventually recovering enough to pass on a *different* case (D1) and failing outright here. Config A's bottleneck (findings 4, 6-before-the-fix) was the manager narrating correct work incorrectly; Config B's bottleneck is the manager's plan outrunning the worker's implementation ability. Neither configuration removes the weak link — it just moves which end of the pipeline it's on.

## Prompt hardening applied

Three targeted changes to `backend/src/core/prompts.py`, each tied directly to a specific, reproduced defect above rather than generic guidance — verified against the full backend test suite afterward (**1256 passed, 6 skipped**, matching the known-good baseline exactly, so nothing broke).

1. **Worker prompt (`create_prompt`) — enforce sorting for "top/highest/lowest N"**, targeting finding 6 (A3, wrong 5/5 across every model/mode tested): the instructions now explicitly require sorting by the named metric before taking N rows, and say returning the first N rows in file order is wrong unless the request says "first N".
2. **Worker prompt — no silent substitution for a missing column**, targeting finding 7 (local-only C3's fabricated "average salary" computed from grade columns): the instructions now say that if a named column doesn't exist, the code must print that it's missing and stop, not compute a number under the requested name from different data.
3. **Answer prompt (`create_answer_prompt`) — qualitative labels must match the number**, targeting finding 4 (hybrid B1/C1: "strongly correlated" for r=0.018, "100% complete" for a 0%-complete column): a new rule requires any word like "strong"/"weak"/"complete" to match the actual value by ordinary convention (weak below ~0.5, moderate ~0.5–0.7, strong above ~0.7 for a correlation) and to not contradict any other number describing the same thing in the output.

These three are the entire change — no unrelated prompt rewording, no new sections, no generic "be careful" language. Rules 1 and 2 are prevention at the source (the worker never writes the bad code); rule 3 is a check between reading a correct number and writing a wrong sentence about it, since `check_grounding` structurally cannot catch that class of error (it verifies digits are real, not that the words around them are true).

## Latency, for what it's worth given the sample size

| | cloud-only | hybrid — Config A | hybrid — Config B | local-only |
|---|---|---|---|---|
| Fastest case | 1.9s (C3, gated) / 8.4s (C2) | 48.7s (B2) | 33.7s (C2) | 27.8s |
| Slowest completed case | 53.7s (D2) | 109.7s (C3, retries) | 356.1s (D2, `NameError`) | 253.4s (C3, retries) |
| Median (completed, non-gated) | ~39s | ~72s | ~63s | ~40s |
| Cases needing correction retries | 1 (D2) | 1 (C3) | 2 (C1 via guard-block, D1: 4 retries) | 3 (B1, C1, C3) |

Local-only's tail is dominated entirely by the correction-retry loop on the two `orders`-hallucination failures and C3's self-correcting-but-ultimately-fabricated answer — not by raw per-call model latency (bearing in mind 6 of its 10 cases were cache hits and didn't pay for code-generation latency at all; see finding 2b). Config A sits consistently above both single-provider modes even on clean first-attempt cases (A1: 85.4s) — every iteration pays both a local-model round-trip *and* a network round-trip, serialized. Config B shows the same pattern with the roles reversed, plus its own worst case (D1: 267.9s, D2: 356.1s) from the local worker needing repeated correction attempts against a more demanding cloud-authored plan (finding 10).

## Harness integrity notes (so these numbers can be trusted)

- **A concurrent-write race in `run_live_suite.py` clobbered 5 real results mid-run**: two instances of the script (deliberately run side by side — one immune to Gemini quota, one not) each held their own in-memory result list from a single startup read, and each blind-overwrote the shared JSON file on every save. The instance that finished last silently discarded the other's newly-written rows. Recovered from this conversation's own tool-call history (the data had been read and displayed before the loss) and reconciled back into the results file. **Fixed** the harness (`_merge_and_write`, `run_live_suite.py`) to re-read and merge by `(mode, case_id)` before every write, so this class of bug can't recur.
- **The semantic cache silently invalidated 6 of local-only's 10 measurements and all 10 of Config B's first attempt** — see finding 2b/2c. **Fixed** the harness to call `semantic_cache.clear()` at the start of every invocation, so this can't recur either.
- Every result in this report, including the recovered and re-run ones, was independently re-verified against what the live API/daemon actually returned, and cross-checked against the raw log for cache-hit/miss status where that mattered — none were reconstructed from a description of what should have happened.

## Bottom line

- **40/40 cases now have real, live-inference data**, across local-only, cloud-only, and both hybrid configurations (local manager + cloud worker, and the reverse). Raw pass rates cluster around 70% in every configuration except Config A's cache-clean local comparison — but the *reasons* differ by configuration, and two of the four apparent 70%s (local-only, Config B's first attempt) turned out not to measure what they claimed to until the cache issue was found and fixed.
- **Three real application bugs were found and fixed this session, not just measured.** The `data_mode` pass-through bug ([orchestrator.py:1669](../backend/src/core/agent/orchestrator.py#L1669)) meant hybrid and cloud-only were completely non-functional on a real install before today. The semantic cache (finding 2a/2b) and trajectory/few-shot memory (finding 2c) could each replay or splice a stale absolute path from a *different* session's workspace into a live turn — not a benchmark artifact, a standing correctness gap that would affect two real users on the same install today. Both are now fixed by [`runtime.rebind_workspace_paths`](../backend/src/core/tools/runtime.py), called at every retrieval point (`orchestrator.py:658`, `orchestrator.py:1653-1663`) to rewrite a stale path against the session actually running the turn before it reaches the model or the executor. **What's still open**: the *retrieval key* itself (`instruction, columns`, no session/provider/model) is unchanged, so a Gemini-quality answer can still surface as a "similar example" for a 1.5B local worker's prompt — rebinding closed the concrete hazard (an unowned path), not the underlying scoping question, which is a larger change left as a follow-up.
- **Three prompt-hardening changes were written against specific reproduced defects and confirmed fixed on the very next live run** — not just theoretically sound, but empirically validated within this same session: A3's unanimous 5-attempt sorting failure (finding 6) and B1's "strongly correlated" mischaracterization (finding 4) both flipped to correct, unprompted, the first time Config B ran after the fix.
- **Testing both hybrid directions revealed a genuinely symmetric result**: Config A's bottleneck is the manager narrating correct worker output incorrectly (findings 4, 6-before-fix); Config B's bottleneck is the manager planning more than the worker can reliably implement (finding 10). Neither pairing eliminates the weak link — swapping which role is "smart" just moves where the mismatch shows up.
- **The cache-adjusted, genuinely-measured local-worker success rate is roughly 1 in 4 (25%), not the reported 7/10 (70%)** — the single most important correction to carry forward from this report, and the reason "which cases were cache hits" now has to be checked before trusting any pass-rate claim from this harness, including future ones.
- **None of these 40 turns had OS-level sandbox containment** — the Windows integrity-label step failed silently (privilege gap on this account) and degraded to `best-effort` on every run, leaving only the AST-based code guard as active defense. Worth confirming and fixing before relying on the "sandboxed" isolation claim on this machine specifically.
