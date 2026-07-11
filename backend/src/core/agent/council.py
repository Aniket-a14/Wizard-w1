import asyncio
from typing import Any

from langchain_ollama import ChatOllama

from src.config import settings
from src.utils.logging import logger, trace_agent


class SpecialistAgent:
    """Base class for specialized async council agents."""

    async def review(self, plan: str, code: str, result: str) -> dict[str, Any]:
        raise NotImplementedError


class VisualizerAgent(SpecialistAgent):
    """Expert in Plotly/Seaborn aesthetics (Async LLM-based)."""

    async def review(self, plan: str, code: str, result: str) -> dict[str, Any]:
        feedback = []
        score = 100

        # 1. Deterministic local check first
        has_plot = "plt." in code or "sns." in code
        if not has_plot:
            return {"agent": "Visualizer", "score": 100, "feedback": []}

        if "plt.title" not in code:
            score -= 20
            feedback.append("Missing plot title.")
        if "plt.xlabel" not in code or "plt.ylabel" not in code:
            score -= 20
            feedback.append("Missing axis labels.")

        # 2. Async LLM check for style critique
        try:
            # Short timeout to avoid hanging the chat if Ollama is slow
            llm = ChatOllama(
                model=settings.WORKER_MODEL_NAME, base_url=settings.OLLAMA_BASE_URL, temperature=0.2, timeout=5.0
            )
            prompt = f"""You are a Visual Design Advisor. Review this matplotlib/seaborn code for aesthetic design:
Code:
```python
{code}
```
Critique the plot configuration (colors, labels, styling). Return 1 short tip to improve the visual design, or say 'Aesthetics are solid' if no improvement is needed.
"""
            res = await llm.ainvoke(prompt)
            tip = res.content.strip()
            if "Aesthetics are solid" not in tip and len(tip) > 5:
                feedback.append(f"LLM Tip: {tip}")
        except Exception as e:
            logger.warning("Visualizer LLM review failed, falling back to local checks", error=str(e))

        return {"agent": "Visualizer", "score": max(score, 0), "feedback": feedback}


class StatisticianAgent(SpecialistAgent):
    """Validates statistical assumptions and findings (Async LLM-based)."""

    async def review(self, plan: str, code: str, result: str) -> dict[str, Any]:
        feedback = []
        is_relevant = "test" in plan.lower() or "stats" in plan.lower() or "model" in plan.lower()

        if not is_relevant:
            return {"agent": "Statistician", "is_relevant": False, "feedback": []}

        # Deterministic checks
        if "p-value" not in result.lower() and "p_value" not in result.lower():
            feedback.append("Scientific Warning: Analysis mentions testing but no p-value reported.")

        # Async LLM check
        try:
            llm = ChatOllama(model=settings.MODEL_NAME, base_url=settings.OLLAMA_BASE_URL, temperature=0.2, timeout=5.0)
            prompt = f"""You are a Statistical Advisor. Review this data science plan and execution output:
Plan: {plan}
Result: {result}
Critique the statistical validity. Identify any missing assumptions, warnings, or incorrect interpretations.
Return 1 short scientific tip, or say 'Analysis is statistically sound'.
"""
            res = await llm.ainvoke(prompt)
            tip = res.content.strip()
            if "statistically sound" not in tip.lower() and len(tip) > 5:
                feedback.append(f"Statistical Tip: {tip}")
        except Exception as e:
            logger.warning("Statistician LLM review failed, falling back to local checks", error=str(e))

        return {"agent": "Statistician", "is_relevant": is_relevant, "feedback": feedback}


class ArchitectAgent(SpecialistAgent):
    """Ensures code follows style and performance best practices (Async LLM-based)."""

    async def review(self, plan: str, code: str, result: str) -> dict[str, Any]:
        feedback = []

        # Deterministic checks
        if "for index, row in" in code:
            feedback.append(
                "Performance Warning: Iterative row processing detected. Use vectorized operations for speed."
            )

        # Async LLM check
        try:
            llm = ChatOllama(
                model=settings.WORKER_MODEL_NAME, base_url=settings.OLLAMA_BASE_URL, temperature=0.2, timeout=5.0
            )
            prompt = f"""You are a Code Performance Architect. Review this Python script for performance/efficiency:
Code:
```python
{code}
```
Critique the code implementation structure. Return 1 short performance suggestion, or say 'Code is well-architected'.
"""
            res = await llm.ainvoke(prompt)
            tip = res.content.strip()
            if "well-architected" not in tip.lower() and len(tip) > 5:
                feedback.append(f"Architect Tip: {tip}")
        except Exception as e:
            logger.warning("Architect LLM review failed, falling back to local checks", error=str(e))

        return {"agent": "Architect", "feedback": feedback}


class TheCouncil:
    """Orchestrates concurrent reviews from all specialized agents."""

    def __init__(self):
        self.specialists = [VisualizerAgent(), StatisticianAgent(), ArchitectAgent()]

    @trace_agent("TheCouncil")
    async def adjudicate(self, plan: str, code: str, result: str) -> dict[str, Any]:
        """Runs all specialists concurrently using asyncio.gather to optimize execution speed."""
        tasks = [agent.review(plan, code, result) for agent in self.specialists]
        reviews = await asyncio.gather(*tasks)

        return {"reviews": reviews, "overall_status": "Reviewed by The Council"}
