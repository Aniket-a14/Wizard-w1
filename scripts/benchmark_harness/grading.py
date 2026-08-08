"""Phase 1.1 content-based grading.

Per docs/benchmark-methodology-spec.md and the plan's Phase -1.1: the original
harness graded `one_shot_success` from a field it wrote independently of the
answer text it was holding, which is how six of nine local-mode "successes" were
actually KeyErrors narrated in prose. This module grades from the answer content
itself against reference_answers.py, and never from a self-reported status.

Reuses grounding.py's own number-matching logic (`_matches`, rounding-precision
tolerance, magnitude words) rather than reimplementing a second, possibly
diverging notion of "close enough" -- the same reasoning
benchmark-report-remediation-plan.md 1.3 already relies on.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from reference_answers import by_id  # noqa: E402

from src.core.agent import grounding as g  # noqa: E402


@dataclass
class GradeResult:
    case_id: str
    passed: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"case_id": self.case_id, "passed": self.passed, "reasons": self.reasons}


def _observed_values(executed_output: str) -> list[float]:
    return [v for v in (g._as_float(t) for t in g.extract_numbers(executed_output)) if v is not None]  # noqa: SLF001


def grade(case_id: str, answer: str, executed_output: str) -> GradeResult:
    """Grades one turn's answer against its reference case.

    Three independent checks, ANY of which failing fails the whole case:
    1. Execution must not describe its own failure (KeyError/Traceback echoed
       into the answer -- exactly the Phase -1.1 pattern).
    2. Every `expected_numbers` entry must be traceable to the REAL execution
       output (not just present in the answer's prose) -- this is what makes a
       case pass on correctness, not merely on fluency.
    3. Every `must_mention` term must appear in the answer; no
       `forbidden_if_present` term may appear.
    """
    case = by_id(case_id)
    if case is None:
        return GradeResult(case_id, False, [f"No reference case registered for id '{case_id}'."])

    reasons: list[str] = []
    lower_answer = (answer or "").lower()
    lower_output = (executed_output or "").lower()

    # Check 1: the answer or the execution output is itself narrating a failure.
    failure_markers = ("keyerror", "traceback (most recent call last)", "nameerror", "attributeerror")
    for marker in failure_markers:
        if marker in lower_answer or marker in lower_output:
            reasons.append(f"Answer or output contains an unhandled error marker: '{marker}'.")

    # Check 2: every expected number must trace to real execution output --
    # reuses grounding.py's own tolerance logic rather than a second one.
    observed = _observed_values(executed_output)
    for expected in case.expected_numbers:
        if not any(g._matches(str(expected), value) for value in observed):  # noqa: SLF001
            reasons.append(f"Expected value {expected} does not appear in real execution output.")

    # Check 3: qualitative content checks.
    for term in case.must_mention:
        if term.lower() not in lower_answer:
            reasons.append(f"Answer must mention '{term}' and does not.")
    for term in case.forbidden_if_present:
        if term.lower() in lower_answer:
            reasons.append(f"Answer contains forbidden term '{term}' (a known fabrication pattern for this case).")

    return GradeResult(case_id, passed=not reasons, reasons=reasons)


def grade_all(turns: dict[str, dict]) -> list[GradeResult]:
    """`turns` maps case_id -> {"answer": str, "executed_output": str}."""
    return [grade(case_id, turn.get("answer", ""), turn.get("executed_output", "")) for case_id, turn in turns.items()]
