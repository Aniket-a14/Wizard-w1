import pytest
import pandas as pd
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.api.api import app, state

client = TestClient(app)

def test_websocket_chat_flow():
    # Set dataframe in state
    state["df"] = pd.DataFrame({"A": [1, 2, 3]})
    state["catalog"] = {}

    with patch("src.core.agent.langgraph_agent.langgraph_agent.step_plan") as mock_plan, \
         patch("src.core.agent.langgraph_agent.langgraph_agent.step_code_generate") as mock_code_gen, \
         patch("src.core.agent.langgraph_agent.langgraph_agent.step_execute_code") as mock_exec, \
         patch("src.core.agent.langgraph_agent.langgraph_agent.step_evaluate") as mock_eval:

        # Mock step_plan to transition to executing
        def plan_side_effect(state_obj):
            state_obj.plan = "Approved plan"
            state_obj.thought = "Let's do X"
            state_obj.status = "executing"
            return state_obj
        mock_plan.side_effect = plan_side_effect

        # Mock step_code_generate
        def code_gen_side_effect(state_obj):
            state_obj.code = "print(123)"
            return state_obj
        mock_code_gen.side_effect = code_gen_side_effect

        # Mock step_execute_code to transition to evaluating
        def exec_side_effect(state_obj, callback=None):
            state_obj.result = "123"
            state_obj.status = "evaluating"
            if callback:
                # Call callback to simulate stdout streaming
                callback("Stdout message")
            return state_obj
        mock_exec.side_effect = exec_side_effect

        # Mock step_evaluate to transition to completed
        async def eval_side_effect(state_obj):
            state_obj.result = "123 (evaluated)"
            state_obj.status = "completed"
            return state_obj
        mock_eval.side_effect = eval_side_effect

        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"message": "test instruction", "mode": "standard"})
            
            # Read messages
            messages = []
            while True:
                try:
                    msg = websocket.receive_json()
                    messages.append(msg)
                    if msg["type"] == "final":
                        break
                except Exception:
                    break

            # Assert standard status transitions were broadcast
            types = [m["type"] for m in messages]
            assert "status" in types
            assert "thought" in types
            assert "code" in types
            assert "final" in types

            # Verify contents
            thought_msg = next(m for m in messages if m["type"] == "thought")
            assert thought_msg["content"] == "Let's do X"

            code_msg = next(m for m in messages if m["type"] == "code")
            assert code_msg["content"] == "print(123)"

            final_msg = next(m for m in messages if m["type"] == "final")
            assert final_msg["response"] == "123 (evaluated)"
            assert final_msg["code"] == "print(123)"

def test_websocket_chat_without_data():
    # Clear state
    state["df"] = None
    state["catalog"] = None

    with client.websocket_connect("/ws/chat") as websocket:
        websocket.send_json({"message": "Hello without dataset", "mode": "standard"})
        msg = websocket.receive_json()
        assert msg["type"] == "error"
        assert "No dataset loaded" in msg["content"]
