import pandas as pd

from src.core.agent.agent import DataAnalysisAgent
from src.core.prompts import create_cleaning_prompt
from src.core.tools.catalog import CatalogEngine
from src.utils.logging import logger, trace_agent


class ScientificAgent:
    """
    Orchestrates the Planning -> Execution -> Critique loop.
    "Level 100" Data Scientist behavior.
    """

    def __init__(self):
        self.execution_agent = DataAnalysisAgent()
        self.catalog = None

    @trace_agent("ScientificAgent")
    def run(
        self,
        instruction: str,
        df: pd.DataFrame,
        mode: str = "planning",
        is_confirmed_plan: bool = False,
        catalog: dict = None,
    ) -> tuple[str, str, str | None, str | None, str]:
        """
        Adapts the original interface to call the new LangGraph-based workflow.
        Returns: (Result, Code, Image, Thought, Status)
        """
        from src.core.agent.langgraph_agent import WorkflowState, langgraph_agent

        # Initialize workflow state
        state = WorkflowState(instruction, df, mode=mode, catalog=catalog)

        if is_confirmed_plan:
            # The instruction passed in is the approved plan
            state.plan = instruction
            state.status = "executing"
        else:
            state.status = "init"

        import asyncio

        final_state = asyncio.run(langgraph_agent.execute_workflow(state))

        # Map statuses
        ui_status = "completed"
        if final_state.status == "waiting_approval":
            ui_status = "waiting_confirmation"

        return (
            final_state.result or final_state.plan,
            final_state.code,
            final_state.image,
            final_state.thought,
            ui_status,
        )

    def clean_dataset(self, df: pd.DataFrame) -> tuple[pd.DataFrame, dict, str]:
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

        # 3. Apply the generated cleaning code to produce the cleaned DataFrame
        if code and code.strip():
            try:
                import matplotlib.pyplot as plt
                import numpy as np
                import seaborn as sns

                exec_globals = {"pd": pd, "np": np, "plt": plt, "sns": sns, "df": df.copy()}
                exec(code, exec_globals)
                cleaned_df = exec_globals.get("df", df)
                if isinstance(cleaned_df, pd.DataFrame) and not cleaned_df.empty:
                    logger.info("Dataset cleaned successfully", original_shape=df.shape, cleaned_shape=cleaned_df.shape)
                    return cleaned_df, catalog, result
                else:
                    logger.warning("Cleaning code did not produce a valid DataFrame, using original")
                    return df, catalog, result
            except Exception as e:
                logger.warning("Failed to apply cleaning code locally, using original", error=str(e))
                return df, catalog, result

        logger.info("No cleaning code generated, using original data")
        return df, catalog, result


# Singleton for the higher-level agent
science_agent = ScientificAgent()
