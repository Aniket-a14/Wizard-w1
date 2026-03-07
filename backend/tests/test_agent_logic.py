import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import sys
import os

# Ensure backend can import its modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.agent.agent import DataAnalysisAgent

@pytest.fixture
def mock_df():
    return pd.DataFrame({"A": [1, 2, 3]})

class TestAgentRouting:
    
    @patch("src.core.agent.agent.settings")
    def test_ollama_mode_uses_llm_for_code(self, mock_settings, mock_df):
        """
        Verify that when MODEL_TYPE is 'ollama', the agent:
        1. DOES invoke the LLM for code.
        """
        mock_settings.MODEL_TYPE = "ollama"
        
        agent = DataAnalysisAgent()
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = "```python\nprint('ollama')\n```"
        
        with patch.object(agent, "_get_llm", return_value=mock_llm), \
             patch.object(agent, "_execute_safe", return_value=("Output", "code", None)):
            
            agent.run("test instruction", mock_df)
            
            # ASSERTIONS
            mock_llm.invoke.assert_called_once()
