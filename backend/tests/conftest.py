"""Shared test configuration.

Environment is pinned *before* any ``src`` import because ``src.config.Settings``
is instantiated at module import time. In particular ``SANDBOX_ENABLED=false``
guarantees the suite never contacts a Docker daemon — the previous suite started
a real container as a side effect of importing the FastAPI app, which is what
made CI depend on the runner having Docker.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="wizard-test-data-"))
TEST_WORKSPACE_DIR = Path(tempfile.mkdtemp(prefix="wizard-test-ws-"))

os.environ.update(
    {
        "ENV": "test",
        "SANDBOX_ENABLED": "false",
        "API_PROVIDER": "ollama",
        "DATA_DIR": str(TEST_DATA_DIR),
        "WORKSPACE_DIR": str(TEST_WORKSPACE_DIR),
        "LOG_DIR": str(TEST_DATA_DIR / "logs"),
        "REDIS_URL": "",
        "API_KEY": "",
        "COUNCIL_ENABLED": "false",
        "VISION_ENABLED": "false",
        "RATE_LIMIT_MAX_REQUESTS": "10000",
        # Never download a transformer during a test run: it is slow and makes
        # the suite depend on network access.
        "EMBEDDINGS_FORCE_FALLBACK": "true",
    }
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib  # noqa: E402


matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.core.database import db_mgr  # noqa: E402
from src.core.session import Session, session_manager  # noqa: E402


# --------------------------------------------------------------------------- #
# DataFrame fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def empty_df() -> pd.DataFrame:
    return pd.DataFrame()


@pytest.fixture
def simple_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "A": [1, 2, 3, 4, 5],
            "B": ["x", "y", "z", "w", "v"],
            "C": [0.1, 0.2, 0.3, 0.4, 0.5],
        }
    )


@pytest.fixture
def tips_df() -> pd.DataFrame:
    """Deterministic stand-in for the classic tips dataset."""
    rng = np.random.default_rng(0)
    size = 60
    return pd.DataFrame(
        {
            "total_bill": np.round(rng.uniform(5, 50, size), 2),
            "tip": np.round(rng.uniform(1, 10, size), 2),
            "sex": rng.choice(["Male", "Female"], size),
            "smoker": rng.choice(["Yes", "No"], size),
            "day": rng.choice(["Thur", "Fri", "Sat", "Sun"], size),
            "size": rng.integers(1, 6, size),
        }
    )


@pytest.fixture
def missing_values_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "A": [1.0, 2.0, np.nan, 4.0],
            "B": ["x", None, "z", "w"],
            "C": [np.inf, 1.0, -np.inf, 2.0],
        }
    )


@pytest.fixture
def wide_df() -> pd.DataFrame:
    """120 columns — exercises the prompt-context column budget."""
    rng = np.random.default_rng(1)
    return pd.DataFrame({f"feature_{index}": rng.normal(size=25) for index in range(120)})


# --------------------------------------------------------------------------- #
# Session fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def session() -> Session:
    """A live session, disposed afterwards so state never leaks between tests."""
    created = session_manager.create()
    yield created
    session_manager.drop(created.id)


@pytest.fixture
def loaded_session(session: Session, simple_df: pd.DataFrame) -> Session:
    session.add_dataset("dataset.csv", simple_df.copy())
    return session


@pytest.fixture(autouse=True)
def _clean_database():
    """Keeps cross-test pollution out of the shared SQLite file."""
    yield
    db_mgr.clear_cache()


@pytest.fixture
def csv_file(tmp_path: Path, simple_df: pd.DataFrame) -> Path:
    path = tmp_path / "sample.csv"
    simple_df.to_csv(path, index=False)
    return path
