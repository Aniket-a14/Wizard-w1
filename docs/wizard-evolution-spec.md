# Wizard — Evolution Spec for Claude Code

**Purpose of this document:** This is a working spec/prompt for Claude Code to use while evolving the existing Wizard-w1 codebase (`github.com/Aniket-a14/Wizard-w1`) into the next generation of the product. This is an **evolution of the current codebase**, not a rewrite — every milestone should build on what already exists (the manager/worker agentic loop, the trust/grounding layer, the execution daemon protocol, the session model, the test discipline) rather than replace it wholesale. Read `CLAUDE.md` in the repo root first; it documents the current architecture in detail and most design decisions below explicitly extend something described there.

Work through the milestones **in order**. Each milestone should land as a coherent, independently testable change — do not start milestone N+1 until N's acceptance criteria are met. If a milestone's scope is ambiguous once you're inside the code, stop and ask rather than guessing; several open decisions are flagged explicitly below.

---

## Product identity

- **Name stays "Wizard."** Versioning is major-generation + sub-version: `w1` (current), `w2` (this evolution), with sub-versions like `w2.1`, `w2.2` for incremental releases within a generation. Treat this document as targeting **Wizard w2**.
- **Audience:** individuals and small teams doing real analytical work, not a toy demo — this is the near-term target and where acceptance is validated. The architecture (connector interface, permission model) is deliberately built so it isn't precluded from enterprise-scale data later, without spending this pass building enterprise-scale optimization itself (see guiding principle 6). Prompts to the agent are expected to be complex, multi-step use cases ("find and explain the cohorts driving churn and recommend which to prioritize"), not single-fact lookups.
- **Distribution model:** anyone can fork/clone the repo, run one setup step, and have a working local (or cloud-model-backed) agent. No hosted service, no telemetry, no tracking — consistent with the project's existing local-first ethos.

---

## Guiding principles (carry through every milestone)

1. **Extend, don't replace.** The orchestrator's loop (`orient → act → observe → revise → verify → answer`), the grounding/trust layer, the daemon protocol, and the session model are sound. New capability should plug into these, the way reference documents already plug into `consult`.
2. **Everything degrades, nothing hangs.** This is a hard existing rule (embeddings fall back to lexical, Redis is optional, a missing encoder never blocks a question) — every new subsystem (cloud providers, new connectors, skills, sandboxing) must fail into a clearly-communicated degraded mode, never a silent hang or a crash.
3. **Report, don't silently correct.** The trust layer's philosophy — flag what wasn't grounded, list what was assumed, never quietly edit model output — applies equally to the new permission system: surface what the agent wants to do; don't auto-launder it.
4. **Measure the machine, don't assume it.** `hostinfo.py`'s approach (derive thread count, memory ceilings, tier from the actual host at boot) is the template for how the new CLI daemon and sandboxing should behave across weak and strong machines alike.
5. **All platforms get equal priority.** Linux, macOS, and Windows are first-class throughout — no "documented but not enforced" shortcuts like the current `RLIMIT_AS`-on-POSIX-only gap, unless a milestone explicitly says otherwise.
6. **Design for enterprise scale, ship for individual scale.** The real near-term user is an individual or small team. Enterprise-scale data volume and connectivity is the reason the connector interface (Milestone 4) and permission model (Milestone 2) are built generally rather than narrowly — but heavy scale-specific optimization (distributed query planning, massive-cluster pushdown, etc.) is explicitly **not** required for this pass. Architect so it isn't precluded later; don't spend this pass's effort building it now.
7. **Every backend/CLI milestone ships its UI surface.** A milestone that changes what the agent can do (a new dial, a new connector type, a new consent category, a new skill source) is not done until there's a UI surface for it — a settings control, a picker, a review panel — even if minimal. This is called out explicitly per milestone below; treat it as a hard requirement, not a follow-up task.

---

## Milestone 1 — Provider-agnostic model layer, with an explicit local/cloud/hybrid data mode

**Goal:** Cloud providers (Anthropic, OpenAI, and others) become first-class alongside Ollama/LM Studio — not a fallback, not a special case. Critically, this milestone is also where the **data-privacy promise gets a real mechanism**, not just an assumption: the user explicitly chooses a data mode, and what the system is willing to send anywhere is governed by that choice.

