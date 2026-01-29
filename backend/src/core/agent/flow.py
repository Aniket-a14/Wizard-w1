from typing import Tuple, Optional
from ...config import settings
from ...utils.logging import logger
from ...utils.cache import response_cache
from .agent import DataAnalysisAgent
from ..prompts import create_planning_prompt
import pandas as pd

class ScientificAgent:
    """
    Orchestrates the Planning -> Execution -> Critique loop.
    "Level 100" Data Scientist behavior.
    """
    def __init__(self):
        self.execution_agent = DataAnalysisAgent()
        
    def run(self, instruction: str, df: pd.DataFrame) -> Tuple[str, str, Optional[str]]:
        logger.info("Starting Scientific Workflow", instruction=instruction)
        
        # 1. Planning Phase
        # We only do this if we have a strong model (Ollama/Hybrid)
        if settings.MODEL_TYPE in ['ollama', 'hybrid']:
            plan = self._create_plan(instruction, df)
            logger.info("Plan created", plan=plan)
            
            # Augment instruction with plan
            augmented_instruction = f"""
User Request: {instruction}

Approved Plan:
{plan}

Please execute this plan using Python.
"""
        else:
            augmented_instruction = instruction
            
        # 2. Execution Phase
        # We delegate the actual coding/running to the base agent
        result, code, image = self.execution_agent.run(augmented_instruction, df)
        
        # 3. Critique/Evaluation Phase (Optional for now)
        # Could feed 'result' back to LLM to ask "Does this answer the question?"
        
        return result, code, image

    def _create_plan(self, instruction: str, df: pd.DataFrame) -> str:
        """Generates a high-level analysis plan."""
        # Check Cache
        cache_key = response_cache.generate_key(instruction, str(df.columns.tolist()), str(df.shape))
        cached_plan = response_cache.get(cache_key)
        if cached_plan:
            logger.info("Plan retrieved from cache")
            return cached_plan
            
        llm = self.execution_agent._get_llm() # Reuse connection
        if not llm:
            return "Proceed directly."
            
        try:
            prompt = create_planning_prompt(instruction, df)
            response = llm.invoke(prompt)
            plan = response.content
            
            # Cache Result
            response_cache.set(cache_key, plan)
            return plan
        except Exception as e:
            logger.warning("Planning failed, skipping", error=str(e))
            return "Proceed with analysis."

# Singleton for the higher-level agent
science_agent = ScientificAgent()
