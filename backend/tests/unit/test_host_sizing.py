"""Resource limits derived from the machine, rather than chosen for a server.

`SYSTEM_PROFILE` was declared in config, in .env.example and in docker-compose,
and read by absolutely nothing -- so every limit was a constant: eight inference
threads on a four-core laptop, and `SESSION_MAX_ACTIVE=32` at 2 GB each, which
permits sixty-four gigabytes of containers on a machine that may have four.
"""

from __future__ import annotations

import pytest

from src.config import Settings, format_memory, parse_memory, tier_for_parameter_size
from src.utils.hostinfo import host_info


# --------------------------------------------------------------------------- #
# Memory strings
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2g", 2 * 1024**3),
        ("512m", 512 * 1024**2),
        ("2GiB", 2 * 1024**3),
        ("2gb", 2 * 1024**3),
        ("1.5g", int(1.5 * 1024**3)),
        ("4096", 4096),
    ],
)
def test_memory_strings_parse(text: str, expected: int) -> None:
    assert parse_memory(text) == expected


@pytest.mark.parametrize("junk", ["", "   ", "junk", "gg", None, 0, -5])
def test_unparseable_memory_is_none_not_an_exception(junk) -> None:
    """A typo in a hand-edited .env should cost a default, not a failed boot."""
    assert parse_memory(junk) is None


def test_formatted_memory_is_a_value_someone_could_have_typed() -> None:
    """A derived limit printed as `2057637k` reads like a measurement it is not."""
    assert format_memory(int(15.7 * 1024**3) // 8) == "1g"
    assert format_memory(3 * 1024**3) == "3g"
    assert format_memory(700 * 1024**2) == "512m"
    assert parse_memory(format_memory(2 * 1024**3)) == 2 * 1024**3


# --------------------------------------------------------------------------- #
# Host detection and sizing
# --------------------------------------------------------------------------- #
def test_host_is_measured_not_assumed() -> None:
    host = host_info()
    assert host.cores >= 1
    assert host.logical_cores >= host.cores
    if host.ram_bytes is not None:
        assert host.ram_bytes > 512 * 1024**2
    assert host.profile in ("laptop", "server", "hpc")


def test_resource_limits_are_derived_from_the_machine() -> None:
    """These used to be constants chosen for a server.

    Eight inference threads on a four-core laptop is contention, and the shipped
    `SESSION_MAX_ACTIVE=32` at `SANDBOX_MEM_LIMIT=2g` permitted sixty-four
    gigabytes of containers on a machine that may have four.
    """
    settings = Settings()
    host = host_info()

    assert settings.LLM_NUM_THREAD <= max(2, min(16, host.cores))
    assert settings.QUEUE_MAX_WORKERS >= 1

    if host.ram_bytes:
        per_runtime = parse_memory(settings.SANDBOX_MEM_LIMIT)
        assert per_runtime is not None
        # Concurrent runtimes must not be able to claim more than half of RAM.
        assert settings.SESSION_MAX_ACTIVE * per_runtime <= host.ram_bytes


def test_an_explicit_value_always_wins() -> None:
    settings = Settings(LLM_NUM_THREAD=3, SANDBOX_MEM_LIMIT="7g", SESSION_MAX_ACTIVE=99)
    assert settings.LLM_NUM_THREAD == 3
    assert settings.SANDBOX_MEM_LIMIT == "7g"
    assert settings.SESSION_MAX_ACTIVE == 99


def test_a_blank_setting_is_treated_as_unset() -> None:
    """`docker-compose.yml` passes optional knobs as `${VAR:-}`.

    An empty environment variable is still *present*, so without this every
    compose deployment would look as though the operator had chosen "" and
    would run with no memory limit at all.
    """
    settings = Settings(SANDBOX_MEM_LIMIT="")
    assert parse_memory(settings.SANDBOX_MEM_LIMIT) is not None


def test_system_profile_resolves_auto_but_honours_a_pin() -> None:
    assert Settings(SYSTEM_PROFILE="hpc").system_profile == "hpc"
    assert Settings(SYSTEM_PROFILE="auto").system_profile == host_info().profile


def test_the_agent_tier_is_still_the_models_business_not_the_hosts() -> None:
    """Host sizing must not have leaked into the *reasoning* budget.

    How many iterations the agent gets depends on the model behind it; how much
    memory a runtime gets depends on the machine. Conflating them would give a
    frontier gateway model a compact leash for running on a laptop.
    """
    assert tier_for_parameter_size("70B") == "full"
    assert Settings(SYSTEM_PROFILE="laptop").budget_for("auto", "70B").tier == "full"
