from typing import Tuple, Optional
from src.utils.logging import logger, trace_agent
from src.utils.cache import response_cache
from src.core.agent.agent import DataAnalysisAgent
from src.core.prompts import create_planning_prompt, create_cleaning_prompt
from src.core.tools.catalog import CatalogEngine
from src.core.agent.council import TheCouncil
from src.core.memory import working_memory
import pandas as pd


class ScientificAgent:
    """
    Orchestrates the Planning -> Execution -> Critique loop.
    "Level 100" Data Scientist behavior.
    """

    def __init__(self):
        self.execution_agent = DataAnalysisAgent()
        self.council = TheCouncil()
        self.catalog = None


    @trace_agent("ScientificAgent")
    def run(self, instruction: str, df: pd.DataFrame, mode: str = "planning", is_confirmed_plan: bool = False, catalog: dict = None) -> Tuple[str, str, Optional[str], Optional[str], str]:
        """
        Adapts the original interface to call the new LangGraph-based workflow.
        Returns: (Result, Code, Image, Thought, Status)
        """
        from src.core.agent.langgraph_agent import langgraph_agent, WorkflowState
        
        # Initialize workflow state
        state = WorkflowState(instruction, df, mode=mode, catalog=catalog)
        
        if is_confirmed_plan:
            # The instruction passed in is the approved plan
            state.plan = instruction
            state.status = "executing"
        else:
            state.status = "init"
            
        final_state = langgraph_agent.execute_workflow(state)
        
        # Map statuses
        ui_status = "completed"
        if final_state.status == "waiting_approval":
            ui_status = "waiting_confirmation"
            
        return final_state.result or final_state.plan, final_state.code, final_state.image, final_state.thought, ui_status

    def clean_dataset(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, dict, str]:
        """
        New Stage: Semantic Cleaning.
        Uses the CatalogEngine to detect issues and the Agent to fix them.
        Returns: (Cleaned DF, Catalog, Cleaning Summary)
        """
        logger.info("Starting Semantic Cleaning Stage")
        
        # 1. Analyze
        catalog = CatalogEngine.analyze(df)
        
        # 2. Clean
        prompt = create_cleaning_prompt(df, catalog)
        result, code, _ = self.execution_agent.run(prompt, df)
        
        if "Error executing code:" in result:
            logger.warning("Cleaning failed, proceeding with raw data", error=result)
            return df, catalog, "No changes applied due to error."
        
        # The result of the agent execution is effectively the 'cleaning summary' 
        # (prints or text returned by the execution agent)
        logger.info("Dataset cleaned successfully")
        return df, catalog, result

    def _create_plan(self, instruction: str, df: pd.DataFrame, mode: str = "standard") -> str:
        """Generates a high-level analysis plan (including thoughts)."""
        # Retrieve Context from Memory
        memory_context = working_memory.get_context_string(instruction)
        
        # Check Cache
        cache_key = response_cache.generate_key(
            instruction, str(df.columns.tolist()), str(df.shape), mode
        )
        cached_plan = response_cache.get(cache_key)
        if cached_plan:
            logger.info("Plan retrieved from cache")
            return cached_plan

        llm = self.execution_agent._get_llm()
        if not llm:
            return "Proceed directly."

        try:
            prompt = create_planning_prompt(instruction, df, catalog=self.catalog, mode=mode, memory_context=memory_context)
            
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
