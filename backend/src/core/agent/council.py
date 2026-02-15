from typing import Dict, Any
import re
from src.utils.logging import logger, trace_agent

class SpecialistAgent:
    """Base class for specialized council agents."""
    def review(self, plan: str, code: str, result: str) -> Dict[str, Any]:
        raise NotImplementedError

class VisualizerAgent(SpecialistAgent):
    """Expert in Plotly/Seaborn aesthetics."""
    def review(self, plan: str, code: str, result: str) -> Dict[str, Any]:
        has_plot = "plt." in code or "sns." in code
        score = 100 if has_plot else 0
        feedback = []
        
        if has_plot:
            if "plt.title" not in code:
                score -= 20
                feedback.append("Missing plot title.")
            if "plt.xlabel" not in code or "plt.ylabel" not in code:
                score -= 20
                feedback.append("Missing axis labels.")
            if "sns.set_theme" not in code:
                feedback.append("Tip: Use sns.set_theme(style='whitegrid') for better aesthetics.")
        
        return {"agent": "Visualizer", "score": score, "feedback": feedback}

class StatisticianAgent(SpecialistAgent):
    """Validates p-values and model assumptions."""
    def review(self, plan: str, code: str, result: str) -> Dict[str, Any]:
        feedback = []
        is_relevant = "test" in plan.lower() or "stats" in plan.lower() or "model" in plan.lower()
        
        if is_relevant:
            if "p-value" not in result.lower() and "p_value" not in result.lower():
                feedback.append("Scientific Warning: Analysis mentions testing but no p-value reported.")
            if "normality" in plan.lower() and "shapiro" not in code.lower():
                feedback.append("Scientific Warning: Normality check promised in plan but missing from code.")
        
        return {"agent": "Statistician", "is_relevant": is_relevant, "feedback": feedback}

class ArchitectAgent(SpecialistAgent):
    """Ensures code follows performance and style best practices."""
    def review(self, plan: str, code: str, result: str) -> Dict[str, Any]:
        feedback = []
        if len(code.split("\n")) > 50:
            feedback.append("Performance Tip: Code block is getting long. Consider modularizing.")
        
        if "for index, row in" in code:
            feedback.append("Performance Warning: Iterative row processing detected. Use vectorized operations for speed.")
            
        return {"agent": "Architect", "feedback": feedback}

class TheCouncil:
    """Orchestrates reviews from all specialized agents."""
    def __init__(self):
        self.specialists = [
            VisualizerAgent(),
            StatisticianAgent(),
            ArchitectAgent()
        ]

    @trace_agent("TheCouncil")
    def adjudicate(self, plan: str, code: str, result: str) -> Dict[str, Any]:
        reviews = []
        for agent in self.specialists:
            reviews.append(agent.review(plan, code, result))
        
        return {
            "reviews": reviews,
            "overall_status": "Reviewed by The Council"
        }
