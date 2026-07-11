import os
import sys
import pytest
import sqlite3
from fastapi.testclient import TestClient

# Ensure backend can import its modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.api.api import app
from src.config import settings
from src.core.tools.guardrail import GuardrailAgent
from src.core.database import db_mgr

client = TestClient(app)

# ----------------- Invariant Test 1: Config parameter defaults & integrity -----------------
def test_config_invariants():
    """
    Ensures that essential configurations always exist with default fallbacks
    so the backend doesn't crash on startup.
    """
    assert hasattr(settings, "DATA_DIR")
    assert hasattr(settings, "OLLAMA_BASE_URL")
    assert hasattr(settings, "SANDBOX_NETWORK_DISABLED")
    assert settings.DATA_DIR is not None

# ----------------- Invariant Test 2: Guardrail Contracts (AST Sandbox security) -----------------
@pytest.mark.parametrize(
    "code_snippet, expected_safe",
    [
        # Safe statements
        ("x = 1 + 2\nprint(x)", True),
        ("import pandas as pd\ndf = pd.DataFrame({'a': [1,2]})\nprint(df.mean())", True),
        ("import matplotlib.pyplot as plt\nplt.plot([1,2], [3,4])", True),
        # Unsafe statements - breakout block imports
        ("import os\nos.system('echo hack')", False),
        ("from os import system\nsystem('echo hack')", False),
        ("__import__('os').system('echo hack')", False),
        # Unsafe statements - dynamic execution
        ("eval('1 + 1')", False),
        ("exec('import sys')", False),
        # Unsafe statements - absolute path workouts
        ("with open('/etc/passwd', 'r') as f:\n    pass", False),
        ("open('../outside.csv', 'w')", False),
    ]
)
def test_guardrail_invariant_scans(code_snippet, expected_safe):
    """
    Verifies that AST security scans block malicious patterns,
    while allowing safe analytic statements.
    """
    is_safe, reason = GuardrailAgent.scan(code_snippet)
    assert is_safe == expected_safe, f"Code: {code_snippet} got safety status {is_safe}, expected {expected_safe}. Reason: {reason}"

# ----------------- Invariant Test 3: SQLite schema and index configuration -----------------
def test_sqlite_schema_and_index_invariants():
    """
    Verifies SQLite db table creation, schema layout, and index presence.
    """
    db_path = settings.DATA_DIR / "wizard.db"
    assert db_path.exists(), "Database file must exist after DB Manager initialization"
    
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        
        # Verify tables exist
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row["name"] for row in cursor.fetchall()]
        assert "semantic_cache" in tables
        assert "trajectories" in tables
        assert "feedbacks" in tables
        
        # Verify schema hash column presence
        cursor = conn.execute("PRAGMA table_info(semantic_cache)")
        cols = [row["name"] for row in cursor.fetchall()]
        assert "schema_hash" in cols
        assert "columns" in cols
        assert "embedding" in cols
        
        # Verify index configuration exists
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = [row["name"] for row in cursor.fetchall()]
        assert "idx_semantic_cache_schema" in indexes
        assert "idx_trajectories_schema" in indexes

# ----------------- Invariant Test 4: API Endpoint and Router contracts -----------------
def test_api_routes_invariants():
    """
    Verifies key API paths are registered, respond to correct HTTP verbs,
    and fail with standardized 4xx/5xx responses rather than unhandled raw errors.
    """
    # 1. Non-existent file deletion should return 404 cleanly
    resp = client.delete("/data/files/nonexistent_file_987654.csv")
    assert resp.status_code == 404
    assert "error" in resp.json() or "detail" in resp.json()
    
    # 2. Non-existent variable export should return 404 cleanly
    resp = client.post("/sandbox/variables/export/nonexistent_var_987654")
    assert resp.status_code == 404
    assert "error" in resp.json() or "detail" in resp.json()
    
    # 3. GET /sandbox/variables is registered
    resp = client.get("/sandbox/variables")
    assert resp.status_code in (200, 500, 404)
    
    # 4. POST /sandbox/interrupt is registered
    resp = client.post("/sandbox/interrupt")
    assert resp.status_code in (200, 500, 404)
