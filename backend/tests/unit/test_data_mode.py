"""The data-mode boundary.

The claim under test is narrow and load-bearing: under ``local-only`` no cloud
provider can be reached, by any route, including one a session pinned to a role
itself. Everything else here supports that.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.core.data_mode import (
    DataPolicy,
    allowed_providers,
    allows_provider,
    check_provider,
    disabled_tools,
    normalize,
    should_redact,
    tool_allowed,
)
from src.core.llm import LLMRole, llm_provider
from src.core.llm.provider import DataModeViolation
from src.providers import CLOUD_PROVIDERS, LOCAL_PROVIDERS


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("provider", sorted(CLOUD_PROVIDERS))
def test_local_only_refuses_every_cloud_provider(provider: str) -> None:
    assert not allows_provider("local-only", provider)


@pytest.mark.parametrize("provider", sorted(LOCAL_PROVIDERS))
def test_local_only_allows_every_local_provider(provider: str) -> None:
    assert allows_provider("local-only", provider)


@pytest.mark.parametrize("provider", sorted(LOCAL_PROVIDERS))
def test_cloud_only_refuses_every_local_provider(provider: str) -> None:
    assert not allows_provider("cloud-only", provider)


def test_hybrid_allows_both() -> None:
    assert allowed_providers("hybrid") == LOCAL_PROVIDERS | CLOUD_PROVIDERS


def test_an_unknown_provider_counts_as_cloud() -> None:
    """The safe direction: treating something unrecognised as local would open
    exactly the hole the check exists to close."""
    assert not allows_provider("local-only", "some-new-backend")


def test_the_refusal_names_the_mode_the_role_and_the_provider() -> None:
    message = check_provider("local-only", "anthropic", "manager")
    assert message is not None
    assert "local-only" in message
    assert "manager" in message
    assert "Anthropic" in message


def test_an_empty_mode_falls_back_to_the_configured_default() -> None:
    assert normalize("") == settings.data_mode
    assert normalize("not-a-mode") == settings.data_mode


# --------------------------------------------------------------------------- #
# Enforcement in the one place every call passes through
# --------------------------------------------------------------------------- #
def test_resolution_refuses_a_cloud_provider_under_local_only() -> None:
    with pytest.raises(DataModeViolation):
        llm_provider.resolve(LLMRole.MANAGER, model="claude-sonnet-4-5", provider="anthropic", data_mode="local-only")


def test_resolution_refuses_a_local_provider_under_cloud_only() -> None:
    with pytest.raises(DataModeViolation):
        llm_provider.resolve(LLMRole.WORKER, model="qwen2.5-coder", provider="ollama", data_mode="cloud-only")


def test_resolution_allows_the_matching_kind() -> None:
    spec = llm_provider.resolve(LLMRole.MANAGER, model="claude-sonnet-4-5", provider="anthropic", data_mode="hybrid")
    assert spec.provider == "anthropic"
    assert spec.api_style == "anthropic"


async def test_no_cloud_client_is_ever_built_under_local_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """The milestone's core claim, asserted at the point a request would be made.

    A session pinning a cloud provider to a role must not be able to route around
    the mode -- which is why the check lives in `resolve` and not in the caller.
    """
    built: list[str] = []
    monkeypatch.setattr(llm_provider, "_build_client", lambda spec: built.append(spec.provider), raising=True)

    for provider in sorted(CLOUD_PROVIDERS):
        with pytest.raises(DataModeViolation):
            await llm_provider.acomplete("hello", provider=provider, data_mode="local-only")

    assert built == []


# --------------------------------------------------------------------------- #
# Tools that call out on their own
# --------------------------------------------------------------------------- #
def test_web_search_is_unavailable_under_local_only() -> None:
    assert not tool_allowed("local-only", "web_search")


@pytest.mark.parametrize("mode", ["hybrid", "cloud-only"])
def test_web_search_is_available_under_the_other_modes(mode: str) -> None:
    assert tool_allowed(mode, "web_search")


def test_a_tool_that_stays_local_is_never_gated() -> None:
    assert tool_allowed("local-only", "inspect")


# --------------------------------------------------------------------------- #
# Redaction decision
# --------------------------------------------------------------------------- #
def test_a_local_bound_prompt_is_never_redacted() -> None:
    """Even with schema-only on: nothing is being protected from this machine."""
    assert not should_redact("hybrid", DataPolicy(schema_only=True), "ollama")


def test_a_cloud_bound_prompt_is_redacted_by_default() -> None:
    assert should_redact("hybrid", DataPolicy(), "anthropic")


def test_schema_only_can_be_turned_off_per_session() -> None:
    assert not should_redact("hybrid", DataPolicy(schema_only=False), "anthropic")


def test_a_per_dataset_override_wins_over_the_session_default() -> None:
    policy = DataPolicy(schema_only=False, per_dataset={"payroll.csv": True})
    assert should_redact("hybrid", policy, "openai", dataset="payroll.csv")
    assert not should_redact("hybrid", policy, "openai", dataset="public.csv")


# --------------------------------------------------------------------------- #
# Per-source policy
# --------------------------------------------------------------------------- #
def test_an_override_is_dropped_with_its_dataset() -> None:
    """Otherwise re-uploading a file of the same name inherits a policy set for
    a different one, which is the wrong direction to be wrong in."""
    policy = DataPolicy(schema_only=False)
    policy.set_for("payroll.csv", True)
    policy.forget("payroll.csv")
    assert not policy.schema_only_for("payroll.csv")


def test_clearing_an_override_returns_to_the_session_default() -> None:
    policy = DataPolicy(schema_only=True)
    policy.set_for("public.csv", False)
    assert not policy.schema_only_for("public.csv")

    assert policy.clear_for("public.csv")
    assert policy.schema_only_for("public.csv")
    assert not policy.clear_for("public.csv")


def test_changing_the_session_default_moves_datasets_that_follow_it() -> None:
    """ "Follow default" is a real third state, not a copy of the current value."""
    policy = DataPolicy(schema_only=True)
    policy.set_for("pinned.csv", False)

    policy.schema_only = False
    assert not policy.schema_only_for("following.csv")
    assert not policy.schema_only_for("pinned.csv")

    policy.schema_only = True
    assert policy.schema_only_for("following.csv")
    assert not policy.schema_only_for("pinned.csv"), "an explicit override must not track the default"


def test_disabled_tools_are_named_per_mode() -> None:
    assert disabled_tools("local-only") == ["web_search"]
    assert disabled_tools("hybrid") == []
    assert disabled_tools("cloud-only") == []


def test_the_active_dataset_decides_redaction(session) -> None:
    """The orchestrator asks per prompt using the session's active table, so a
    table marked more sensitive than the default is treated that way."""
    import pandas as pd

    from src.core.agent.orchestrator import orchestrator

    session.data_mode = "hybrid"
    session.data_policy.schema_only = False
    session.models.manager_provider = "anthropic"
    session.add_dataset("payroll.csv", pd.DataFrame({"salary": [1, 2]}))

    assert orchestrator._redact_for(session, "manager") is False

    session.data_policy.set_for("payroll.csv", True)
    assert orchestrator._redact_for(session, "manager") is True
