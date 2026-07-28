"""Deciding whether two models can be resident at once on this machine.

The agent alternates between a manager and a worker several times per question.
Two small models coexist on any laptop; two 7B models want ~14 GB, and on a
16 GB machine that also runs a browser and a Python sandbox the operating system
starts paging a model between tokens. That is not "slower", it is slower by
orders of magnitude and it takes the desktop with it.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.core.llm import resources
from src.core.llm.resources import (
    ModelFootprint,
    estimate_footprint,
    parse_parameter_size,
    plan_resident_set,
)


GB = 1024**3


@pytest.fixture
def sixteen_gb(monkeypatch):
    """A 16 GB laptop, which budgets 9.4 GB for models at the default fraction."""

    class _Host:
        ram_bytes = 16 * GB

    monkeypatch.setattr(resources, "host_info", lambda: _Host())
    return _Host()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("7.6B", 7.6), ("3.1B", 3.1), ("70b", 70.0), ("", 0.0), (None, 0.0), ("huge", 0.0)],
)
def test_parameter_sizes_are_parsed(raw, expected):
    assert parse_parameter_size(raw) == expected


def test_the_footprint_estimate_matches_a_measured_model():
    """Calibration check against a real reading, not a datasheet.

    `qwen2.5:3b` is 1,929,912,432 bytes on disk and reports 2.91 GB resident at
    an 8192-token context. If this drifts, every co-residency decision drifts
    with it, so the measurement is pinned here.
    """
    footprint = estimate_footprint("qwen2.5:3b", 1_929_912_432, "3.1B", 8192)
    assert footprint.total_gb == pytest.approx(2.91, abs=0.15)


def test_context_length_costs_memory():
    """KV cache scales with the context window, which is why num_ctx is not free."""
    small = estimate_footprint("m", 4 * GB, "7B", 4096)
    large = estimate_footprint("m", 4 * GB, "7B", 16384)
    assert large.total_bytes > small.total_bytes
    assert large.weights_bytes == small.weights_bytes  # only the context part grows


def test_a_missing_parameter_count_is_inferred_from_the_file():
    """Some installs report no parameter size; a 4-bit quant is ~0.55 GB per billion."""
    footprint = estimate_footprint("mystery", 4 * GB, "", 8192)
    assert footprint.total_bytes > 4 * GB


def test_two_small_models_stay_resident_together(sixteen_gb):
    """The common laptop case: nothing is evicted, so nothing reloads."""
    plan = plan_resident_set(
        [
            estimate_footprint("qwen2.5:3b", 1_929_912_432, "3.1B", 8192),
            estimate_footprint("qwen2.5-coder:1.5b", 986_062_089, "1.5B", 8192),
        ]
    )
    assert plan.co_resident is True
    assert plan.keep_alive == settings.LLM_KEEP_ALIVE
    assert plan.fits is True


def test_two_seven_b_models_are_swapped_rather_than_co_resident(sixteen_gb):
    """The whole point: a 7B pair must not be asked to share 16 GB with the OS.

    Each is released after it runs, costing one reload per role change -- a
    bounded cost, unlike two oversized models competing for RAM.
    """
    seven_b = lambda name: estimate_footprint(name, int(4.7 * GB), "7.6B", 8192)  # noqa: E731
    plan = plan_resident_set([seven_b("qwen2.5:7b"), seven_b("qwen2.5-coder:7b")])

    assert plan.co_resident is False
    assert plan.keep_alive == settings.LLM_KEEP_ALIVE_SWAP
    assert plan.required_gb > plan.budget_gb
    # Each one alone still fits, so this is a swap plan and not a lost cause.
    assert plan.fits is True


def test_one_model_serving_both_roles_never_swaps(sixteen_gb):
    """Same model for manager and worker: one resident copy, zero evictions."""
    same = estimate_footprint("qwen2.5:7b", int(4.7 * GB), "7.6B", 8192)
    plan = plan_resident_set([same, same])

    assert plan.co_resident is True
    assert plan.keep_alive == settings.LLM_KEEP_ALIVE
    assert len(plan.footprints) == 1


def test_a_model_too_large_for_the_machine_is_reported_as_not_fitting(sixteen_gb):
    """`fits` is false only when even one model alone exceeds the budget.

    That is a different problem from swapping, and it gets a different note: no
    scheduling choice rescues a model the machine cannot hold.
    """
    plan = plan_resident_set([estimate_footprint("llama3:70b", 40 * GB, "70B", 8192)])
    assert plan.fits is False


def test_planning_with_no_models_is_harmless():
    plan = plan_resident_set([])
    assert plan.co_resident is True
    assert plan.fits is True
    assert plan.footprints == ()


def test_the_budget_leaves_room_for_the_rest_of_the_machine(sixteen_gb):
    """Ollama does not account for the OS, this backend, or the user's browser."""
    assert resources.memory_budget_bytes() < 16 * GB


def test_an_unknown_memory_size_plans_conservatively(monkeypatch):
    """Being wrong here should cost a reload, not a swap storm."""

    class _Host:
        ram_bytes = None

    monkeypatch.setattr(resources, "host_info", lambda: _Host())
    assert 0 < resources.memory_budget_bytes() <= 8 * GB


def test_gateway_models_are_not_planned_against_local_memory():
    """A hosted model occupies somebody else's RAM; planning ours around it is wrong."""
    plan = resources.plan_for_models(["gpt-4o", "gpt-4o-mini"], "openai", 8192)
    assert plan.footprints == ()
    assert plan.co_resident is True


def test_the_plan_survives_serialisation():
    """It is rendered on /settings, so it has to cross the API boundary."""
    plan = plan_resident_set([ModelFootprint("m", 2 * GB, 1 * GB)])
    payload = plan.to_dict()
    assert payload["models"] == [{"name": "m", "gb": 3.0}]
    assert isinstance(payload["reason"], str) and payload["reason"]
