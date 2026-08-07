# Governance

Wizard is currently maintained by a single lead maintainer (see
[MAINTAINERS.md](MAINTAINERS.md)). This document describes how decisions get
made today, and the path to something less centralized as the project grows.

## Decision-making

- Day-to-day decisions — bug fixes, dependency updates, small features — are
  made by whoever's reviewing the PR, following [CONTRIBUTING.md](CONTRIBUTING.md).
- Architectural decisions (anything touching the orchestrator loop, the
  execution/sandboxing boundary, the permission model, or data-mode
  enforcement) are made by the lead maintainer. `docs/wizard-evolution-spec.md`
  and `CLAUDE.md` are the record of *why*, not just *what* — a design that
  contradicts them needs the reasoning updated too, not just the code.
- Disagreements are resolved by discussion on the issue or PR first. If that
  doesn't converge, the lead maintainer makes the call and states the
  reasoning in the thread, so it's on the record for next time.

## Becoming a maintainer

There's no fixed contribution count or tenure requirement. In practice,
someone becomes a candidate by consistently sending well-scoped, well-tested
PRs and by reviewing others' — the same signal any project uses. The lead
maintainer proposes new maintainers; existing maintainers (once there is more
than one) confirm by consensus. This will get formalized once the project
actually has more than one active maintainer — writing a multi-person process
for a one-person project would describe a reality that doesn't exist yet.

## Security issues

Security reports do not go through the normal issue/PR process — see
[SECURITY.md](SECURITY.md).

## Scope of this document

This covers project governance (who decides what). It is not a code of
conduct (see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)) and not a contribution
guide (see [CONTRIBUTING.md](CONTRIBUTING.md)).
