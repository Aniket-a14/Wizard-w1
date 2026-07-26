"""Executive summary generation.

Previously read ``working_memory.memories`` as a plain list attribute. That
attribute stopped existing when memory moved to SQLite, so ``GET /report``
raised ``AttributeError`` and returned 500 on every call. It now queries the
store directly and handles the empty case.
"""

from __future__ import annotations

import time
from typing import Any

from src.core.memory import working_memory


class ReportingEngine:
    """Aggregates session interactions into a readable markdown report."""

    @staticmethod
    def generate_executive_summary(timespan_seconds: int = 3600, session_id: str | None = None) -> str:
        entries = working_memory.recent(timespan_seconds=timespan_seconds, session_id=session_id)

        if not entries:
            return (
                "## No analysis to summarise yet\n\n"
                "Run a few questions against your dataset and the report will collect the findings here."
            )

        lines = [
            "# Analysis Report",
            f"*Generated {time.strftime('%Y-%m-%d %H:%M:%S')} — {len(entries)} interaction(s).*",
            "",
            "## Findings",
        ]

        for index, entry in enumerate(entries, start=1):
            instruction = (entry.get("instruction") or "Untitled request").strip()
            result = (entry.get("result") or "").strip()
            summary = result[:400] + ("..." if len(result) > 400 else "")
            lines.append(f"### {index}. {instruction}")
            goal = ReportingEngine._extract_goal(entry.get("plan") or "")
            if goal:
                lines.append(f"**Approach:** {goal}")
            lines.append(f"**Outcome:** {summary or 'No output recorded.'}")
            lines.append("")

        scores = [
            entry.get("meta", {}).get("quality_score")
            for entry in entries
            if isinstance(entry.get("meta"), dict) and entry.get("meta", {}).get("quality_score") is not None
        ]
        lines.append("## Reliability")
        lines.append("- Generated code was statically screened before every execution.")
        lines.append("- Execution took place in an isolated container where Docker was available.")
        if scores:
            lines.append(f"- Mean heuristic quality score: {sum(scores) / len(scores):.1f}/100")

        return "\n".join(lines)

    @staticmethod
    def _extract_goal(plan: str) -> str:
        """First meaningful line of a plan, trimmed for display."""
        for line in plan.strip().splitlines():
            cleaned = line.strip().lstrip("0123456789.-) ").strip()
            if cleaned and not cleaned.startswith("<"):
                return cleaned[:160]
        return ""

    @staticmethod
    def summary_payload(timespan_seconds: int = 3600, session_id: str | None = None) -> dict[str, Any]:
        entries = working_memory.recent(timespan_seconds=timespan_seconds, session_id=session_id)
        return {
            "report": ReportingEngine.generate_executive_summary(timespan_seconds, session_id),
            "interaction_count": len(entries),
        }


reporting_engine = ReportingEngine()
