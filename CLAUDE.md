# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Wizard w1** — a local-first autonomous data analysis agent. A FastAPI backend orchestrates two local Ollama models (a "manager" that reasons and a "worker" that writes code), executes the generated Python inside a per-session Docker sandbox, and streams reasoning, code, stdout and the final answer to a Next.js client over one WebSocket.

Monorepo: `backend/` (Python 3.11, FastAPI) + `frontend/` (Next.js 16 / React 19 / Tailwind v4).

## Commands

### Full stack
```bash
ollama pull qwen3:8b && ollama pull qwen2.5-coder:7b   # any two models; nothing is pinned
docker compose up --build -d                 # backend :8000, frontend :3000
docker compose --profile redis up -d         # optional shared cache/queue
```

### Backend
```bash
pip install -r requirements.txt              # root file, not backend/
pip install -r requirements-optional.txt     # only for Redis or an OpenAI gateway

uvicorn src.api.api:app --reload --port 8000 # run from backend/
python backend/main.py path/to/data.csv      # CLI REPL over the same stack

pytest                                       # from repo ROOT (pyproject sets testpaths/pythonpath)
pytest backend/tests/unit -q                 # one layer
pytest backend/tests/unit/test_code_guard.py::test_repair_strips_markdown_fences

ruff check . --fix && ruff format .          # CI runs `ruff check` + `ruff format --check`
```

`asyncio_mode = "auto"`, so async tests need no decorator.

**Tests never touch Docker, Ollama or the network.** `backend/tests/conftest.py` sets `SANDBOX_ENABLED=false` and `EMBEDDINGS_FORCE_FALLBACK=true` *before* importing `src`, because `Settings` is instantiated at import time. Keep new env pinning at the top of that file.

### Frontend
```bash
cd frontend && npm ci
npm run dev
npm run lint && npx tsc --noEmit && npm run build   # the three CI gates
```

## Architecture

### One request path

`POST /api/chat` and `WS /ws/chat` both call `AnalysisOrchestrator.run`. The transport only translates events into frames — it contains no workflow logic. (Historically the WebSocket handler re-implemented the node loop by hand, and the two copies drifted until the semantic cache and the fast-path router applied to REST only.)

### Event protocol — [events.py](backend/src/core/agent/events.py)

The orchestrator knows nothing about WebSockets; it emits typed events to an `Emitter`. `EventCollector` buffers them for the REST path and for tests; `WebSocketEmitter` serialises them onto a socket.

Frames: `session`, `status`, `step_start`/`step_end`, `reasoning_delta`, `plan_delta`, `content_delta`, `code`, `stdout`, `artifact`, `approval_required`, `warning`, `error`, `final`.

Investigation frames, added with the agentic loop: `iteration_start`, `action`, `observation`, `finding`, `plan_revised`, `assumption`, `verification`. The frames above are all still emitted, so a client that ignores these degrades rather than breaking. `observation` closes the most recent `action` that has none — the backend never correlates them by id.

`reasoning_delta` vs `plan_delta` are split *during* streaming by tracking the `<thought>` tag boundary incrementally ([`_stream_plan`](backend/src/core/agent/orchestrator.py)), so the UI can show a live thinking panel that switches to the plan at the right moment.

### Workflow — [orchestrator.py](backend/src/core/agent/orchestrator.py)

**This is a loop, not a pipeline.** Each iteration the manager sees what has actually run and chooses the next move; the run ends when it says it can answer, or the budget is spent.

```
orient (plan) → [approval gate] → loop → verify → answer
                                    ↑ ↓
                     inspect / code+execute / consult / reflect
                                      ↓
                                  correct   (bounded by MAX_CORRECTION_RETRIES)
```

