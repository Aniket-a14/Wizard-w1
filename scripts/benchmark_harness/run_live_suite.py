"""Live suite: A1-D2 user-story cases across local-only, hybrid, and cloud-only,
using the harness built in run_benchmark.py / grading.py / reference_answers.py.

Order is cloud -> hybrid -> local-only deliberately: cloud is fastest (~10-15s/turn),
so it validates the Gemini gateway wiring cheaply before committing to the much
longer local-mode run (~80-160s/turn). Results are written incrementally after
each case so a failure partway through does not lose what already ran.

Gateway credentials are read from the root .env's GEMINI_API_KEY and passed as
GATEWAY_API_URL / GATEWAY_API_KEY -- set as process environment, never written to
backend/.env, so nothing persists after this run.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"

# --- read the Gemini key from root .env without ever printing it, and wire it
#     as the generic OpenAI-compatible gateway (matches the earlier report's own
#     "custom_gateway:gemini-2.5-flash" setup) ---
root_env = (REPO_ROOT / ".env").read_text()
match = re.search(r"^GEMINI_API_KEY=(.+)$", root_env, re.MULTILINE)
if not match:
    raise SystemExit("No GEMINI_API_KEY found in root .env")
gemini_key = match.group(1).strip()

os.environ.setdefault("GATEWAY_API_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
os.environ["GATEWAY_API_KEY"] = gemini_key
os.environ.setdefault("SANDBOX_ENABLED", "false")  # host backend, matches original report's setup
os.environ.setdefault("EXECUTION_BACKEND", "host")

sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_benchmark import host_preconditions, run_one_turn  # noqa: E402
from grading import grade  # noqa: E402
from reference_answers import REFERENCE_CASES  # noqa: E402
from src.core.semantic_cache import semantic_cache  # noqa: E402

DATASET = REPO_ROOT / "workspace" / "dataset.csv"
HOUSING = REPO_ROOT / "workspace" / "housing.csv"

CASE_IDS = ["A1", "A2", "A3", "B1", "B2", "C1", "C2", "C3", "D1", "D2"]

#: Modes that spend Gemini free-tier quota (5 req/min/model) and need pacing.
#: A single turn can burn 4-8 calls across its iterations, so back-to-back
#: cases reliably exhaust the free tier -- discovered the hard way on the
#: first run of this suite (5 of 8 cloud-only cases came back 429, not a real
#: system failure). COOLDOWN_SEC is deliberately generous, not tuned to the
#: minimum that might work.
QUOTA_LIMITED_MODES = {"cloud-only", "hybrid"}
COOLDOWN_SEC = 25
RETRY_DELAY_PATTERN = re.compile(r"retry in ([\d.]+)s|'retryDelay': '(\d+)s'")


def _is_quota_error(turn: dict) -> bool:
    text = (turn.get("answer") or "") + str(turn.get("error") or "")
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "exceeded your current quota" in text


def _suggested_retry_delay(turn: dict, default: float = 35.0) -> float:
    text = (turn.get("answer") or "") + str(turn.get("error") or "")
    match = RETRY_DELAY_PATTERN.search(text)
    if not match:
        return default
    value = match.group(1) or match.group(2)
    return float(value) + 5.0  # buffer on top of the API's own suggested delay


async def run_with_quota_retry(mode: str, prompt: str, dataset_path, models: dict, max_retries: int = 2) -> dict:
    """Retries a turn that failed purely on rate-limiting, up to max_retries times,
    waiting the API's own suggested delay (plus a buffer) between attempts. A
    failure for any other reason is returned as-is -- this is not a general
    retry-until-success loop, only a rate-limit-specific one."""
    turn = await run_one_turn(mode, prompt, dataset_path, models)
    attempts = 0
    while _is_quota_error(turn) and attempts < max_retries:
        delay = _suggested_retry_delay(turn)
        print(f"    quota hit, waiting {delay}s before retry {attempts + 1}/{max_retries}", flush=True)
        await asyncio.sleep(delay)
        turn = await run_one_turn(mode, prompt, dataset_path, models)
        attempts += 1
    return turn

#: gemini-2.5-flash hit its 20/day free-tier cap. Quota turned out to be pooled
#: across the whole "flash" model family, not strictly per exact model name --
#: gemini-2.0-flash was exhausted on first use despite never being called
#: before. Overridable so a fresh, untouched model can be swapped in per role.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")
#: Config B (report section 11.3): cloud manager, local worker -- the reverse
#: of Config A. Separate env var because Config A and B can need different
#: models on the same day once one family's quota is exhausted.
GEMINI_MANAGER_MODEL = os.environ.get("GEMINI_MANAGER_MODEL_NAME", GEMINI_MODEL)

#: Each entry is (result-label, data_mode, models). The label is what results
#: are keyed/deduplicated by; data_mode is what's actually passed to
#: orchestrator.run via Session.data_mode. They differ for "hybrid-cfgB": it's
#: still data_mode="hybrid" as far as the app is concerned, but needs its own
#: result rows distinct from Config A's ("hybrid") so a rerun of one doesn't
#: skip or collide with the other.
_ALL_MODE_CONFIGS = [
    (
        "cloud-only",
        "cloud-only",
        {
            "manager_provider": "custom_gateway",
            "manager_model": GEMINI_MODEL,
            "worker_provider": "custom_gateway",
            "worker_model": GEMINI_MODEL,
        },
    ),
    (
        "hybrid",
        "hybrid",
        {
            "manager_provider": "ollama",
            "manager_model": "qwen2.5:3b",
            "worker_provider": "custom_gateway",
            "worker_model": GEMINI_MODEL,
        },
    ),
    (
        "hybrid-cfgB",
        "hybrid",
        {
            "manager_provider": "custom_gateway",
            "manager_model": GEMINI_MANAGER_MODEL,
            "worker_provider": "ollama",
            "worker_model": "qwen2.5-coder:1.5b",
        },
    ),
    (
        "local-only",
        "local-only",
        {
            "manager_provider": "ollama",
            "manager_model": "qwen2.5:3b",
            "worker_provider": "ollama",
            "worker_model": "qwen2.5-coder:1.5b",
        },
    ),
]

#: Restrict which labels this run covers, e.g. LIVE_SUITE_MODES=hybrid-cfgB.
#: Matches against the result-label (first tuple element), not data_mode, so
#: Config A and Config B can be selected independently despite sharing
#: data_mode="hybrid".
_requested_modes = os.environ.get("LIVE_SUITE_MODES", "")
if _requested_modes:
    wanted = {m.strip() for m in _requested_modes.split(",")}
    MODE_CONFIGS = [mc for mc in _ALL_MODE_CONFIGS if mc[0] in wanted]
else:
    MODE_CONFIGS = _ALL_MODE_CONFIGS

OUT_PATH = Path(__file__).resolve().parent / "results" / "live_suite_results.json"


def dataset_for(case_id: str) -> Path:
    case = next(c for c in REFERENCE_CASES if c.id == case_id)
    return HOUSING if case.dataset == "housing.csv" else DATASET


def _merge_and_write(results: list[dict]) -> list[dict]:
    """Re-reads the file and merges with in-memory results before writing.

    Two invocations of this script (e.g. cloud-only and local-only launched side
    by side to dodge quota/RAM contention) each hold their own in-memory list
    read once at startup. A blind overwrite here silently lost 5 real cloud
    results once already -- the local-only process's next save clobbered them
    because they weren't in its own list. Keyed by (mode, case_id), the freshest
    write for a given key wins, but a key only the other process has survives.
    """
    disk: list[dict] = []
    if OUT_PATH.exists():
        try:
            disk = json.loads(OUT_PATH.read_text())
        except Exception:  # noqa: BLE001 - a corrupt partial file just starts fresh
            disk = []
    merged = {(r["mode"], r["case_id"]): r for r in disk}
    merged.update({(r["mode"], r["case_id"]): r for r in results})
    out = list(merged.values())
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    return out


async def main() -> None:
    # The semantic cache is global -- keyed only on (question text, columns), no
    # session/provider/model scoping -- and persists in backend/data/wizard.db
    # across every invocation of this script, and every other session that ever
    # ran against this dataset. Without this, a case can silently execute code
    # generated by a *different* config's worker (or a session from days ago)
    # instead of the one actually under test, which happened repeatedly today:
    # local-only cases replayed gemini-2.5-flash's cached code, and a from-scratch
    # Config B run replayed Config A's, both undetected until wall-clock time and
    # guard-rejection paths gave it away. Clearing here makes every run start from
    # a guaranteed-clean slate rather than relying on remembering to do this by hand.
    semantic_cache.clear()
    OUT_PATH.parent.mkdir(exist_ok=True)
    results: list[dict] = []
    if OUT_PATH.exists():
        try:
            results = json.loads(OUT_PATH.read_text())
        except Exception:  # noqa: BLE001 - a corrupt partial file just starts fresh
            results = []
    done_keys = {(r["mode"], r["case_id"]) for r in results}

    print(f"Host preconditions at start: {host_preconditions()}", flush=True)

    for label, data_mode, models in MODE_CONFIGS:
        for case_id in CASE_IDS:
            if (label, case_id) in done_keys:
                print(f"SKIP (already done): {label}/{case_id}", flush=True)
                continue

            case = next(c for c in REFERENCE_CASES if c.id == case_id)
            print(f"=== {label} / {case_id}: {case.name} ===", flush=True)
            t0 = time.perf_counter()
            try:
                if data_mode in QUOTA_LIMITED_MODES:
                    turn = await run_with_quota_retry(data_mode, case.prompt, dataset_for(case_id), models)
                else:
                    turn = await run_one_turn(data_mode, case.prompt, dataset_for(case_id), models)
                graded = grade(case_id, turn["answer"], turn["executed_output"])
                record = {
                    "mode": label,
                    "case_id": case_id,
                    "case_name": case.name,
                    "models": models,
                    **turn,
                    "graded_pass": graded.passed,
                    "graded_reasons": graded.reasons,
                    "wall_clock_sec": round(time.perf_counter() - t0, 2),
                }
            except Exception as exc:  # noqa: BLE001 - record the failure, keep the suite going
                record = {
                    "mode": label,
                    "case_id": case_id,
                    "case_name": case.name,
                    "models": models,
                    "status": "harness_error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "wall_clock_sec": round(time.perf_counter() - t0, 2),
                }

            results.append(record)
            results = _merge_and_write(results)
            pass_marker = record.get("graded_pass")
            print(
                f"  -> {record['wall_clock_sec']}s, pass={pass_marker}, "
                f"reasons={record.get('graded_reasons') or record.get('error', '')}",
                flush=True,
            )

            if data_mode in QUOTA_LIMITED_MODES:
                print(f"  cooling down {COOLDOWN_SEC}s before next quota-limited case", flush=True)
                await asyncio.sleep(COOLDOWN_SEC)

    print(f"\nDONE. {len(results)} turns written to {OUT_PATH}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
