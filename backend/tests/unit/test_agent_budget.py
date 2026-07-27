"""Tier sizing: how one codebase serves a 1.5B local model and a frontier one.

Every loop iteration costs a manager round-trip. A large model earns a long
leash; a small one wanders, so it gets a short budget, a smaller action menu and
deterministic fallbacks. These tests pin the boundaries, because getting them
wrong is invisible until someone's laptop spends four minutes on one question.
"""

from __future__ import annotations

import pytest

from src.config import TIER_BUDGETS, Settings, settings, tier_for_parameter_size


# --------------------------------------------------------------------------- #
# Inferring a tier from the model
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "parameter_size,tier",
    [
        ("1.5B", "compact"),
        ("0.5B", "compact"),
        ("3B", "compact"),
        ("3.8B", "compact"),
        ("7B", "balanced"),
        ("8B", "balanced"),
        ("14B", "balanced"),
        ("27B", "balanced"),
        ("30B", "full"),
        ("70B", "full"),
        ("405B", "full"),
    ],
)
def test_parameter_count_selects_the_tier(parameter_size: str, tier: str) -> None:
    assert tier_for_parameter_size(parameter_size) == tier


@pytest.mark.parametrize("reported", [None, "", "unknown", "large", "N/A", "0B", "-3B"])
def test_an_unreadable_size_falls_back_to_the_middle_tier(reported: str | None) -> None:
    """Hosted gateways report no parameter count, and they are not small.

    Guessing `compact` for them would cripple the strongest models available;
    guessing `full` would set a 24-iteration budget on an unknown model.
    """
    assert tier_for_parameter_size(reported) == "balanced"


def test_a_lowercase_or_spaced_size_is_still_read() -> None:
    assert tier_for_parameter_size(" 7b ") == "balanced"
    assert tier_for_parameter_size("70b") == "full"


# --------------------------------------------------------------------------- #
# Budgets
# --------------------------------------------------------------------------- #
def test_every_tier_is_defined_and_names_itself() -> None:
    for name, budget in TIER_BUDGETS.items():
        assert budget.tier == name, "a budget must know which tier it came from"


def test_budgets_increase_monotonically_with_tier() -> None:
    compact, balanced, full = (TIER_BUDGETS[name] for name in ("compact", "balanced", "full"))

    assert compact.iterations < balanced.iterations < full.iterations
    assert compact.deep_iterations < balanced.deep_iterations < full.deep_iterations
    assert compact.max_columns < balanced.max_columns < full.max_columns
    assert compact.observation_chars < balanced.observation_chars < full.observation_chars


def test_the_compact_tier_withholds_the_expensive_actions() -> None:
    """A 1.5B model spends a reflection iteration restating the question."""
    compact = TIER_BUDGETS["compact"]
    assert not compact.allow_reflection
    assert not compact.allow_verification


def test_fast_mode_is_one_iteration_with_nothing_extra() -> None:
    """Fast means fast. Verification is the most expensive thing a turn can do —
    a second code generation *and* a second execution — so asking for `fast`
    must not silently pay for it."""
    budget = settings.budget_for("fast", "70B")

    assert budget.iterations == 1
    assert not budget.allow_verification
    assert not budget.allow_reflection


def test_deep_mode_uses_the_deep_allowance() -> None:
    assert settings.budget_for("deep", "7B").iterations == TIER_BUDGETS["balanced"].deep_iterations
    assert settings.budget_for("auto", "7B").iterations == TIER_BUDGETS["balanced"].iterations


def test_the_hard_ceiling_outranks_the_tier() -> None:
    """A runaway loop on a paid gateway is a billing incident, so the ceiling
    is deliberately not derived from the tier."""
    capped = Settings(AGENT_MAX_ITERATIONS=3)
    assert capped.budget_for("deep", "405B").iterations == 3


def test_observation_size_is_also_capped_by_configuration() -> None:
    capped = Settings(AGENT_OBSERVATION_CHARS=500)
    assert capped.budget_for("deep", "405B").observation_chars == 500


def test_an_explicit_tier_overrides_inference() -> None:
    """Someone who has measured their own setup outranks the heuristic."""
    pinned = Settings(AGENT_TIER="full")
    assert pinned.resolve_tier("1.5B") == "full"
    assert pinned.budget_for("auto", "1.5B").tier == "full"


def test_auto_defers_to_the_model() -> None:
    auto = Settings(AGENT_TIER="auto")
    assert auto.resolve_tier("1.5B") == "compact"
    assert auto.resolve_tier("70B") == "full"


@pytest.mark.parametrize("mode", ["auto", "fast", "deep", "planning", "anything-else"])
def test_every_mode_yields_a_usable_budget(mode: str) -> None:
    """A mode that reached this far unrecognised must not produce a zero budget
    — that would be a run that answers without ever executing anything."""
    budget = settings.budget_for(mode, "7B")
    assert budget.iterations >= 1
    assert budget.max_columns > 0