- The old shape fixed a plan before touching the data and fed 200 characters of each step's output into the next. It could not recover when the data contradicted the plan. [DABstep](https://arxiv.org/abs/2506.23719) measures the gap: hard tasks need 6+ dependent steps, the best model scores 14.55% on them vs 76.39% on single-step ones, and planning is the largest error category.
- Actions live in [actions.py](backend/src/core/agent/actions.py). `parse_decision` **never raises** — malformed model output resolves to a default (`code` mid-run, forced `answer` on the last iteration). The loop is worthless if a small model saying `**Action:** Code.` derails it.
- `inspect` is answered deterministically from the frame (`Session.inspect`), costing no LLM call. That is what makes it worth offering as an action.
- Budgets come from `settings.budget_for(mode, parameter_size)` — see the config section. Every iteration is a manager round-trip.
- Modes: `auto` (agent picks its depth), `fast` (one shot, **and no verification** — it is the most expensive thing a turn can do), `deep`. `planning` is a legacy alias meaning "deep, but gate the plan".
- Plan approval is opt-in (`AGENT_REQUIRE_APPROVAL`). A plan containing `SEARCH: "…"` **always** halts for consent regardless — that leaves the machine.
- An approved plan skips `_orient` entirely, which is where the gate lives, so it cannot re-fire. It must also not be downgraded to `fast`: approving work is not asking for less of it.
- **The final answer is synthesised by the manager from real execution output** (`create_answer_prompt`). Do not reintroduce client-side cleanup of the response — the frontend used to regex-strip tracebacks, code blocks and numeric rows out of it, which deleted legitimate results.

### Trust layer — [grounding.py](backend/src/core/agent/grounding.py)

Deterministic, no LLM calls, and it **reports rather than edits** — post-processing model output is exactly the mistake above.

- `check_grounding` flags numbers in the answer that appear in no execution output. Tolerance comes from the *answer's own* precision (`3.14` for an output of `3.14159` is reporting, not invention) plus magnitude words (`1.23 million`).
- `assumptions_from_code` reads silent decisions back out of the code that ran — `dropna`, `how='inner'`, `nlargest`, `errors='coerce'`. Each changes what the number means.
- `_verify` re-derives the headline result by a different route and looks for `VERIFIED:` / `MISMATCH:`. A wrong join grain produces a confident, plausible, wrong number that no self-review catches, because the reviewer is the model that made it.

### Execution — [execution.py](backend/src/core/execution.py)

`CodeExecutor.execute` is the **only** way generated code reaches an interpreter. It guards first, then runs in the session's container, falling back to a restricted in-process interpreter when Docker is unreachable (reported via `ExecutionResult.sandboxed=False` and a warning). Semantic cleaning on upload goes through here too.

### Security — [code_guard.py](backend/src/core/security/code_guard.py)

One AST-based analyzer, not regex. It distinguishes:
- **policy violation** → stop and tell the user (`GuardVerdict.ok=False`)
- **syntax error** → retryable, feed back into the correction loop (`verdict.syntax_error`)

Blocks banned modules, banned builtins, interpreter-internals attributes, bare `__builtins__`, reflection with a computed or dunder attribute name, and literal file paths outside `/workspace`. The container is the real boundary; this is defence in depth that also covers the Docker-less path.

### Sandbox — [sandbox.py](backend/src/core/tools/sandbox.py)

`SandboxPool` creates **one container per session**, lazily. `DAEMON_SCRIPT` is a string literal injected via tar — edit execution semantics inside that string.

- Length-prefixed (`>I`) JSON over TCP:5005. Actions: `execute`, `inspect_variables`, `reload_dataset`, `reset`, `ping`.
- `df` is **not** passed per call; the daemon preloads it from the session's bind-mounted `dataset.feather`. `Session._materialize` writes it; `reload_dataset` refreshes it without recreating the container.
- **Every** session table is preloaded into `tables['<table_key>']` from `workspace/tables/*.feather`, with `df` still bound to the active one. Cross-table questions need them all in the namespace at once. `remove_dataset` must call `reload_dataset()`, or the deleted frame stays queryable.
- The Docker-less fallback mirrors this: `CodeExecutor.execute` takes a `tables` mapping, supplied from `Session.tables`. The container ignores it — it already read them off the mount.
- The daemon records its own PID; `interrupt()` signals it directly. Signalling PID 1 would kill the container, since PID 1 is `sleep infinity`.
- Limits: `mem_limit`, `pids_limit`, optional `cpu_quota`, `cap_drop=ALL`, `no-new-privileges`, plus a socket deadline per execution.

### Sessions — [session.py](backend/src/core/session.py)

Every browser gets a `Session`: its own datasets, **reference documents**, catalog, chat history, workspace directory and container. Resolved from the `X-Session-Id` header (or `?session=`), TTL-reaped, and capacity-bounded. There is no global dataset state.

