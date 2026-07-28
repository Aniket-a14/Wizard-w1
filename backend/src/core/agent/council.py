"""Specialist reviewers that critique a finished analysis.

Each specialist runs a cheap deterministic check first and only escalates to the
LLM when there is something worth asking about. The previous version issued an
LLM call unconditionally from all three reviewers on every successful execution
-- three extra round-trips on a laptop running local models, for feedback that
was frequently "looks fine".

Reviews are also advisory now: findings surface as warnings rather than being
concatenated into the user-facing answer, which is what the frontend had grown
regexes to strip back out.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.config import settings
from src.core.llm import LLMRole, llm_provider, strip_reasoning
from src.utils.logging import logger, trace_agent


if TYPE_CHECKING:  # `src.core.session` pulls in the executor; keep that out of import order
    from src.core.session import ModelPreferences


class SpecialistAgent:
    """Base class for a reviewer."""

    name = "Specialist"

    async def review(self, plan: str, code: str, result: str, models: ModelPreferences | None = None) -> dict[str, Any]:
        raise NotImplementedError

    async def _ask(self, prompt: str, role: LLMRole = LLMRole.WORKER, models: ModelPreferences | None = None) -> str:
        # Specialists used to always run on the configured default model, which
        # quietly ignored the user's choice for the rest of the session.
        role_name = role.value
        try:
            return (
                await llm_provider.acomplete(
                    prompt,
                    role=role,
                    temperature=0.2,
                    model=models.model_for(role_name) if models else None,
                    provider=models.provider_for(role_name) if models else None,
                    # One sentence is what is asked for and one sentence is what
                    # is used; the caveat is appended to a warning list.
                    max_tokens=settings.output_budget("review"),
                )
            ).strip()
        except Exception as exc:
            logger.debug("Specialist LLM review skipped", agent=self.name, error=str(exc))
            return ""


class VisualizerAgent(SpecialistAgent):
    """Checks that charts are legible and labelled."""

    name = "Visualizer"

    async def review(self, plan: str, code: str, result: str, models: ModelPreferences | None = None) -> dict[str, Any]:
        produces_plot = any(marker in code for marker in ("plt.", "sns.", "px.", "go."))
        if not produces_plot:
            return {"agent": self.name, "applicable": False, "feedback": []}

        feedback: list[str] = []
        uses_matplotlib = "plt." in code or "sns." in code
        if uses_matplotlib:
            if "title" not in code:
                feedback.append("The chart has no title.")
            if "xlabel" not in code or "ylabel" not in code:
                feedback.append("The chart is missing one or both axis labels.")
        elif "title" not in code and "labels" not in code:
            feedback.append("The Plotly figure has no title or axis labels configured.")

        return {"agent": self.name, "applicable": True, "feedback": feedback}


class StatisticianAgent(SpecialistAgent):
    """Flags statistical claims made without the supporting evidence."""

    name = "Statistician"

    RELEVANT = ("test", "hypothesis", "significan", "correlat", "regress", "model", "predict", "distribution")

    async def review(self, plan: str, code: str, result: str, models: ModelPreferences | None = None) -> dict[str, Any]:
        haystack = f"{plan} {code}".lower()
        if not any(marker in haystack for marker in self.RELEVANT):
            return {"agent": self.name, "applicable": False, "feedback": []}

        feedback: list[str] = []
        lowered = result.lower()
        claims_significance = "significan" in lowered or "reject" in lowered
        reports_p_value = "p-value" in lowered or "p_value" in lowered or "pvalue" in lowered
        if claims_significance and not reports_p_value:
            feedback.append("Significance is claimed but no p-value is reported.")

        if "corr" in haystack and "causal" in lowered:
            feedback.append("Correlation is being described in causal terms.")

        if feedback:
            tip = await self._ask(
                "You are a statistical reviewer. In one sentence, state the single most important "
                f"caveat for this analysis.\n\nPlan: {plan[:800]}\n\nOutput: {result[:800]}",
                role=LLMRole.MANAGER,
                models=models,
            )
            tip = strip_reasoning(tip)
            if tip and "sound" not in tip.lower():
                feedback.append(tip)

        return {"agent": self.name, "applicable": True, "feedback": feedback}


class ArchitectAgent(SpecialistAgent):
    """Catches pandas anti-patterns that will not scale."""

    name = "Architect"

    ANTIPATTERNS = (
        ("for index, row in", "Row-by-row iteration detected; a vectorised operation would be far faster."),
        (".iterrows()", "`.iterrows()` is slow on large frames; prefer vectorised operations."),
        (").append(", "`DataFrame.append` is removed in pandas 2.x; use `pd.concat` instead."),
        ("inplace=True", "`inplace=True` is deprecated in several pandas APIs; prefer reassignment."),
    )

    async def review(self, plan: str, code: str, result: str, models: ModelPreferences | None = None) -> dict[str, Any]:
        feedback = [message for pattern, message in self.ANTIPATTERNS if pattern in code]
        return {"agent": self.name, "applicable": bool(feedback), "feedback": feedback}


class TheCouncil:
    """Runs every specialist concurrently and aggregates their findings."""

    def __init__(self):
        self.specialists: list[SpecialistAgent] = [VisualizerAgent(), StatisticianAgent(), ArchitectAgent()]

    @trace_agent("TheCouncil")
    async def adjudicate(
        self, plan: str, code: str, result: str, models: ModelPreferences | None = None
    ) -> dict[str, Any]:
        if not settings.COUNCIL_ENABLED:
            return {"reviews": [], "status": "disabled"}

        outcomes = await asyncio.gather(
            *(specialist.review(plan, code, result, models) for specialist in self.specialists),
            return_exceptions=True,
        )

        reviews: list[dict[str, Any]] = []
        for specialist, outcome in zip(self.specialists, outcomes, strict=True):
            if isinstance(outcome, Exception):
                logger.warning("Specialist review failed", agent=specialist.name, error=str(outcome))
                continue
            reviews.append(outcome)

        return {
            "reviews": [review for review in reviews if review.get("feedback")],
            "status": "reviewed",
        }
