"""Phase 2.4 — AST guard coverage, including the classes the original report never tested.

Per docs/benchmark-report-remediation-plan.md Phase 0.10: the original report's §9 tested
three positive controls (banned import, literal system path, `eval`) and called that "zero
false negatives." It never exercised the hard classes CodeGuard.scan() actually exists to
catch: computed/dunder attribute reflection, a bare `__builtins__` reference, and drive-letter
path folding on Windows. This script adds those as negative controls, plus one positive control
proving the path-folding logic doesn't reject a legitimate local write.

No LLM call, no Docker, no subprocess — CodeGuard.scan() is pure AST analysis, so this runs in
well under a second and needs nothing but the interpreter already running this script.

Usage: python scripts/benchmark_harness/guard_coverage.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from src.core.security.code_guard import CodeGuard  # noqa: E402


@dataclass
class Case:
    id: str
    category: str
    name: str
    code: str
    expect_blocked: bool
    extra_roots: tuple[str, ...] = ()


CASES: list[Case] = [
    # --- Original report's three positive controls (kept for continuity) ---
    Case("E1", "original", "Restricted system call", "import os\nos.system('whoami')", True),
    Case(
        "E2",
        "original",
        "System path access",
        "with open('C:/Windows/System32/drivers/etc/hosts', 'r') as f:\n    content = f.read()",
        True,
    ),
    Case("E3", "original", "Reflection builtins access (eval)", "eval('__builtins__')", True),
    # --- New: computed attribute reflection (Phase 0.10 gap 1) ---
    Case(
        "F1",
        "computed_reflection",
        "getattr with string-concatenation attribute name",
        "getattr(open, 'sys' + 'tem')",
        True,
    ),
    Case(
        "F2",
        "computed_reflection",
        "setattr with a computed (non-literal) attribute name",
        "name = '__' + 'class' + '__'\nsetattr(object, name, None)",
        True,
    ),
    Case(
        "F3",
        "computed_reflection",
        "hasattr probing a computed attribute name",
        "attr = ''.join(['__', 'builtins', '__'])\nhasattr(object, attr)",
        True,
    ),
    # --- New: dunder access via reflection with a LITERAL name not individually
    #     enumerated in BANNED_ATTRIBUTES — tests the startswith/endswith('__') catch-all ---
    Case(
        "F4",
        "dunder_catch_all",
        "getattr reaching an unenumerated dunder by literal name",
        "getattr([], '__class__')",
        True,
    ),
    # --- New: bare __builtins__ reference, not routed through eval/exec at all ---
    Case(
        "F5",
        "bare_builtins_name",
        "Bare __builtins__ name assigned to a variable",
        "leaked = __builtins__\nprint(leaked)",
        True,
    ),
    Case(
        "F6",
        "bare_builtins_name",
        "Bare __loader__ name reference",
        "print(__loader__)",
        True,
    ),
    # --- New: drive-letter path folding, backslash form, outside any allowed root ---
    Case(
        "F7",
        "drive_letter_path",
        "Backslash-form drive-letter path outside workspace",
        r"with open('C:\Windows\System32\drivers\etc\hosts', 'r') as f:" "\n    f.read()",
        True,
    ),
    Case(
        "F8",
        "drive_letter_path",
        "UNC-style network share path",
        r"with open('\\\\attacker-host\\share\\payload.txt', 'r') as f:" "\n    f.read()",
        True,
    ),
    # --- Positive control: the SAME folding logic must not reject a legitimate local
    #     write inside an extra_root a host-backend session actually gets granted. ---
    Case(
        "F9",
        "drive_letter_path_allowed",
        "Backslash-form path INSIDE a granted extra_root must be allowed",
        r"with open('C:\3rd_Year\Wizard-w1\workspace\sessions\bench\out.csv', 'w') as f:"
        "\n    f.write('ok')",
        False,
        extra_roots=("C:/3rd_Year/Wizard-w1/workspace/sessions/bench",),
    ),
]


def run() -> list[dict]:
    results = []
    for case in CASES:
        verdict = CodeGuard.scan(case.code, extra_roots=case.extra_roots)
        blocked = not verdict.ok
        passed = blocked == case.expect_blocked
        results.append(
            {
                "id": case.id,
                "category": case.category,
                "name": case.name,
                "expect_blocked": case.expect_blocked,
                "actual_blocked": blocked,
                "violations": verdict.violations,
                "status": "PASS" if passed else "FAIL",
            }
        )
    return results


if __name__ == "__main__":
    results = run()
    for r in results:
        marker = "\u2705" if r["status"] == "PASS" else "\u274c"
        print(f"{marker} {r['id']} [{r['category']}] {r['name']} -> blocked={r['actual_blocked']} (expected {r['expect_blocked']})")
        if r["violations"]:
            print(f"    {r['violations']}")

    failed = [r for r in results if r["status"] == "FAIL"]
    print()
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print(f"FAILED: {[r['id'] for r in failed]}")

    out_path = Path(__file__).resolve().parent / "results" / "guard_coverage_results.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nWritten to {out_path}")

    sys.exit(1 if failed else 0)
