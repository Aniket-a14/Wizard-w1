from typing import Tuple, Optional
import re
from src.config import settings
from src.utils.logging import logger, trace_agent
from src.utils.cache import response_cache
from src.core.agent.agent import DataAnalysisAgent
from src.core.prompts import create_planning_prompt, create_cleaning_prompt
from src.core.tools.catalog import CatalogEngine
from src.core.tools.guardrail import GuardrailAgent
from src.core.tools.evaluator import Evaluator
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
        Returns: (Result, Code, Image, Thought, Status)
        Status: "completed" or "waiting_confirmation"
        """
        self.catalog = catalog
        logger.info("Starting Scientific Workflow", instruction=instruction, mode=mode, confirmed=is_confirmed_plan)

        thought = None
        plan = ""
        augmented_instruction = instruction

        # 1. Planning Phase
        # Skip planning if we are in "fast" mode with a confirmed plan (or just re-executing)
        # BUT: Simpler logic is:
        # If is_confirmed_plan -> The instruction IS the plan. Skip planning.
        # If NOT is_confirmed_plan -> We need to Plan.
        
        should_plan = not is_confirmed_plan

        if should_plan:
            raw_plan_response = self._create_plan(instruction, df, mode=mode)
            
            # Extract thought and plan
            thought_match = re.search(r"<thought>(.*?)</thought>", raw_plan_response, re.DOTALL)
            if thought_match:
                thought = thought_match.group(1).strip()
                plan = raw_plan_response.replace(thought_match.group(0), "").strip()
            else:
                plan = raw_plan_response
            
            logger.info("Plan created", thought_preview=thought[:50] if thought else "None")
            
            # CHECKPOINT: If mode is "planning", we stop here and ask for confirmation.
            if mode == "planning":
                return plan, "", None, thought, "waiting_confirmation"

            augmented_instruction = f"""
User Request: {instruction}

Approved Plan:
{plan}

Please execute this plan using Python.
"""
        elif is_confirmed_plan:
            # The instruction passed in IS the approved plan (plus context)
            augmented_instruction = instruction

        # 2. Execution Phase with Self-Correction
        max_retries = 2
        previous_error = None
        
        for attempt in range(max_retries + 1):
            result, code, image = self.execution_agent.run(
                augmented_instruction, 
                df, 
                previous_error=previous_error, 
                catalog=self.catalog, 
                plan=plan if not is_confirmed_plan else augmented_instruction, 
                mode=mode
            )
            
            # 3. Guardrail Check
            is_safe, reason = GuardrailAgent.scan(code)
            if not is_safe:
                logger.warning("Code blocked by guardrails", reason=reason)
                return reason, code, None, thought, "completed"

            if "Error executing code:" not in result:
                # 4. Success - Evaluate Quality
                eval_result = Evaluator.score_execution(result)
                logger.info("Execution evaluated", score=eval_result["score"], status=eval_result["status"])
                
                # 5. Adjudicate with The Council
                council_feedback = self.council.adjudicate(augmented_instruction, code, result)
                logger.info("Adjudication complete", reviewer_count=len(council_feedback["reviews"]))
                
                # Append council feedback to result for transparency
                result += "\n\n### 🛡️ The Council's Review\n"
                for review in council_feedback["reviews"]:
                    agent_name = review["agent"]
                    feedback_items = review.get("feedback", [])
                    if feedback_items:
                        result += f"- **{agent_name}**: {', '.join(feedback_items)}\n"
                    else:
                        result += f"- **{agent_name}**: ✅ No issues detected.\n"

                # Save to Memory
                working_memory.add_interaction(
                    instruction=instruction,
                    plan=plan,
                    code=code,
                    result=result,
                    meta={"catalog": self.catalog}
                )

                return result, code, image, thought, "completed"
            
            # Failure - Try to correct
            logger.warning(f"Execution failed (Attempt {attempt + 1})", error=result)
            previous_error = result
            
            if attempt == max_retries:
                logger.error("Max retries reached, returning failure.")
                return result, code, image, thought, "completed"

        return result, code, image, thought, "completed"

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
