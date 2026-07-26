# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Wizard w1** — a local-first autonomous data analysis agent. A FastAPI backend orchestrates two local Ollama models (a "manager" that reasons and a "worker" that writes code), executes the generated Python inside a per-session Docker sandbox, and streams reasoning, code, stdout and the final answer to a Next.js client over one WebSocket.

Monorepo: `backend/` (Python 3.11, FastAPI) + `frontend/` (Next.js 16 / React 19 / Tailwind v4).

## Commands

### Full stack
```bash
ollama pull deepseek-r1:1.5b && ollama pull qwen2.5-coder:1.5b   # on the host
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

`reasoning_delta` vs `plan_delta` are split *during* streaming by tracking the `<thought>` tag boundary incrementally ([`_stream_plan`](backend/src/core/agent/orchestrator.py)), so the UI can show a live thinking panel that switches to the plan at the right moment.

### Workflow — [orchestrator.py](backend/src/core/agent/orchestrator.py)

```
cache lookup → plan → [approval gate] → generate → execute
                                            ↑          ↓
                                            └ correct ─┘   (bounded by MAX_CORRECTION_RETRIES)
                                                       ↓
                                                  review → answer
```

- Cache hit or a keyword-simple request skips planning entirely.
- `mode="planning"` halts at `awaiting_approval`; `mode="fast"` runs straight through.
- A plan containing `SEARCH: "…"` halts for consent before any web search.
- A plan with ≥2 numbered steps executes step-by-step with prior outputs fed forward.
- **The final answer is synthesised by the manager from real execution output** (`create_answer_prompt`). Do not reintroduce client-side cleanup of the response — the frontend used to regex-strip tracebacks, code blocks and numeric rows out of it, which deleted legitimate results.

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
- The daemon records its own PID; `interrupt()` signals it directly. Signalling PID 1 would kill the container, since PID 1 is `sleep infinity`.
- Limits: `mem_limit`, `pids_limit`, optional `cpu_quota`, `cap_drop=ALL`, `no-new-privileges`, plus a socket deadline per execution.

### Sessions — [session.py](backend/src/core/session.py)

Every browser gets a `Session`: its own datasets, catalog, chat history, workspace directory and container. Resolved from the `X-Session-Id` header (or `?session=`), TTL-reaped, and capacity-bounded. There is no global dataset state.

### Context budgeting — [retriever.py](backend/src/core/rag/retriever.py) + [prompts.py](backend/src/core/prompts.py)

`generate_system_context` does not dump the whole frame. Columns are selected by relevance to the question (columns named in the question are always kept), and memories, trajectories and few-shot examples are retrieved semantically. Everything degrades to lexical scoring when no embedding model is loaded.

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

## Frontend

- [use-chat-stream.ts](frontend/lib/use-chat-stream.ts) owns one persistent WebSocket with heartbeat and exponential-backoff reconnect, and appends each `*_delta` frame to the live message. This is genuine token streaming; do not reintroduce the timer-based word reveal.
- `connect()` deliberately performs **no synchronous setState** — it is called from a mount effect, and the `react-hooks/set-state-in-effect` lint rule is an error, not a warning.
- The session id lives in `localStorage` and is sent on every request, so a reload rejoins the same server-side session and dataset.
- Components: [chat-shell.tsx](frontend/components/chat-shell.tsx) (layout), [chat/message.tsx](frontend/components/chat/message.tsx), [chat/reasoning-panel.tsx](frontend/components/chat/reasoning-panel.tsx), [chat/step-timeline.tsx](frontend/components/chat/step-timeline.tsx), [chat/artifacts-panel.tsx](frontend/components/chat/artifacts-panel.tsx) (slide-over), [chat/model-picker.tsx](frontend/components/chat/model-picker.tsx).
- The picker browses one provider at a time and always sends the provider alongside the model name — the list on screen may belong to a different backend than the role currently uses, and a bare name would be routed to the wrong daemon.

### Design system — [globals.css](frontend/app/globals.css)

Every colour, shadow, duration and easing curve is a token; components reference tokens, never raw values. Adding a `#hex` or a bare `duration-200` to a component is the thing to avoid.

- **Light only.** There is no `.dark` block and no `dark` variant. The aurora washes, the orb's glow and the shadow ramp are all tuned against a warm white ground. Do not reintroduce `dark:` classes — they will silently do nothing.
- The base background is painted on `html`, not `body`. `.aurora` is `position: fixed; z-index: -1`, and a background on `body` covers it completely.
- Surfaces: `.aurora` (ambient wash, in the root layout), `.grid-field` (hero only), `.glass` (anything floating over content), `.ring-gradient` (1px gradient border — plain `border` cannot express one), `.text-gradient`.
- Motion: `.reveal` / `.reveal-in` / `.reveal-scale` for entrances, `.stagger` with an inline `--i` for cascades, `.lift` for hover, `.caret` for the streaming cursor. Entrances are blur + a 6px rise, never a long slide.
- `prefers-reduced-motion` neutralises entrances to their **end state** rather than just shortening them, so nothing is left stranded mid-blur.
- Type: system stack by choice. `next/font/google` downloads at build time, which would make `npm run build` — a CI gate — depend on network reachability.

### The orb and sound

- [animated-orb.tsx](frontend/components/animated-orb.tsx) is the brand mark, recovered from the pre-rewrite UI. Blur and drop shadow are computed from `size`; the original constants only looked right at hero scale. Orbits live in `globals.css`.
- [use-sound.ts](frontend/lib/use-sound.ts) pools one `Audio` element per sound — the old code allocated a new one per click. The mute preference is shared through `useSyncExternalStore` and persisted, hydrated in `subscribe` rather than an effect (again, `set-state-in-effect` is an error).
- Autoplay is expected to fail: browsers block the startup chime until the page has been interacted with, so it is re-armed to fire on the first real gesture.

## Testing

Four layers under `backend/tests/`: `unit/`, `integration/`, `regression/`, `negative/`.

`regression/test_regressions.py` pins specific defects; each test's docstring states what broke and why. Read it before changing session handling, the database layer, the guard, the rate limiter, provider resolution or `sandbox.interrupt()`.

The autouse teardown clears state through `semantic_cache.clear()`, **not** `db_mgr.clear_cache()` — `add()` writes to SQLite *and* to the in-process exact-match cache, and clearing only the table leaves a live entry that sends a later test with the same question down the cache-hit path. That failure is order-dependent and invisible when the file is run alone.

`conftest.py` pins `OLLAMA_BASE_URL` and `LMSTUDIO_BASE_URL` to `http://127.0.0.1:1`. Model discovery is the one component that dials out on its own; port 1 is refused instantly instead of waiting on a connect timeout or resolving `host.docker.internal`, which is a real host on some dev machines.

## Conventions

Conventional commits are enforced by commitlint via pre-commit (`pre-commit install --hook-type commit-msg`). Ruff line-length is 120 with `E501` disabled — the formatter owns line length.
