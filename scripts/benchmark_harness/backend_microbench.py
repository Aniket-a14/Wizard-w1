"""Phase 2.3 / 1.6 / 1.7 — controlled cold/warm execution-backend microbenchmark.

Per docs/benchmark-methodology-spec.md 1.6: the original report's Docker (0.418s)
vs Host (5.333s) numbers are not a like-for-like comparison -- image state, daemon
warmth, and interpreter/pandas import were not controlled. This script measures
cold spawn, warm spawn (reuse), cold exec, warm exec, and teardown separately for
whichever single backend is named by EXECUTION_BACKEND in the environment, plus
records the 1.7 host-precondition fields so the numbers are interpretable later.

No LLM call: the code executed is a trivial `print()`, so this only measures the
execution-backend plumbing itself, never model inference. Safe to run directly.

Usage (backend is read from the environment, one process per backend so the
Settings singleton picks up the right value at import time):

    EXECUTION_BACKEND=host   python scripts/benchmark_harness/backend_microbench.py
    EXECUTION_BACKEND=docker python scripts/benchmark_harness/backend_microbench.py
    EXECUTION_BACKEND=inprocess python scripts/benchmark_harness/backend_microbench.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"

# --- environment must be pinned before any `src` import: Settings is built at
#     import time, exactly like backend/tests/conftest.py does it. ---
_BENCH_ROOT = Path(tempfile.mkdtemp(prefix="wizard-bench-"))
os.environ.setdefault("WORKSPACE_DIR", str(_BENCH_ROOT / "workspace"))
os.environ.setdefault("DATA_DIR", str(_BENCH_ROOT / "data"))
os.environ.setdefault("LOG_DIR", str(_BENCH_ROOT / "logs"))
os.environ.setdefault("WIZARD_CONFIG_DIR", str(_BENCH_ROOT / "config"))
os.environ.setdefault("API_PROVIDER", "ollama")
os.environ.setdefault("REDIS_URL", "")
requested_backend = os.environ.get("EXECUTION_BACKEND", "host")
if requested_backend == "docker":
    os.environ.setdefault("SANDBOX_ENABLED", "true")

sys.path.insert(0, str(BACKEND_DIR))

from src.config import settings  # noqa: E402
from src.core.execution import CodeExecutor  # noqa: E402
from src.core.tools import runtime as runtime_backend  # noqa: E402


def timed(fn):
    t0 = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - t0


def main() -> dict:
    resolved_backend = runtime_backend.active_backend()
    baseline_count = runtime_backend.active_runtime_count()

    session_id = f"bench-{requested_backend}-{uuid.uuid4().hex[:8]}"
    executor = CodeExecutor(session_id)
    report: dict = {
        "requested_backend": requested_backend,
        "resolved_backend": resolved_backend,
        "degraded": requested_backend != resolved_backend,
        "session_id": session_id,
        "baseline_active_runtime_count": baseline_count,
        # 1.7 host preconditions
        "host_sandbox_mode": settings.HOST_SANDBOX,
        "sandbox_image": settings.sandbox_image if resolved_backend == "docker" else None,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        # --- Cold spawn: first runtime acquisition for a brand-new session id ---
        runtime_obj, cold_spawn_sec = timed(lambda: runtime_backend.get_runtime(session_id, create=True))
        report["cold_spawn_sec"] = round(cold_spawn_sec, 4)
        report["cold_spawn_got_runtime"] = runtime_obj is not None

        # --- Cold exec: first code execution on that runtime (daemon handshake
        #     included). Docker/host daemons can still be finishing startup the
        #     instant after the container/process is reported "started" -- a real
        #     orchestrator turn never notices because an LLM round-trip always
        #     separates spawn from the first execute() call, but a synthetic
        #     benchmark calling execute() immediately can race it. Recorded
        #     honestly (first-attempt result + retries-to-settle) rather than
        #     papered over with a fixed warm-up sleep before measuring.
        cold_result, cold_exec_sec = timed(lambda: executor.execute("print('bench cold exec ok')"))
        report["cold_exec_sec"] = round(cold_exec_sec, 4)
        report["cold_exec_ok"] = cold_result.ok
        report["cold_exec_backend"] = cold_result.backend
        report["cold_exec_isolation"] = cold_result.isolation
        report["cold_exec_first_attempt_output"] = cold_result.output[:200]

        retries = 0
        settle_start = time.perf_counter()
        while not cold_result.ok and retries < 5:
            time.sleep(0.5 * (retries + 1))
            retries += 1
            cold_result = executor.execute("print('bench cold exec retry ok')")
        if retries:
            report["cold_exec_settle_retries"] = retries
            report["cold_exec_settle_sec"] = round(time.perf_counter() - settle_start, 4)
            report["cold_exec_settled_ok"] = cold_result.ok

        # --- Warm exec: same runtime, second call ---
        warm_result, warm_exec_sec = timed(lambda: executor.execute("print('bench warm exec ok')"))
        report["warm_exec_sec"] = round(warm_exec_sec, 4)
        report["warm_exec_ok"] = warm_result.ok

        # --- Warm "spawn": re-requesting a runtime that's already up (reuse, not
        #     a fresh process/container) ---
        _, warm_spawn_sec = timed(lambda: runtime_backend.get_runtime(session_id, create=True))
        report["warm_spawn_sec"] = round(warm_spawn_sec, 4)

        active_before_teardown = runtime_backend.active_runtime_count()
        report["active_runtime_count_before_teardown"] = active_before_teardown

        # --- Teardown ---
        _, teardown_sec = timed(lambda: runtime_backend.release_runtime(session_id))
        report["teardown_sec"] = round(teardown_sec, 4)

        active_after_teardown = runtime_backend.active_runtime_count()
        report["active_runtime_count_after_teardown"] = active_after_teardown
        report["lifecycle_verified"] = active_after_teardown == baseline_count
        report["status"] = "PASSED"
    except Exception as exc:  # noqa: BLE001 - a benchmark records the failure, doesn't hide it
        report["status"] = "FAILED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        try:
            runtime_backend.release_runtime(session_id)
        except Exception:  # noqa: BLE001 - best-effort cleanup after an already-recorded failure
            pass

    return report


if __name__ == "__main__":
    report = main()
    print(json.dumps(report, indent=2))

    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"backend_microbench_{requested_backend}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nWritten to {out_path}")

    sys.exit(0 if report.get("status") == "PASSED" else 1)