`DatasetHandle.table_key` is the sanitised name generated code addresses the table by (`Q3 sales (final).csv` → `tables['q3_sales_final']`). It also names the file under `workspace/tables/`.

### Reference documents — [ingest/documents.py](backend/src/core/ingest/documents.py)

Data dictionaries, metric definitions, business rules — `.md/.txt/.rst/.html` always, `.pdf/.docx` when `pypdf`/`python-docx` are installed (imported inside the function, so neither is required to start). Chunked on **paragraph** boundaries, not fixed width: a definition cut in half yields two chunks that each retrieve well and neither of which states the rule. Retrieval goes through `embedding_service`, so it degrades to lexical overlap with no model loaded.

`.txt` is deliberately claimed by both loaders — a tab-delimited export and a plain-text dictionary are both real. The endpoint decides which. Nothing structured (`.csv`, `.parquet`, `.xlsx`) may appear in the document list; a test pins that.

### Context budgeting — [retriever.py](backend/src/core/rag/retriever.py) + [prompts.py](backend/src/core/prompts.py)

`generate_system_context` does not dump the whole frame. Columns are selected by relevance to the question (columns named in the question are always kept), and memories, trajectories and few-shot examples are retrieved semantically. Everything degrades to lexical scoring when no embedding model is loaded.

"Named in the question" goes through `mentions_column`, which matches on **word boundaries**. A substring test looks equivalent and is not: a column called `C` matches inside "check" and `id` matches inside "provide", so nearly every column reported as explicitly requested and the budget stopped budgeting.

`prompts.TOOLKIT` declares the libraries available to generated code, and is **filtered by what is actually importable** when Docker is unreachable — the container has the full set, the API process does not. Anything added to `backend/docker/Dockerfile` must be added to `TOOLKIT` too, or the model never learns it can use it. That is not hypothetical: scikit-learn and statsmodels were installed for months while the prompt advertised only pandas and matplotlib.

### Infrastructure — [infra/](backend/src/core/infra/)

`get_cache()` and `get_queue()` return in-process implementations by default. Setting `REDIS_URL` (with `redis` installed) swaps in Redis; if Redis is configured but unreachable, the cache degrades rather than failing the app. Nothing requires Redis.

### Persistence — [database.py](backend/src/core/database.py)

One SQLite file, `backend/data/wizard.db`, accessed through `db_mgr`. **Connections are pooled per thread and closed explicitly**, with WAL and a busy timeout — FastAPI dispatches blocking work through `asyncio.to_thread`, so several threads hit this database concurrently.

Tables: `semantic_cache`, `trajectories` (failure→fix pairs), `feedbacks`, `working_memory`, `chat_messages`, `schema_registry`. Additive column migrations run on boot from the `MIGRATIONS` tuple.

### Models — [llm/](backend/src/core/llm/)

`llm_provider` builds and caches clients keyed by (provider, endpoint, model, temperature, …), so per-session model selection is cheap. Every entry point has a streaming twin (`astream`, `stream_to`).

**The provider is per-request, not process-wide.** `settings.API_PROVIDER` is only the default. `ModelPreferences` stores a provider per *role*, so one run can plan on Ollama and generate code on LM Studio; `ModelSpec` therefore carries the resolved `base_url`, and that URL is part of the cache key — without it the same model name on two backends collides. Never read a provider URL directly from `settings`; go through `settings.provider_root_url` / `provider_openai_base_url` / `provider_api_key`, keyed by the provider actually in play.

`model_registry` enumerates what is really installed, per provider and cached per provider:
- **Ollama** → `/api/tags`
- **LM Studio** → `/api/v0/models` (native: real `type`, quantization, context length, load state), falling back to `/v1/models`
- **Gateways** → `/v1/models`

Empty results are cached too, for a shorter TTL — a refused connect costs seconds, and one page load asks for both the list and a suggestion. `available_providers()` must stay network-free; it renders on every page load.

### Config — [config.py](backend/src/config.py)

Pydantic-settings singleton reading `backend/.env` (see `backend/.env.example`). Notes:

