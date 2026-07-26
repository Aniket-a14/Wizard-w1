"""Heuristic scoring of an execution result.

The error check now looks for the marker the executor actually emits rather than
the substring ``"Error"``, which matched any output containing words like
"Errors found: 0" or a column named ``error_rate`` and silently halved the score.
"""

from __future__ import annotations

import re
from typing import Any


ERROR_MARKERS = ("Error executing code:", "Traceback (most recent call last)")

ANALYTICAL_KEYWORDS = frozenset(
    {
        "test",
        "correlation",
        "regression",
        "model",
        "hypothesis",
        "distribution",
        "stats",
        "statistical",
        "significance",
        "predict",
    }
)

RIGOUR_KEYWORDS = ("mean", "median", "distribution", "variance", "std", "p-value", "significant", "confidence")

PROHIBITED_CALLS = ("exec(", "eval(", "os.system", "subprocess", "__import__")


class Evaluator:
    """Cheap, deterministic quality signal recorded alongside each interaction."""

    @staticmethod
    def score_execution(
        result: str,
        expected_snippet: str | None = None,
        instruction: str | None = None,
    ) -> dict[str, Any]:
        score = 100
        deductions: list[str] = []
        text = result or ""

        if any(marker in text for marker in ERROR_MARKERS):
            score -= 50
            deductions.append("Execution error detected.")

        if expected_snippet and expected_snippet.lower() not in text.lower():
            score -= 30
            deductions.append(f"Expected content '{expected_snippet}' was not present.")

        is_analytical = any(keyword in instruction.lower() for keyword in ANALYTICAL_KEYWORDS) if instruction else True
        if is_analytical:
            lowered = text.lower()
            if not any(keyword in lowered for keyword in RIGOUR_KEYWORDS):
                score -= 10
                deductions.append("Result reports no summary statistics.")

        score = max(0, score)
        return {"score": score, "deductions": deductions, "status": "PASS" if score >= 70 else "FAIL"}

    @staticmethod
    def evaluate_code_quality(code: str) -> dict[str, Any]:
        warnings: list[str] = []
        is_clean = True

        for call in PROHIBITED_CALLS:
            if call in code:
                is_clean = False
                warnings.append(f"Prohibited call '{call}' detected.")

        if code.strip() and not re.search(r"^\s*(import|from)\s", code, re.MULTILINE):
            warnings.append("No imports detected; the snippet may be incomplete.")

        return {
            "is_clean": is_clean,
            "warnings": warnings,
            "quality_rating": "High" if is_clean and not warnings else "Low",
        }
