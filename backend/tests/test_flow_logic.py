import pytest
from unittest.mock import patch
import pandas as pd
import sys
import os
from types import SimpleNamespace

# Ensure backend can import its modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.agent.flow import ScientificAgent

@pytest.fixture
def mock_df():
    return pd.DataFrame({"A": [1, 2, 3]})

class TestScientificFlow:
    
    @patch("src.config.settings")
    def test_run_in_planning_mode(self, mock_settings, mock_df):
        """
        Test that running in 'planning' mode:
        1. Generates a plan.
        2. Returns 'waiting_confirmation' status.
        3. Does NOT execute code immediately.
        """
        mock_settings.MODEL_TYPE = "ollama"
        agent = ScientificAgent()

        with patch("src.core.agent.langgraph_agent.langgraph_agent.execute_workflow") as mock_execute_workflow:
            mock_execute_workflow.return_value = SimpleNamespace(
                result="Plan: Do X.",
                plan="Plan: Do X.",
                code="",
                image=None,
                thought="Thinking...",
                status="waiting_approval"
            )
            result, code, image, thought, status = agent.run("Analyze this", mock_df, mode="planning", is_confirmed_plan=False)
            
            assert status == "waiting_confirmation"
            assert thought == "Thinking..."
            assert "Plan: Do X." in result
            assert code == ""
            
    @patch("src.config.settings")
    def test_run_with_confirmed_plan(self, mock_settings, mock_df):
        """
        Test that running with 'is_confirmed_plan=True':
        1. Skips planning.
        2. Executes code.
        3. Returns 'completed'.
        """
        mock_settings.MODEL_TYPE = "ollama"
        agent = ScientificAgent()

        with patch("src.core.agent.langgraph_agent.langgraph_agent.execute_workflow") as mock_execute_workflow:
            mock_execute_workflow.return_value = SimpleNamespace(
                result="Success",
                plan="Analyze this",
                code="print('done')",
                image=None,
                thought="",
                status="completed"
            )
            result, code, image, thought, status = agent.run("Analyze this", mock_df, mode="fast", is_confirmed_plan=True)
        
        assert status == "completed"
        assert "Success" in result
        mock_execute_workflow.assert_called_once()

    @patch("src.config.settings")
    def test_manager_initialization(self, mock_settings):
        """
        Verify that ScientificAgent initializes its execution agent.
        """
        agent = ScientificAgent()
        assert agent.execution_agent is not None

