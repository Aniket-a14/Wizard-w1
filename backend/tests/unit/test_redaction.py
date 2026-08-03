"""Schema-only prompts.

What must survive redaction is everything a model needs to *write correct code*:
column names, dtypes, null rates, shape. What must not survive is any real value.
The two are asserted separately because passing one and failing the other is the
interesting failure in both directions.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.core.prompts import create_planning_prompt, create_prompt, generate_system_context


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "customer_id": [1001, 1002, 1003, 1004],
            "region": ["Northwood", "Eastvale", "Northwood", "Southgate"],
            "revenue": [1234.56, 9876.54, 4321.0, 555.25],
            "signed_up": ["2024-01-05", "2024-02-11", "2024-03-02", "2024-04-19"],
        }
    )


def redacted(frame: pd.DataFrame) -> str:
    return generate_system_context(frame, query="revenue by region", redact=True)


def full(frame: pd.DataFrame) -> str:
    return generate_system_context(frame, query="revenue by region", redact=False)


# --------------------------------------------------------------------------- #
# What must not survive
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", ["Northwood", "Eastvale", "Southgate", "1234.56", "9876.54", "2024-01-05", "1001"])
def test_no_real_value_reaches_a_redacted_prompt(frame: pd.DataFrame, value: str) -> None:
    assert value not in redacted(frame)


def test_those_same_values_do_reach_an_unredacted_prompt(frame: pd.DataFrame) -> None:
    """Otherwise the test above would pass for the wrong reason."""
    context = full(frame)
    assert "Northwood" in context
    assert "1234.56" in context


def test_the_example_column_is_dropped_from_the_schema_table(frame: pd.DataFrame) -> None:
    assert "| example |" in full(frame)
    assert "| example |" not in redacted(frame)


def test_distinct_values_become_a_count(frame: pd.DataFrame) -> None:
    context = redacted(frame)
    assert "3 distinct values (withheld)" in context
    assert "Northwood" not in context


def test_the_numeric_summary_is_withheld(frame: pd.DataFrame) -> None:
    assert "Withheld" in redacted(frame)
    # The unredacted form carries real aggregates.
    assert "mean" in full(frame)


# --------------------------------------------------------------------------- #
# What must survive
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("column", ["customer_id", "region", "revenue", "signed_up"])
def test_every_column_name_survives(frame: pd.DataFrame, column: str) -> None:
    assert column in redacted(frame)


def test_dtypes_and_shape_survive(frame: pd.DataFrame) -> None:
    context = redacted(frame)
    assert "int64" in context
    assert "4 rows x 4 columns" in context


def test_null_rates_survive(frame: pd.DataFrame) -> None:
    assert "0.0%" in redacted(frame)


def test_the_model_is_told_values_were_withheld(frame: pd.DataFrame) -> None:
    """Without this the model reads an empty glimpse as an empty table."""
    context = redacted(frame)
    assert "withhold" in context.lower() or "withheld" in context.lower()
    assert "invent" in context.lower()


# --------------------------------------------------------------------------- #
# The flag reaches both prompt builders
# --------------------------------------------------------------------------- #
def test_the_worker_prompt_honours_redaction(frame: pd.DataFrame) -> None:
    assert "Northwood" in create_prompt("revenue by region", frame, redact=False)
    assert "Northwood" not in create_prompt("revenue by region", frame, redact=True)


def test_the_planning_prompt_honours_redaction(frame: pd.DataFrame) -> None:
    assert "Northwood" in create_planning_prompt("revenue by region", frame, redact=False)
    assert "Northwood" not in create_planning_prompt("revenue by region", frame, redact=True)


# --------------------------------------------------------------------------- #
# Chosen per role, not per turn
# --------------------------------------------------------------------------- #
def test_a_cloud_manager_and_a_local_worker_get_different_prompts(session) -> None:
    """The point of deciding redaction per prompt: under hybrid the planner can
    be cloud-bound and redacted while the code generator stays local and is not."""
    from src.core.agent.orchestrator import orchestrator

    session.data_mode = "hybrid"
    session.data_policy.schema_only = True
    session.models.manager_provider = "anthropic"
    session.models.worker_provider = "ollama"

    assert orchestrator._redact_for(session, "manager") is True
    assert orchestrator._redact_for(session, "worker") is False
