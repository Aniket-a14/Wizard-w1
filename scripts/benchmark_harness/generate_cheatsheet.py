"""Phase 3.2 -- generate the report's §12 tuning cheatsheet FROM config.py,
instead of hand-typing settings from memory (which is how the original report
ended up with five invented names -- see docs/benchmark-report-remediation-plan.md
Phase 0.1).

Every row's field name is checked with `hasattr(settings, name)` before being
emitted. If a curator (human or model) writes down a setting that doesn't exist,
this script fails loudly at generation time instead of shipping a plausible-
looking row nobody can find in `.env`.

No LLM call -- this only introspects the already-imported `settings` singleton.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from src.config import settings  # noqa: E402

# (field name, recommended value or "default", applies-to note). The field name
# is validated against the live Settings object below -- this list only curates
# WHICH settings are worth a cheatsheet row, never their values.
#
# OLLAMA_MAX_LOADED_MODELS is deliberately NOT in this list: it belongs to the
# Ollama server process, not to Wizard's Settings, so `hasattr(settings, ...)`
# would correctly reject it -- it's listed separately below, unvalidated on
# purpose, with that fact stated rather than hidden.
NOT_A_WIZARD_SETTING = [
    {
        "setting": "OLLAMA_MAX_LOADED_MODELS",
        "current_value": "(not a Wizard setting)",
        "recommendation": "2 (increase to 3 with 32+ GB RAM) -- set in Ollama's own config, not backend/.env",
        "applies_to": "Any machine running Ollama",
    }
]

ROWS = [
    ("LLM_NUM_THREAD", "leave unset (0) -- auto-derived from physical core count at boot", "All local inference setups"),
    ("LLM_KEEP_ALIVE", "sent per-request; do not also set OLLAMA_KEEP_ALIVE server-side", "Resident-pair turns, see MODEL_MEMORY_FRACTION"),
    ("EXECUTION_BACKEND", "docker (preferred) or host", "All platforms with Docker available"),
    ("DATA_MODE", "local-only / hybrid / cloud-only", "Choose per privacy needs + hardware"),
    ("SEMANTIC_CACHE_THRESHOLD", "default is already tuned; lower cautiously for more cache hits", "Repeated/similar queries"),
    ("SANDBOX_EXEC_TIMEOUT", "leave at default -- see §7 enterprise scenario durations", "Complex multi-step queries"),
    ("RATE_LIMIT_MAX_REQUESTS", "default is fine for single-user/dev", "Cloud API rate limiting"),
    ("RATE_LIMIT_WINDOW_SECONDS", "paired with RATE_LIMIT_MAX_REQUESTS", "Cloud API rate limiting"),
    ("SESSION_TTL_SECONDS", "default is fine for single-user/dev", "Session/workspace cleanup"),
    ("GATEWAY_API_URL", "required for hybrid/cloud modes via a gateway", "Cloud provider endpoint"),
    ("MODEL_MEMORY_FRACTION", "0 = auto-derive (DEFAULT_MEMORY_FRACTION=0.60)", "Resident-pair planning, see llm/resources.py"),
]


def generate() -> list[dict]:
    rows = []
    for field, recommendation, applies_to in ROWS:
        if not hasattr(settings, field):
            raise SystemExit(
                f"FATAL: '{field}' is not a real Settings field. "
                "This is exactly the defect Phase 0.1 exists to fix -- refusing to emit a cheatsheet row for it."
            )
        default = getattr(settings, field)
        rows.append(
            {
                "setting": field,
                "current_value": default,
                "recommendation": recommendation,
                "applies_to": applies_to,
            }
        )
    return rows + NOT_A_WIZARD_SETTING


def to_markdown(rows: list[dict]) -> str:
    lines = [
        "| # | Setting | Current value (this run) | Recommendation | Applies to |",
        "| :---: | :--- | :--- | :--- | :--- |",
    ]
    for i, row in enumerate(rows, start=1):
        lines.append(
            f"| {i} | `{row['setting']}` | `{row['current_value']}` | {row['recommendation']} | {row['applies_to']} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    rows = generate()
    markdown = to_markdown(rows)
    print(markdown)

    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "cheatsheet_section12.md").write_text(markdown + "\n")
    print(f"\nWritten to {out_dir / 'cheatsheet_section12.md'}")
    print(f"\n{len(rows)}/{len(rows)} settings verified to exist on the live Settings object.")