- `API_PROVIDER` is the *default* provider, not a global switch — see the models section. `MODEL_TYPE` exists only so older `.env` files still validate.
- `LMSTUDIO_BASE_URL` is stored as a bare root; a pasted `/v1` suffix is stripped by a validator, because discovery needs `/api/v0` off the same root. LM Studio binds loopback only until "Serve on Local Network" is enabled, which is the usual cause of an empty picker from inside Docker.
- `LLM_NUM_CTX` reaches Ollama only. OpenAI-compatible servers fix context length when the model is loaded, so it is deliberately not sent there.
- `cors_origins` / `cors_allow_credentials` are resolved together: a wildcard origin forces credentials off, because the combination is invalid in every browser.
- `PLOT_FORMAT` is coupled across two places — the visualization rule in `create_prompt` and the artifact branch in `_execute`. Change both.
- `SANDBOX_ENABLED=false` disables container creation entirely; `EMBEDDINGS_FORCE_FALLBACK=true` skips the model download. Both are set in CI.
- **`MODEL_NAME` / `WORKER_MODEL_NAME` / `VISION_MODEL_NAME` are empty by default**, meaning "use whatever this provider has installed", resolved through `model_registry.suggest`. Setting one pins it. They used to be hardcoded Ollama tags, which made those two models load-bearing — both 404 on LM Studio and on every gateway.
- `AGENT_TIER` (`auto`/`compact`/`balanced`/`full`) sizes the loop. On `auto` it is inferred from the manager model's parameter count via `tier_for_parameter_size`: <4B compact, 4–30B balanced, ≥30B full. Gateways report no size and get `balanced` — guessing `compact` would cripple the strongest models available.
- `settings.budget_for(mode, parameter_size)` is the single place mode and tier combine. `TierBudget` carries its own `tier` name so callers never reverse-match numbers back to a tier. `fast` returns `allow_verification=False` — verification is a second code generation *and* a second execution.
- `AGENT_MAX_ITERATIONS` is a hard ceiling above the tier, deliberately not derived: a runaway loop on a paid gateway is a billing incident.

## Frontend

Four routes, no landing page — `/` **is** the workspace:

| Route | Component |
|-------|-----------|
| `/` | [chat-shell.tsx](frontend/components/chat-shell.tsx) |
| `/data` | [pages/data-workbench.tsx](frontend/components/pages/data-workbench.tsx) |
| `/models` | [pages/models-workbench.tsx](frontend/components/pages/models-workbench.tsx) |
| `/settings` | [pages/settings-workbench.tsx](frontend/components/pages/settings-workbench.tsx) |

[app-shell.tsx](frontend/components/app-shell.tsx) renders the nav rail once from the root layout. Keep it there: mounting it per page would tear down and rebuild the chat WebSocket on every route change.

- [use-chat-stream.ts](frontend/lib/use-chat-stream.ts) owns one persistent WebSocket with heartbeat and exponential-backoff reconnect, and appends each `*_delta` frame to the live message. This is genuine token streaming; do not reintroduce the timer-based word reveal.
- The composer's segmented control is **Auto / Fast / Deep** — analysis *depth*, not workflow. The pair it replaced ("Plan first" / "Direct") described whether you would be asked to approve a plan, which is a permissions question and now lives on `/settings`.
- [chat/investigation-trail.tsx](frontend/components/chat/investigation-trail.tsx) renders what the agent chose to do, move by move; [chat/answer-trust.tsx](frontend/components/chat/answer-trust.tsx) renders how far the answer can be trusted. Both are collapsed by default — the answer is the headline.
- Grounding and verification arrive **twice**: as a warning string (for REST clients with no richer surface) and as structured fields. `message.tsx` filters the two known prefixes out of the plain warning list so nothing is said twice. Those prefixes are coupled to `GroundingReport.warning()` and `orchestrator._verify`.
- `connect()` deliberately performs **no synchronous setState** — it is called from a mount effect, and the `react-hooks/set-state-in-effect` lint rule is an error, not a warning.
- The session id lives in `localStorage` and is sent on every request, so a reload rejoins the same server-side session and dataset.
- Chat components: [chat/message.tsx](frontend/components/chat/message.tsx), [chat/reasoning-panel.tsx](frontend/components/chat/reasoning-panel.tsx), [chat/step-timeline.tsx](frontend/components/chat/step-timeline.tsx), [chat/artifacts-panel.tsx](frontend/components/chat/artifacts-panel.tsx) (slide-over), [chat/model-picker.tsx](frontend/components/chat/model-picker.tsx) (quick swap; `/models` is the full surface).
- The picker browses one provider at a time and always sends the provider alongside the model name — the list on screen may belong to a different backend than the role currently uses, and a bare name would be routed to the wrong daemon.

