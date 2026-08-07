# Migrating from Wizard w1 to w2

Wizard w2 is the evolution described in [`wizard-evolution-spec.md`](wizard-evolution-spec.md):
cloud model providers alongside local ones under an explicit data mode, a
permission profile independent of investigation depth, host-primary execution
with OS-native sandboxing (Docker becomes opt-in), real database/warehouse
connectors, a skills system, parallel subagents, and a CLI daemon. This note
is the short version for anyone with a working w1 install: what actually
changes for you, and what doesn't.

## The short version: most installs need to do nothing

Every setting introduced across Milestones 1–9 — `DATA_MODE`,
`AGENT_PERMISSION_PROFILE`, `HOST_SANDBOX`, `HOST_SANDBOX_NETWORK`,
`SUBAGENT_*`, `SKILLS_*`, the connector settings, and the rest — is additive
with a safe default. An existing `backend/.env` keeps validating exactly as
it did under w1; you don't need to add anything to keep running the way you
already were.

Two concrete backward-compat mechanisms in `backend/src/config.py` make this
true rather than just asserted:

- `EXECUTION_BACKEND`'s pre-w2 spellings, `auto` and `local`, are folded to
  `host` by a `mode="before"` field validator (`_fold_execution_backend`)
  before the rest of the codebase ever sees the value — so a `.env` that
  still says `EXECUTION_BACKEND=local` keeps working, and now gets the new
  OS-sandboxed subprocess instead of the old unsandboxed one, for free.
- `LOCAL_RUNTIME_START_TIMEOUT` / `LOCAL_RUNTIME_MEM_LIMIT` /
  `LOCAL_RUNTIME_ALLOW_PIP` are still accepted as aliases for their renamed
  `HOST_RUNTIME_*` equivalents via `AliasChoices`. No field was silently
  dropped.

The SQLite database (`backend/data/wizard.db`) also migrates itself: every
schema change since w1 is an additive column in `database.py`'s `MIGRATIONS`
tuple, applied automatically on boot. There is no export/import step and
nothing to run by hand.

## The one real behavior change: the execution backend default

**A bare install now runs generated code in a sandboxed host subprocess by
default, not a Docker container.** This is Milestone 3: Docker moved from
default to opt-in, replaced by real per-OS sandboxing (Landlock/seccomp on
Linux, `sandbox-exec` on macOS, a restricted job object plus a Low integrity
level on Windows) as the safety net, with the AST code guard unchanged
underneath both.

This only affects how you *start* the backend without Docker Compose —
`uvicorn src.api.api:app` by hand, or `wizard start` once you're on the
Milestone 8 CLI:

- **`docker compose up` is unaffected.** `docker-compose.yml` still sets
  `EXECUTION_BACKEND=${EXECUTION_BACKEND:-docker}` explicitly, so a Compose
  install keeps getting one container per session exactly as it did under w1.
- **A non-Compose install now defaults to `host`** (see above) instead of
  whatever `auto`/`local` resolved to under w1. If you specifically want
  container-per-session without Compose, set `EXECUTION_BACKEND=docker` in
  `backend/.env`.

Either way, `GET /api/sandbox/selftest` spawns a real probe and reports what
this specific machine can actually enforce — worth running once after
upgrading, since containment now depends on what your OS supports rather than
only on whether Docker is installed.

## New files appear on disk

Milestone 1 introduced a local, unencrypted config directory (OS access
control is the guarantee, the same one `~/.aws/credentials` relies on — see
`CLAUDE.md`'s Credentials section for the reasoning, including why OS
keychain integration was considered and not taken):

| Platform | Location |
|---|---|
| Windows | `%APPDATA%\Wizard` |
| macOS | `~/Library/Application Support/Wizard` |
| Linux | `$XDG_CONFIG_HOME/wizard` (or `~/.config/wizard`) |

Inside it: `credentials.json` (cloud provider API keys, if you configure
any), `connections.json` (saved database/warehouse connections — Milestone
4), and `skills/` (your user-global skills — Milestone 5/6). None of this
existed under w1; there is no old location to migrate from, and nothing here
is required unless you use the features that populate it.

`WIZARD_CONFIG_DIR` overrides the location if you need it somewhere else.

## Optional: adopting the new defaults deliberately

Nothing below is required to keep working — it's for anyone who wants to
actually use what changed:

- **Pick a data mode.** The shipped default is `local-only`, which matches
  what w1 always did (nothing left the machine). Switch to `hybrid` or
  `cloud-only` only if you've configured a cloud provider and want to use it.
- **Review the permission profile.** The shipped default is `ask-always` —
  strictly *more* consultative than w1, which had no consent model at all for
  library installs, network access, or database writes. If that's too
  chatty for your workflow, `auto-approve` or a `custom` per-category profile
  are both available in `/settings`.
- **Run the sandbox self-test once** (`GET /api/sandbox/selftest`, or the
  equivalent panel in `/settings`) to see what this specific machine enforces
  — it varies by OS and kernel version, and the report names the gaps rather
  than hiding them.

## See also

- [`CLAUDE.md`](../CLAUDE.md) — full architecture reference, updated through
  Milestone 10.
- [`wizard-evolution-spec.md`](wizard-evolution-spec.md) — the milestone-by-
  milestone plan this upgrade implements.
