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
    def test_hybrid_mode_uses_local_model_for_code(self, mock_settings, mock_df):
        """
        Verify that when MODEL_TYPE is 'hybrid', the agent:
        1. Does NOT invoke the LLM for code.
        2. DOES invoke the Local Generator.
        """
        mock_settings.MODEL_TYPE = "hybrid"
        mock_settings.MODEL_NAME = "deepseek-r1"
        
        agent = DataAnalysisAgent()
        
        # Mock LLM and Local Generator
        mock_llm = MagicMock()
        mock_local_gen = MagicMock()
        
        # Setup mocks
        agent.llm = mock_llm
        agent.local_generator = mock_local_gen
        
        # Setup local generator return value
        # It returns a list of dicts: [{'generated_text': '... code ...'}]
        mock_local_gen.return_value = [{"generated_text": "Code:\n```python\nprint('hello')\n```"}]
        
        # Mock internal methods to avoid side effects
        with patch.object(agent, "_get_llm", return_value=mock_llm), \
             patch.object(agent, "_get_local_generator", return_value=mock_local_gen), \
             patch.object(agent, "_execute_safe", return_value=("Output", "code", None)):
            
            agent.run("test instruction", mock_df)
            
            # ASSERTIONS
            
            # 1. LLM should NOT be invoked for hybrid mode code generation
            mock_llm.invoke.assert_not_called()
            
            # 2. Local Generator SHOULD be invoked
            mock_local_gen.assert_called_once()
            
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
