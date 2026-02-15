import pytest
from fastapi.testclient import TestClient
from src.api.api import app
from src.utils.logging import trace_agent
from unittest.mock import patch

client = TestClient(app)

def test_logging_trace_agent_exception():
    """Trigger the 'except' block in the trace_agent decorator."""
    @trace_agent("failure_agent")
    def failing_func():
        raise ValueError("Simulated Agent Failure")

    with pytest.raises(ValueError, match="Simulated Agent Failure"):
        failing_func()

def test_api_validation_error_handler():
    """Trigger the RequestValidationError handler in api.py."""
    # Send invalid type for an expected field
    response = client.post("/chat", json={"message": 123, "is_confirmed_plan": "not-a-bool"})
    assert response.status_code == 422
    assert "detail" in response.json()

def test_api_upload_exception_path():
    """Trigger the catch-all Exception block in upload_file."""
    with patch("src.api.api.validate_csv", side_effect=Exception("Internal Server Error")):
        files = {"file": ("test.csv", b"a,b\n1,2", "text/csv")}
        response = client.post("/upload", files=files)
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal Server Error"

def test_api_chat_exception_path():
    """Trigger the catch-all Exception block in chat."""
    # First, fake a dataset in state
    from src.api.api import state
    state["df"] = "not-none"
    
    with patch("src.api.api.science_agent.run", side_effect=Exception("Chat Engine Failure")):
        response = client.post("/chat", json={"message": "hello"})
        assert response.status_code == 500
        assert response.json()["detail"] == "Chat Engine Failure"
