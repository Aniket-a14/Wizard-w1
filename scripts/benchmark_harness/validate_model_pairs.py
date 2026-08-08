"""Phase 3.1 -- validate the report's §11.2 recommended model pairs against the
real memory planner (`estimate_footprint` / `plan_resident_set`'s own arithmetic),
instead of asserting they fit.

Per docs/benchmark-report-remediation-plan.md 3.1: two 7B models want ~14GB
against `MODEL_MEMORY_FRACTION` of system RAM -- the report may be recommending
pairs that land in swap on the very machines it recommends them for. This script
doesn't call `plan_resident_set` directly, because that function reads THIS
machine's real RAM (`host_info().ram_bytes`) rather than taking a hypothetical
figure -- so it reimplements exactly its budget/required comparison
(`budget = ram_bytes * fraction`, `required = sum(footprint.total_bytes)`) against
each hardware tier's *stated* RAM, using the codebase's own `estimate_footprint`
for the footprint math so the two never diverge.

No LLM call, no host RAM dependency -- pure arithmetic, safe to run directly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from src.core.llm.resources import DEFAULT_MEMORY_FRACTION, estimate_footprint  # noqa: E402


GB = 1024**3

# From the report's §11.2 table, verbatim.
PAIRS = [
    {
        "tier": "Entry-Level (4-8 GB RAM, no GPU)",
        "ram_gb": 6,  # midpoint of stated 4-8 GB range
        "num_ctx": 8192,
        "manager": ("qwen2.5:1.5b", "1.5B"),
        "worker": ("qwen2.5-coder:0.5b", "0.5B"),
    },
    {
        "tier": "Mid-Range (8-16 GB RAM, no GPU)",
        "ram_gb": 12,
        "num_ctx": 8192,
        "manager": ("qwen2.5:3b", "3.1B"),
        "worker": ("qwen2.5-coder:1.5b", "1.5B"),
    },
    {
        "tier": "High-End (16-32 GB RAM + 8-12GB VRAM)",
        "ram_gb": 24,
        "num_ctx": 8192,
        "manager": ("qwen2.5:7b", "7.6B"),
        "worker": ("qwen2.5-coder:3b", "3.1B"),
    },
    {
        "tier": "32GB RAM + 12+GB VRAM",
        "ram_gb": 32,
        "num_ctx": 16384,
        "manager": ("qwen2.5:14b", "14.8B"),
        "worker": ("qwen2.5-coder:7b", "7.6B"),
    },
    {
        "tier": "64+GB RAM + 24GB VRAM",
        "ram_gb": 64,
        "num_ctx": 16384,
        "manager": ("codellama:34b", "34B"),
        "worker": ("qwen2.5-coder:14b", "14.8B"),
    },
]


def evaluate(entry: dict) -> dict:
    budget_bytes = int(entry["ram_gb"] * GB * DEFAULT_MEMORY_FRACTION)
    manager_name, manager_params = entry["manager"]
    worker_name, worker_params = entry["worker"]

    manager_fp = estimate_footprint(manager_name, 0, manager_params, entry["num_ctx"])
    worker_fp = estimate_footprint(worker_name, 0, worker_params, entry["num_ctx"])
    # Same model in both roles collapses to one footprint (per CLAUDE.md's own
    # rule) -- none of these five pairs hit that case, but the check costs nothing.
    footprints = {manager_name: manager_fp, worker_name: worker_fp}
    required_bytes = sum(fp.total_bytes for fp in footprints.values())

    return {
        "tier": entry["tier"],
        "stated_ram_gb": entry["ram_gb"],
        "num_ctx": entry["num_ctx"],
        "manager": f"{manager_name} ({manager_params})",
        "worker": f"{worker_name} ({worker_params})",
        "manager_gb": round(manager_fp.total_bytes / GB, 2),
        "worker_gb": round(worker_fp.total_bytes / GB, 2),
        "budget_gb": round(budget_bytes / GB, 2),
        "required_gb": round(required_bytes / GB, 2),
        "verdict": "RESIDENT (both fit together)" if required_bytes <= budget_bytes else "SWAP (does not fit together)",
        "fits": required_bytes <= budget_bytes,
    }


if __name__ == "__main__":
    results = [evaluate(p) for p in PAIRS]

    print(f"{'Tier':<40} {'Mgr GB':>7} {'Wkr GB':>7} {'Req GB':>7} {'Budget GB':>10}  Verdict")
    for r in results:
        print(
            f"{r['tier']:<40} {r['manager_gb']:>7.2f} {r['worker_gb']:>7.2f} "
            f"{r['required_gb']:>7.2f} {r['budget_gb']:>10.2f}  {r['verdict']}"
        )

    swaps = [r for r in results if not r["fits"]]
    print()
    if swaps:
        print(f"{len(swaps)}/{len(results)} recommended pairs land in SWAP at their own stated RAM figure:")
        for r in swaps:
            print(
                f"  - {r['tier']}: {r['manager']} + {r['worker']} needs {r['required_gb']}GB, budget is {r['budget_gb']}GB"
            )
    else:
        print(f"All {len(results)} recommended pairs fit resident at their stated RAM figure.")

    out_path = Path(__file__).resolve().parent / "results" / "model_pair_validation.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nWritten to {out_path}")