- Extend `llm/` so `ModelPreferences` / `ModelSpec` / the provider resolution path treat a cloud API key exactly like a local endpoint: resolved per-role, cached per (provider, endpoint, model, temperature, max_tokens, num_ctx) exactly as today.
- `llm/resources.py`'s memory-footprint planning (`plan_resident_set`, keep-alive budgeting) is a **local-only concern** — cloud roles should skip it entirely rather than being forced through it, since "will this model fit in RAM" is meaningless for an API call.
- `model_registry` needs a cloud-provider enumeration path (list available models per API key) parallel to its existing Ollama `/api/tags` / LM Studio `/api/v0/models` paths.
- **Data mode is a top-level, session-wide setting: `local-only` / `cloud-only` / `hybrid`.** This is how the local-first promise is kept even once cloud models are equal-footing:
  - `local-only` — every role (manager, worker, embeddings) must resolve to a local provider. If a cloud provider is the only one configured, the system refuses to run rather than silently falling back to it — this is a hard boundary, not a soft preference.
  - `cloud-only` — every role resolves to a cloud provider.
  - `hybrid` — the user picks, per role, which provider handles it (e.g., manager reasoning on a cloud model, worker code generation or a specific tool call kept local). This is also where a policy decision belongs: what's actually allowed to reach a cloud call — full sample rows and statistics, or schema/column-names/types only with real values kept out of the prompt. Make this configurable per data source/connection under `hybrid`, and default to the more conservative option (schema-only to any cloud-bound call) rather than defaulting to convenience.
  - Tool/connector availability follows the same mode: a tool that itself calls out (e.g., a cloud object-storage connector, web search) should be presented as unavailable or gated under `local-only`, not just "the model chooses not to use it."
- **Cost visibility.** Since cloud calls have real per-token cost, surface a running usage/cost readout (tokens and estimated cost per session, and per subagent once Milestone 7 lands) in the UI and in `wizard doctor`. **Under `local-only`, this reads as zero, unambiguously** — no estimated cost, no meter, nothing implying spend where none exists.
- **Credentials are stored locally on the machine only** — no remote sync, no cloud-hosted secrets. Use a local config/credentials file under the user's Wizard config directory (equivalent of `~/.wizard/`), not environment-variable-only. Decide file permissions/encryption approach and document it; flag to the user if you consider OS keychain integration, since that's a genuine platform-divergent effort (Keychain/Credential Manager/Secret Service) — don't silently pick one without noting the tradeoff.
- **UI surface:** a data-mode picker (local-only / cloud-only / hybrid) visible at all times, not buried in settings — this is a trust-critical control. Under `hybrid`, a per-role/per-connection provider assignment and the schema-only-vs-full-data toggle described above. The running cost readout lives alongside it.
- **Acceptance:** switching data mode visibly changes what the system will and won't do (a `local-only` session refuses a configured-cloud-only tool rather than silently using it), the cost readout is honest and zero under `local-only`, and a fresh install can run entirely on a cloud provider with zero local models installed, or entirely on local models with zero network calls, with no code path assuming one or the other.

---

## Milestone 2 — Two independent dials: depth and permission profile

**Goal:** Separate "how much the agent investigates" from "how much it asks before acting" — like Claude Code's permission modes.

