# 🧙‍♂️ Wizard w1

> A local-first autonomous data analysis agent. Ask a real question about your data; it investigates — looking, computing, revising its approach when the data disagrees with it — then verifies the result and explains it, streaming its reasoning as it goes.

![Status](https://img.shields.io/badge/Status-Active-success) ![Version](https://img.shields.io/badge/Version-v3.1.0-orange) ![Docker](https://img.shields.io/badge/Docker-Ready-blue) ![CI](https://github.com/Aniket-a14/Wizard-w1/actions/workflows/ci.yml/badge.svg?branch=master) ![Security](https://github.com/Aniket-a14/Wizard-w1/actions/workflows/codeql.yml/badge.svg?branch=master)

## What it is

Wizard runs entirely on your machine. Your data never leaves it, and no API key is required.

You upload a file and ask a question in plain language. A **manager** model works out what to do; a **worker** model writes the Python; the code is statically screened and executed inside a Docker container scoped to your session.

The important part is what happens next. Rather than following a plan fixed before anything ran, the manager sees the **real output** and decides what to do next — examine a column, compute something else, consult an attached document, revise the plan outright, or stop and answer. It repeats until it has an answer or runs out of budget. Real analytical questions are not one step; you find out the join key is dirty, or that "active customer" means three different things in three tables, only once you have looked.

Every stage streams to the browser as it happens — the reasoning, each move and what it found, the generated code, the program's stdout, and the answer token by token.

## Why you might want it

- **Local first.** Two small Ollama models are enough to be useful. Nothing is sent anywhere.
- **You choose the models.** Nothing is hardcoded — the app uses whatever your provider actually has, and you can assign a different model, on a different backend, to each role.
- **It sizes itself to your hardware.** A 1.5B model gets a short leash and deterministic fallbacks; a large model gets a long investigation. Same app, one setting, and `auto` works it out from the model itself.
- **It runs the code, it doesn't just suggest it.** Results come from execution, not from a model claiming an answer.
- **It checks its own work.** The headline result is recomputed by a different route, and any figure in the answer that appears in no execution output is flagged rather than quietly presented.
- **It tells you what it assumed.** Dropped nulls, inner joins, top-N cuts — read back out of the code that actually ran, not out of the model's description of it.
- **It corrects itself.** Failures are fed back with the traceback, and successful repairs are remembered as negative examples for next time.
- **Docker is optional, not a fallback.** Without it, code runs in a subprocess per session — its own memory ceiling, a per-step timeout, a working Stop button, and variables that persist between steps. Same behaviour, no image to build.
- **It fits the machine it is on.** Thread count, sandbox memory and the session cap are measured from your CPU and RAM at boot rather than assumed.
- **It is honest about degradation.** No embedding model? Retrieval falls back to word overlap. Model unreachable? You get a clear message, not a hang. Nothing silently pretends.

## Quick start

**Prerequisites:** [Ollama](https://ollama.com/) (or LM Studio). [Docker Desktop](https://www.docker.com/products/docker-desktop/) is recommended but **not required** — see [Running without Docker](#running-without-docker).

```bash
git clone https://github.com/Aniket-a14/Wizard-w1.git
cd Wizard-w1
docker compose up --build -d
```

Open **http://localhost:3000**. API docs are at **http://localhost:8000/docs**.

**You do not need to install a model first.** Go to **/models** and use *Install a model* — starter picks are offered per provider, downloads show progress in the page, and nothing sends you to a terminal or the LM Studio window. Ollama models are installed through its own API; LM Studio models through the `lms` CLI that ships with it.

If you would rather use a terminal, any two models work — a reasoning model and a code model is the useful split, and nothing in the app is tied to a particular pair:

```bash
ollama pull qwen3:8b             # reasoning
ollama pull qwen2.5-coder:7b     # code
```

Optionally `ollama pull embeddinggemma` (or `nomic-embed-text`). Wizard embeds through whichever model server you already run, so this is all that semantic retrieval needs — no extra install, and no GPU libraries. Without one, matching falls back to word overlap.

### Disk space

The sandbox image ships in tiers. `standard` is the default; pick a smaller one if you are tight on space, and the agent is simply told about a smaller toolkit rather than writing code that then fails to import.

```bash
SANDBOX_TIER=core docker compose up --build -d   # pandas, numpy, pyarrow, duckdb, matplotlib, openpyxl
SANDBOX_TIER=full docker compose up --build -d   # adds survival analysis and geospatial
```

### Running without Docker

```bash
pip install -r requirements.txt -r requirements-local.txt
cd backend && uvicorn src.api.api:app --port 8000
cd frontend && npm ci && npm run dev
```

`EXECUTION_BACKEND` defaults to `auto`: it finds no Docker and runs generated code in a **subprocess** of the backend instead — a separate process with a memory ceiling, a per-step timeout, an interrupt that works, and a namespace that survives between steps. Set `EXECUTION_BACKEND=local` to choose it explicitly even where Docker is available.

It is not a security boundary: the subprocess runs as you, with your files. The static code guard still applies. Use Docker for data or questions you did not write yourself.

Any model you have pulled appears in the picker, and the app picks a sensible one per role on its own — no model name is configured anywhere by default.

**A note on model size.** The agent decides its own next step each iteration, which is a lot to ask of a very small model. Under 4B parameters it automatically runs a shorter loop with no self-revision and no verification pass; 7B and up is where the investigation behaviour starts to earn its cost. It still works below that — it just does less.

### Using LM Studio instead of (or alongside) Ollama

LM Studio works out of the box — no configuration needed if it is on its default port.

1. In LM Studio, open **Developer** and **Start Server**.
2. Turn on **Serve on Local Network**. LM Studio binds to loopback by default, so the backend container cannot reach it otherwise. (Skip this if you run the backend outside Docker.)
3. In the model picker, switch the provider to **LM Studio**.

The provider is stored **per role**, so you can leave the reasoning model on Ollama and put only the code model on LM Studio, or vice versa. Models are discovered through LM Studio's native API, which reports quantization, context length and whether a model is currently loaded — an unloaded model is marked, because LM Studio loads it on first use and that can take a while on a laptop.

Any other OpenAI-compatible server (vLLM, llama.cpp, a hosted gateway) works through `API_PROVIDER=custom_gateway` with `GATEWAY_API_URL`.

## How it works

```mermaid
graph TD
    classDef client fill:#0ea5e9,stroke:#0369a1,stroke-width:2px,color:#fff;
    classDef api fill:#10b981,stroke:#047857,stroke-width:2px,color:#fff;
    classDef brain fill:#db2777,stroke:#9d174d,stroke-width:2px,color:#fff;
    classDef sandbox fill:#f59e0b,stroke:#b45309,stroke-width:2px,color:#000;
    classDef store fill:#64748b,stroke:#334155,stroke-width:2px,color:#fff;

    UI["Next.js client<br/>(streams every move)"]:::client
    WS["FastAPI · WS /ws/chat"]:::api
    Session["Session<br/>tables · documents · sandbox"]:::api
    Loop["Analysis loop<br/>bounded by the tier budget"]:::api

    Manager["Manager model<br/>decide · revise · answer"]:::brain
    Worker["Worker model<br/>Python"]:::brain

    Guard["Code guard<br/>AST policy check"]:::sandbox
    Box["Per-session container<br/>cap_drop · mem/pid limits"]:::sandbox

    Trust["Trust layer<br/>verify · ground · assumptions"]:::store
    Store["SQLite<br/>cache · trajectories · memory"]:::store
    Retr["Retriever<br/>columns · memory · documents"]:::store

    UI <-->|typed event frames| WS
    WS --> Session --> Loop
    Loop <--> Retr <--> Store

    Loop -->|"1 what next?"| Manager
    Manager -->|"2 inspect / consult"| Retr
    Manager -->|"3 write code for this sub-task"| Worker
    Worker --> Guard -->|allowed| Box
    Box -->|"4 real output"| Loop
    Loop -.->|"repeat until answerable"| Manager
    Loop -->|5| Trust
    Trust -->|"6 synthesise from real output"| Manager
```

The dotted line is the part that matters. Step 4 feeds back into step 1: the manager sees what the code actually produced and picks the next move from it, so a plan that turns out to be wrong gets rewritten instead of carried out. How many times round that loop is allowed depends on the model — see `AGENT_TIER` below.

Underneath it, the retry loop still applies: when the sandbox raises, the traceback is added to the worker's prompt and the sub-task is retried, up to `MAX_CORRECTION_RETRIES`. A failure that is successfully repaired is stored so the same mistake is shown as a counter-example next time a similar question is asked. A sub-task that fails outright is not fatal — it is an observation, and the agent can route around it.

## Features

**Analysis**
- Chooses each next move from real execution output, and revises its plan when the data contradicts it
- Three depths: **Auto** (it decides), **Fast** (one pass), **Deep** (investigate thoroughly)
- Self-corrects on execution failure using the real traceback
- The full analytical stack, not just pandas: duckdb for SQL over dataframes, statsmodels and scipy for inference, scikit-learn/xgboost/lightgbm for modelling, lifelines for survival, networkx for graphs, geopandas for spatial — and the model is told what is *actually* installed, so a smaller image narrows the toolkit rather than producing code that fails
- Interactive Plotly charts (or static matplotlib, via `PLOT_FORMAT`)
- Optional plan approval before anything runs, and explicit consent before any web search

**Trust**
- The headline result is recomputed by a different route, and a disagreement is reported prominently
- Every figure in the answer is traced back to real output; anything that was not computed is flagged
- Silent decisions in the code — dropped nulls, inner joins, top-N cuts, coerced dates — are listed alongside the answer
- Each analysis is written out as a runnable script you can re-run next month against fresh data

**Data**
- CSV, TSV, Excel, JSON, NDJSON, Parquet and Feather
- **Reference documents** — data dictionaries, metric definitions, business rules as Markdown, text, PDF or .docx — which the agent consults mid-analysis when a question turns on what a column means
- Large files are sampled for analysis while the full file stays available in the workspace
- Column names are normalised for safe code generation **and de-duplicated**
- Every loaded table is available to generated code at once as `tables['name']`, so cross-table joins need no extra step

**Operational**
- Per-session isolation: separate dataset, execution namespace, workspace and history
- **Two execution backends**: a container per session, or a subprocess per session with no Docker at all
- Sizes itself to the host — inference threads from physical cores, runtime memory and the session cap from installed RAM
- Runs without Docker, without an embedding model, and without Redis
- Optional Redis for a shared cache and job state
- Optional `API_KEY` for deployments beyond localhost

## Configuration

Copy [backend/.env.example](backend/.env.example) to `backend/.env`. Everything has a working default; the values you are most likely to touch:

| Key | Default | Purpose |
|-----|---------|---------|
| `API_PROVIDER` | `ollama` | Default backend: `ollama`, `lmstudio`, `openai` or `custom_gateway` |
| `MODEL_NAME` | `""` | Pin the reasoning model. Empty = use what the provider has |
| `WORKER_MODEL_NAME` | `""` | Pin the code model. Empty = use what the provider has |
| `AGENT_TIER` | `auto` | `auto`, `compact`, `balanced` or `full` — how long an investigation may run |
| `AGENT_MAX_ITERATIONS` | `24` | Hard ceiling, whatever the tier says |
| `AGENT_REQUIRE_APPROVAL` | `False` | `True` to approve every plan before it runs |
| `AGENT_VERIFY` | `True` | Recompute the headline result a second way |
| `AGENT_GROUNDING_CHECK` | `True` | Flag figures that appear in no execution output |
| `CONTEXT_DOCS_ENABLED` | `True` | Accept reference documents alongside the data |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Where Ollama lives |
| `LMSTUDIO_BASE_URL` | `http://host.docker.internal:1234` | Where LM Studio lives (root, not `/v1`) |
| `PLOT_FORMAT` | `html` | `html` for interactive Plotly, `png` for static |
| `EXECUTION_BACKEND` | `auto` | `docker`, `local` (subprocess, no Docker) or `inprocess` |
| `SANDBOX_TIER` | `standard` | `core`, `standard` or `full` — how much toolkit the image installs |
| `SYSTEM_PROFILE` | `auto` | `auto` measures the machine; or pin `laptop`/`server`/`hpc` |
| `SANDBOX_ENABLED` | `True` | `False` disables containers entirely |
| `SANDBOX_NETWORK_DISABLED` | `False` | `True` is safer, but blocks on-demand package installs |
| `SANDBOX_DOCKER_RUNTIME` | `""` | Set `runsc` for gVisor kernel isolation |
| `CORS_ALLOW_ORIGINS` | `http://localhost:3000` | Comma-separated allowlist |
| `API_KEY` | `""` | When set, mutating routes require `X-API-Key` |
| `EMBEDDING_REMOTE_MODEL` | `""` | Pin the embedding model. Empty = discover one from the provider |
| `REDIS_URL` | `""` | Empty means in-process cache and queue |

Resource limits — `LLM_NUM_THREAD`, `SANDBOX_MEM_LIMIT`, `SESSION_MAX_ACTIVE`, `QUEUE_MAX_WORKERS` — are **left unset on purpose**. They are derived from the machine at boot, and setting one pins it.

## API

Interactive docs: `http://localhost:8000/docs`.

The session id is returned in the `X-Session-Id` header and should be sent back on subsequent requests.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/config` | Server capabilities |
| `POST` | `/api/session` | Create a session |
| `GET` | `/api/models` | Models installed on the host |
| `POST` | `/api/models` | Choose models for this session |
| `POST` | `/api/datasets` | Upload a file |
| `POST` | `/api/documents` | Attach a reference document |
| `DELETE` | `/api/documents/{name}` | Remove one |
| `GET` | `/api/data/preview` | Paginated table view |
| `POST` | `/api/chat` | Run a turn, buffered |
| `WS` | `/ws/chat` | Run a turn, streamed |
| `GET` | `/api/workspace/files` | Files this session produced |
| `GET` | `/api/report` | Summary of the session's analyses |

<details>
<summary>WebSocket frames</summary>

**Client → server**
```jsonc
{ "type": "message",  "content": "which day has the highest tips?", "mode": "planning" }
{ "type": "approval", "approved": true, "tool": "execute_plan", "content": "...", "plan": "..." }
{ "type": "cancel" }
{ "type": "ping" }
```

**Server → client**

`session` · `status` · `step_start` · `step_end` · `reasoning_delta` · `plan_delta` · `content_delta` · `code` · `stdout` · `artifact` · `approval_required` · `warning` · `error` · `final`

Reasoning and the final answer arrive as separate delta streams, so the client can render a live "thinking" panel independently of the answer.
</details>

## Security

Generated code is untrusted. Three layers apply:

1. **Static analysis** — an AST policy check rejects restricted imports, dynamic execution, interpreter-internals traversal, reflection with computed attribute names, and file access outside the workspace. Malformed code is treated as retryable rather than hostile, so the model gets to fix its own typo.
2. **Process isolation** — with `EXECUTION_BACKEND=docker`, one container per session with `cap_drop=ALL`, `no-new-privileges`, memory and PID limits, and a per-execution timeout; set `SANDBOX_DOCKER_RUNTIME=runsc` for gVisor. With `local`, a subprocess per session with an address-space cap (POSIX; Windows has no equivalent without pywin32) and the same timeout — which contains runaway code, but is **not** a security boundary. Use Docker for input you did not write yourself.
3. **Scoped filesystem** — each session reads and writes only its own workspace directory.

> [!IMPORTANT]
> The backend mounts the host Docker socket so it can create sandbox containers. That is host-root-equivalent access. Run Wizard on a trusted machine, and set `API_KEY` and a narrow `CORS_ALLOW_ORIGINS` before exposing it beyond localhost.

Report vulnerabilities privately — see [SECURITY.md](./SECURITY.md).

## Development

```bash
pip install -r requirements.txt       # API server
pip install -r requirements-local.txt # + the analysis toolkit, for running without Docker
cd frontend && npm ci && cd ..

pytest                                # 600+ tests; no Docker, model, network or subprocess
ruff check . --fix && ruff format .

cd frontend && npm run lint && npx tsc --noEmit && npm run build
```

Tests are organised as `unit/`, `integration/`, `regression/` and `negative/` under `backend/tests/`. The regression suite pins previously-fixed defects and each test explains what broke — worth reading before changing sessions, the database layer or the code guard.

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full workflow and [CLAUDE.md](./CLAUDE.md) for an architecture tour.

## Troubleshooting

**The backend cannot reach Ollama.** On Linux, `host.docker.internal` is not automatic; the compose file adds a `host-gateway` alias for it. If you still cannot connect, set `OLLAMA_BASE_URL=http://172.17.0.1:11434`.

**Settings shows "Local subprocess" instead of "Docker container".** Docker is unreachable, so code is running in a subprocess of the backend. That is a supported mode — bounded, interruptible, and it keeps variables between steps — but it is not isolated from your filesystem. Start Docker Desktop and reload to get a container back.

**Settings shows "In-process (no isolation)".** Neither backend was permitted. Set `EXECUTION_BACKEND=local` (or `auto`) in `backend/.env`. Only this mode has no isolation and no persistent namespace.

**Retrieval says "Word overlap".** No embedding model is installed on your provider. `ollama pull embeddinggemma` and reload. Nothing breaks without one; matching is just less good at paraphrases.

**The model picker is empty.** Nothing is installed yet, or the model server is not running. Open **/models** and use *Install a model* — there are starter picks per provider, and you do not need a terminal or the LM Studio window. `ollama pull qwen3:8b` still works if you prefer.

**The LM Studio tab is empty but LM Studio is running.** Almost always **Serve on Local Network** being off — with it off LM Studio accepts loopback connections only, and the backend runs in a container. The error under the tab names the exact URL that was tried. Note that `LMSTUDIO_BASE_URL` wants the root (`http://host.docker.internal:1234`), not the `/v1` endpoint the LM Studio UI displays; a trailing `/v1` is stripped for you.

**LM Studio answers the first question very slowly.** It loads the model on first request. The picker marks models that are not loaded; loading one in LM Studio beforehand avoids the stall.

**Analysis keeps failing on the same step.** The agent stops after `MAX_CORRECTION_RETRIES`. The generated code and the traceback are in the "Ran N steps" disclosure — that usually shows a column that does not exist or a type that needs converting first.

**A large upload is slow.** Files over `MAX_INMEMORY_ROWS` are sampled for analysis; the full file stays in the workspace and can be read directly in generated code.

## License

[BSD 3-Clause](./LICENSE).