### Design system — [globals.css](frontend/app/globals.css)

Every colour, shadow, duration and easing curve is a token; components reference tokens, never raw values. Adding a `#hex` or a bare `duration-200` to a component is the thing to avoid.

- **Light only.** There is no `.dark` block and no `dark` variant. The aurora washes, the orb's glow and the shadow ramp are all tuned against a warm white ground. Do not reintroduce `dark:` classes — they will silently do nothing.
- The base background is painted on `html`, not `body`. `.aurora` is `position: fixed; z-index: -1`, and a background on `body` covers it completely.
- Surfaces: `.aurora` (ambient wash, in the root layout), `.grid-field` (hero only), `.glass` (anything floating over content), `.ring-gradient` (1px gradient border — plain `border` cannot express one), `.text-gradient`.
- Motion: `.reveal` / `.reveal-in` / `.reveal-scale` for entrances, `.stagger` with an inline `--i` for cascades, `.lift` for hover, `.caret` for the streaming cursor. Entrances are blur + a 6px rise, never a long slide.
- `prefers-reduced-motion` neutralises entrances to their **end state** rather than just shortening them, so nothing is left stranded mid-blur.
- Type is **Geist**, self-hosted from the `geist` npm package (the font files ship inside it). Deliberately not `next/font/google`, which downloads at build time and would make `npm run build` — a CI gate — fail whenever Google Fonts was unreachable.

### The orb and sound

- [animated-orb.tsx](frontend/components/animated-orb.tsx) is the brand mark, recovered from the pre-rewrite UI. Blur and drop shadow are computed from `size`; the original constants only looked right at hero scale. Orbits live in `globals.css`.
- [use-sound.ts](frontend/lib/use-sound.ts) pools one `Audio` element per sound — the old code allocated a new one per click. The mute preference is shared through `useSyncExternalStore` and persisted, hydrated in `subscribe` rather than an effect (again, `set-state-in-effect` is an error).
- Autoplay is expected to fail: browsers block the startup chime until the page has been interacted with, so it is re-armed to fire on the first real gesture.

## Testing

Four layers under `backend/tests/`: `unit/`, `integration/`, `regression/`, `negative/`.

Shared LLM stubs live in [tests/stubs.py](backend/tests/stubs.py) and the `stub_llm` fixture in `conftest.py`. `backend/tests` is on `sys.path` because `conftest.py` is there, so `from stubs import ScriptedLLM` works from any test module — do not cross-import between test files. Running out of scripted responses yields `"Done."` rather than raising, so a test fails on its own assertion instead of an IndexError that says nothing.

The loop changes the call *count*, not just the content: a `fast` run is plan → code → answer, an `auto` run adds a decision call per iteration plus a verification call. A test that scripts N responses and gets `"Done."` is usually missing the verification entry.

`regression/test_regressions.py` pins specific defects; each test's docstring states what broke and why. Read it before changing session handling, the database layer, the guard, the rate limiter, provider resolution or `sandbox.interrupt()`.

The autouse teardown clears state through `semantic_cache.clear()`, **not** `db_mgr.clear_cache()` — `add()` writes to SQLite *and* to the in-process exact-match cache, and clearing only the table leaves a live entry that sends a later test with the same question down the cache-hit path. That failure is order-dependent and invisible when the file is run alone.

`conftest.py` pins `OLLAMA_BASE_URL` and `LMSTUDIO_BASE_URL` to `http://127.0.0.1:1`. Model discovery is the one component that dials out on its own; port 1 is refused instantly instead of waiting on a connect timeout or resolving `host.docker.internal`, which is a real host on some dev machines.

## Conventions

Conventional commits are enforced by commitlint via pre-commit (`pre-commit install --hook-type commit-msg`). Ruff line-length is 120 with `E501` disabled — the formatter owns line length.