- **Depth** stays what it is today: `fast` / `auto` / `deep` (`AGENT_TIER` + mode), governing iteration budget, verification, decision round-trips.
- **Permission profile** is new and orthogonal: `auto-approve` / `ask-always` / `custom`. It governs whether the agent pauses for consent on specific *classes* of action:
  - installing a library into the sandbox
  - any outbound network/internet access (this already exists for web search via the `SEARCH: "…"` gate — generalize that mechanism rather than duplicating it)
  - connecting to an external database/warehouse (read access)
  - **writing back to an external database/warehouse** — its own category, distinct from read/connect, and **defaulting to off/ask regardless of profile** unless the user has explicitly enabled write-back for that connection (ties into Milestone 4's write-back note)
  - use of a specific tool/connector the user hasn't pre-authorized
  - writing outside the session workspace
- `custom` lets the user pick per-category (e.g., auto-approve library installs, but always ask before any network call, and never auto-approve write-back).
- This must compose cleanly with the existing plan-approval gate (`AGENT_REQUIRE_APPROVAL`) — that gate is about the *plan*; this is about *actions within an approved plan*. Keep them conceptually and code-wise distinct.
- **UI surface:** a permission-profile selector alongside the depth control in the composer, plus a `custom` view listing each category with its own toggle — including the write-back category, shown clearly as a distinct, higher-friction control rather than folded into general database access.
- **Acceptance:** the same analysis, run once with `deep` + `auto-approve` and once with `fast` + `ask-always`, produces the same *quality* of answer when nothing risky comes up, but visibly different consent-prompt behavior when it does — and no profile, including `auto-approve`, ever silently writes to an external data source without a first-time explicit opt-in for that connection.

---

## Milestone 3 — Host-primary execution, Docker optional, OS-native sandboxing

**Goal:** Docker moves from default to opt-in. Host-process execution (today's `local` backend) becomes the primary path, with real per-OS sandboxing replacing the container as the safety net — plus the existing AST code guard, which stays regardless.

- This is the highest-risk milestone in this spec. Treat it as its own sub-phase with its own review before moving on.
- Per-platform sandboxing, all three treated as first-class:
  - **Linux:** seccomp-bpf and/or Landlock to restrict syscalls and filesystem access for the analysis subprocess.
  - **macOS:** `sandbox-exec` (or its modern replacement if `sandbox-exec` is deprecated on the target macOS versions — verify current state, don't assume) profiles restricting filesystem/network.
  - **Windows:** restricted tokens / job objects / AppContainer, replacing the currently-unenforced `RLIMIT_AS` gap called out in the existing codebase.
- The AST code guard (`code_guard.py`) stays exactly as-is as defense-in-depth — it does not get weaker because Docker is gone; if anything, it's now doing more of the work.
- `EXECUTION_BACKEND` gains real tri-state meaning: `docker` (opt-in, existing container path unchanged), `host` (new default — subprocess + OS-native sandbox), `inprocess` (unchanged, dev/test only).
- The permission profile from Milestone 2 is the *policy* layer on top of this — sandboxing is what happens regardless of consent; the permission dial decides whether the agent asks before hitting a boundary the sandbox would otherwise just enforce silently.
- **Acceptance:** with Docker not installed at all, a fresh clone still runs analyses with real, verifiable OS-level containment (not just documentation claiming it) on Linux, macOS, and Windows.

---

## Milestone 4 — Expanded data connectivity (cloud + local databases)

**Goal:** Beyond file upload, users can connect directly to real data sources — any database or data store, local, cloud, or hybrid, not a fixed list.

- **No hardcoded connector whitelist.** The design should not assume "these N databases and no others." Build a general connector interface — schema discovery, sampled read, full read, (optionally) write-back — and implement it against the broadest-reach standard abstractions available (e.g. SQLAlchemy-style dialects for anything relational, a generic driver path for document/NoSQL stores, a generic object-storage path for anything S3-compatible or equivalent), so that support for a given database is a matter of *which dialect/driver is installed*, not a rearchitecture of the connector layer itself.
- Treat "local," "cloud," and "hybrid" as properties of a connection (where it lives, how it's reached — local socket, VPN, public endpoint), not different code paths. A connection is a connection string/credential set plus a driver; the agent doesn't need to know or care whether the thing on the other end is on the user's laptop or in someone's cloud account.
- Ship a **reference implementation** covering a small representative spread (one relational engine, one document store, one object-storage-compatible target) purely to prove the interface out end-to-end — but the interface, not that specific list, is the deliverable. Additional databases should be addable by a contributor without touching core orchestration code, ideally via the same pluggable pattern as Milestone 5/6's skills (ties connector extensibility to the same "anyone can fork and extend" philosophy as the rest of the system).
- Connectors are ingest sources parallel to the existing file-upload path — they should register `DatasetHandle`s / table entries into the session the same way an uploaded CSV does, so the rest of the pipeline (table_key sanitization, per-table `.feather` materialization, `tables['name']` availability to generated code) needs no special-casing downstream.
- Credentials for a connection (host, port, connection string, access keys) go through the same local-only credential storage from Milestone 1 — never persisted to the shared skill registry, never sent anywhere but the target data source itself.
- Connecting to a new data source is itself a permission-gated action under Milestone 2's model (a "connect to external database" consent category), regardless of which driver is in play.
- **Write-back is read-only by default.** Every connection starts read-only; enabling write-back for a specific connection is an explicit, separate opt-in the user makes once per connection, gated by Milestone 2's dedicated write-back permission category — never implied by "connect" or by an `auto-approve` profile.
- **Scale scope for this pass:** per guiding principle 6, build the connector *interface* generally (so nothing about it blocks enterprise-scale use later — e.g., don't assume a table fits in memory, prefer query-capable reads where the driver supports it), but do not spend this milestone building distributed/cluster-scale optimization. Individual- and small-team-scale usage is what gets validated now.
- **UI surface:** a connections panel (add/edit/remove a data source, choose driver/dialect, test connection, toggle write-back per connection) reachable from the same place as file upload, since both are just ingest sources to the session.
- **Acceptance:** a user can point the agent at *any* database they have a driver for — local, cloud, or hybrid, from the reference set or a community-added one — ask a complex analytical question spanning it plus an uploaded file, and get one coherent analysis across both, with no database type getting special-cased treatment in the core pipeline, and with every connection read-only until the user explicitly says otherwise.

---

## Milestone 5 — Skills system (SKILL.md-style, agent-promotable)

**Goal:** Reusable, inspectable units of know-how — not just private trajectory memory.

- Reuse the `SKILL.md` frontmatter + instructions convention already established in this ecosystem (same shape Claude Code itself uses) — don't invent a new format.
- Skills live in layered locations: built-in (shipped with Wizard), user-global (`~/.wizard/skills/`), project-local. Consulted by the manager mid-analysis the same way reference documents already are (`ingest/documents.py` / `consult` pattern) — same retrieval path, same "degrades to lexical matching with no embedding model" behavior.
- **Promotion pipeline:** the existing `trajectories` table (failure→fix pairs) already captures repeated successful patterns. Add a path where a trajectory that succeeds repeatedly (define a concrete threshold) gets surfaced to the user as a candidate for promotion into a named, human-readable skill — not auto-published silently.
- A completed analysis can also be explicitly promoted into a skill by the user from the results UI (ties into Milestone 9).
- **UI surface:** a skills browser (list installed skills by layer — built-in/user-global/project — view/edit contents, see which analyses used which skill) and an inline "promote this trajectory to a skill?" prompt when the promotion threshold is hit.
- **Acceptance:** the agent can name which skill informed a decision, a user can open and edit that skill's file directly, and a new install's agent gets measurably better at a repeated task type as skills accumulate.

---

## Milestone 6 — GitHub-based public skill registry

**Goal:** Skills are shareable the way ClawHub skills are — pulled from repos/gists, not hosted by Wizard itself.

- No Wizard-run hosting service. The registry mechanism is: point the agent (or the CLI) at a GitHub repo or gist URL; it fetches, validates format, and installs into the user-global skills directory.
- **Security is not optional here.** A pulled skill is untrusted instruction text at minimum, and potentially untrusted code if a skill bundles helper scripts. Before a pulled skill can run against real user data:
  - Validate it parses as well-formed `SKILL.md` (frontmatter + instructions only, no unexpected executable payloads, unless explicitly designed to carry them — decide and document this boundary explicitly).
  - Surface the skill's full contents to the user for review before first use — never silent-install-and-run.
  - Anything a skill causes the agent to do still passes through the Milestone 2 permission profile and the Milestone 3 sandbox exactly like agent-generated code does. A skill is a suggestion to the manager, not a bypass.
- **Pin, don't track.** A skill installed from a GitHub repo/gist is pinned to the specific commit SHA (or release tag, resolved to a SHA) at install time — never a live branch reference. The skill cannot change under the user silently; an update is a deliberate `wizard skills update` that shows a diff before re-installing.
- A simple local index of "installed skills + their source URL + pinned commit + when last updated" is enough for v1 — no need for search/discovery infrastructure yet unless it falls out naturally.
- **UI surface:** an "add from GitHub URL" flow that shows the full skill contents and the resolved commit before confirming install, and a registry view distinguishing built-in / user-installed / pending-review skills.
- **Acceptance:** a user can `wizard skills add <github-url>`, review what it contains and which exact commit it's pinned to, and have it available to the agent — with the same sandboxing and consent gates as everything else, and with no skill ever changing behavior without an explicit update step.

---

## Milestone 7 — Subagents for parallel sub-tasks

**Goal:** Within one analysis, independent sub-tasks can fan out to isolated parallel workers rather than running strictly serially through the single manager/worker loop.

- Each subagent gets its own execution namespace/workspace slice (consistent with the existing per-session isolation model — a subagent is a scoped child of the session, not a new top-level session).
- The parent orchestrator decides when a step is parallelizable (independent sub-questions, independent table investigations) — this is a manager-level decision, following the existing "action" vocabulary in `actions.py` rather than a separate hardcoded rule.
- Results from subagents feed back into the same grounding/verification layer as any other execution output — a subagent's number is just as subject to `check_grounding` and re-derivation as the main loop's.
- Respect the permission profile and sandbox per subagent independently — a subagent doesn't inherit blanket trust just because its parent was already approved for something unrelated.
- **UI surface:** the investigation trail (Milestone 9) shows subagents as distinguishable parallel branches, not interleaved as if from one thread — including each subagent's own cost contribution once Milestone 1's cost readout is in place.
- **Acceptance:** a multi-part question (e.g., "compare these three regions and then reconcile the differences") visibly runs parts in parallel in the investigation trail, with each subagent's steps distinguishable from the main thread's.

---

## Milestone 8 — CLI as a single static binary, background daemon

**Goal:** One binary (Rust or Go — your call, but pick one and commit, don't ship both), same tool on Linux/macOS/Windows with equal priority, that manages the backend + frontend as a background service.

- Core subcommands: `wizard init` (environment check, `.env` setup, optional model pulls), `wizard start` (launches backend+frontend as background processes, opens the browser once healthy), `wizard stop`, `wizard status`/`doctor` (surfaces host sizing, provider reachability, sandbox capability — reusing `hostinfo.py`/`model_registry` data rather than reimplementing it), `wizard attach` (reconnect to a running daemon's logs/status).
- The binary owns process lifecycle (PID tracking, health polling against `/api/config`) but does **not** own container lifecycle beyond what's needed to optionally start Docker-backed execution when a user opts into Milestone 3's `docker` mode.
- Credential and config storage from Milestone 1 lives under one consistent config directory this binary manages, consistent across all three OSes (respect each platform's conventional location — don't hardcode a Linux-style path on Windows).
- No remote/tailscale-style access — this is confirmed out of scope. The daemon binds to localhost only.
- **Daemon operations, not just launch:**
  - `wizard update` — updates the binary and/or the backend/frontend checkout, with a clear message if the two drift out of a compatible version pair (the binary should check a compatibility marker against the backend it's managing rather than assuming they always match).
  - Log rotation for the background processes — logs go somewhere findable (`wizard logs` / a path `doctor` reports), and don't grow unbounded across a long-running daemon.
  - Crash recovery — if the backend or frontend process dies unexpectedly, the daemon detects it (health poll failure) and either restarts it with backoff or surfaces a clear "stopped unexpectedly, see logs" state rather than silently appearing "running" while dead.
  - Version compatibility check on `wizard start` — refuse to run (with a clear message) rather than starting a binary against an incompatible backend checkout.
- **Acceptance:** `git clone`, one `wizard init`, one `wizard start`, on a machine with nothing else installed, on all three OSes, with equivalent behavior and no OS treated as an afterthought — and a killed backend process is detected and recovered or clearly reported, not silently invisible.

---

## Milestone 9 — Results: review, export, promote

**Goal:** A finished analysis gives the user three things, not one.

- **UI review** — unchanged from today's investigation trail / answer / trust surfaces, extended to show subagent activity (Milestone 7) and any skill consulted (Milestone 5).
- **Re-runnable export** — extend the existing "runnable script you can re-run next month" feature into a clean exportable script/notebook capturing the actual executed steps (not a reconstruction from the model's description of them — pull from real execution output, consistent with the grounding philosophy). **Never embed a credential or connection secret in the exported file** — any database/cloud connection referenced in the script is looked up by name from local config at run time, so the exported artifact is safe to share even if the analysis touched a live data source.
- **Promote to skill** — an explicit user action that takes a completed analysis and, with review, turns it into a named skill (Milestone 5's manual promotion path) or contributes it toward the registry (Milestone 6), never automatically.
- **Acceptance:** after any analysis, a user can view it, download something they could run standalone next month, and optionally save it as a skill — without three separate disconnected features.

---

## Milestone 10 — Versioning, docs, release polish

**Goal:** Ship this as Wizard w2.

- Update `CLAUDE.md` (or its successor doc) to describe the new architecture with the same density and precision as the current one — every non-obvious decision explained, not just described.
- Decide and document the `w1` → `w2` migration story for anyone with an existing local install (config format changes from Milestone 1/8, execution backend default change from Milestone 3).
- Confirm the full test suite discipline still holds: no test touches Docker, a real model provider, or the real network, regardless of how many new subsystems (cloud providers, connectors, sandboxing, registry) were added. Extend `conftest.py`'s environment-pinning pattern to every new subsystem rather than letting new code find its own defaults under test.

---

## Open items intentionally left for you to flag, not guess

- Whether OS keychain integration (vs. a local encrypted file) is worth the platform-specific effort in Milestone 1/8 — flag the tradeoff rather than silently choosing.
- Exact trajectory-promotion threshold in Milestone 5.
- Whether pulled skills (Milestone 6) may ever bundle executable helper code, or must be instruction-only — this is a real security boundary, decide it explicitly and early since it shapes the registry's trust model.
- Rust vs. Go for Milestone 8 — pick one, but the choice should be explained (ecosystem for cross-platform sandboxing bindings, static-binary story, etc.), not assumed.
