"""Backwards-compatible facade over :mod:`src.core.security.code_guard`.

The project previously implemented two disagreeing guards: a regex denylist here
and an AST walk inlined in the agent. Both now delegate to a single AST-based
analyzer. This module is kept so existing imports and the ``(is_safe, reason)``
contract continue to work.
"""

from __future__ import annotations

import re

from src.core.security.code_guard import CodeGuard
from src.utils.logging import logger


class GuardrailAgent:
    """Thin adapter preserving the historical tuple-returning API."""

    @classmethod
    def scan(cls, code: str) -> tuple[bool, str]:
        verdict = CodeGuard.scan(code)
        if not verdict.ok:
            logger.warning("Guardrail triggered", reason=verdict.reason, syntax_error=verdict.syntax_error)
            if verdict.syntax_error:
                return False, verdict.reason
            return False, f"Guardrail Violation: {verdict.reason}"
        return True, "Safe"

    @classmethod
    def audit_scientific_alignment(cls, plan: str, code: str) -> tuple[bool, str]:
        """Heuristic check that the code plausibly implements the plan."""
        plan_keywords = re.findall(r"\b\w{4,}\b", plan.lower())
        code_lower = code.lower()

        matches = [kw for kw in plan_keywords if kw in code_lower]
        if len(matches) < 2 and len(plan_keywords) > 5:
            return False, "Code does not seem aligned with the proposed plan."

        return True, "Aligned"
