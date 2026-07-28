"""Deciding what will actually fit in this machine's memory before asking for it.

The agent alternates between two models -- a manager that reasons and a worker
that writes code -- several times per question. Whether that is cheap or ruinous
depends entirely on whether both fit in RAM at once, and *nothing in the app
knew*. Two 1.5B models coexist happily on any laptop. Two 7B models want around
fourteen gigabytes, and on a sixteen-gigabyte machine that is also running a
browser, the backend and a Python sandbox, the operating system starts swapping.
A model being paged to disk between tokens is not slow in the way a small model
is slow; it is slower by one to two orders of magnitude, and it takes the rest
of the desktop down with it.

The lever we have
-----------------
Only two things reach the model server per request: ``num_ctx`` and
``keep_alive``. ``OLLAMA_MAX_LOADED_MODELS`` would be the direct control, but it
belongs to the server process, not the client, so it is out of reach here.

That is enough. When both models fit, both are told to stay resident for a long
time, because the alternation means an eviction between them costs a reload from
disk every iteration. When they do not fit, the model that just ran is told to
release itself promptly, so its memory is gone before the other one needs it:
one deliberate reload per role change, instead of the machine deciding under
pressure. Swapping on purpose is a bounded cost; thrashing is not.

Calibration
-----------
``estimate_footprint`` is fitted to a measurement rather than a datasheet. On
this machine ``qwen2.5:3b`` -- 1.93 GB of weights on disk, 3.1B parameters --
reported 2.91 GB resident at an 8192-token context, so roughly 40 MB of KV cache
and compute buffers per billion parameters per 1024 tokens of context. Extended
to a 7B at 8192 that predicts ~7.1 GB against a real ~6.5 GB, which is the
direction to be wrong in: the estimate decides whether to co-locate, and
over-estimating costs one reload while under-estimating costs a swap storm.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import settings
from src.utils.hostinfo import host_info
from src.utils.logging import logger


#: Bytes of KV cache and compute buffer per billion parameters per 1024 tokens
#: of context. Measured, see the module docstring.
OVERHEAD_PER_B_PARAM_PER_1K_CTX = 40 * 1024**2

#: Weights in memory run slightly above the file on disk.
WEIGHT_INFLATION = 1.05

#: Share of total RAM the model server may be planned against. The rest is the
#: operating system, this backend, the sandbox subprocess and the user's actual
#: desktop -- all of which exist, and none of which Ollama accounts for when it
#: decides it can fit another model.
DEFAULT_MEMORY_FRACTION = 0.60

#: Assumed size when a provider reports none. Gateways report nothing and are
#: not resident on this machine at all, so they are excluded before this is
#: reached; it only covers a local model with missing metadata.
ASSUMED_PARAMS_B = 7.0


def parse_parameter_size(parameter_size: str | None) -> float:
    """``"7.6B"`` -> ``7.6``. Returns ``0.0`` when there is nothing to parse."""
    if not parameter_size:
        return 0.0
    cleaned = str(parameter_size).strip().upper().rstrip("B")
    try:
        value = float(cleaned)
    except ValueError:
        return 0.0
    return max(0.0, value)


@dataclass(frozen=True)
class ModelFootprint:
    """What one model is expected to occupy while it is loaded."""

    name: str
    weights_bytes: int
    overhead_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.weights_bytes + self.overhead_bytes

    @property
    def total_gb(self) -> float:
        return self.total_bytes / 1024**3


def estimate_footprint(
    name: str,
    size_bytes: int,
    parameter_size: str | None,
    num_ctx: int,
) -> ModelFootprint:
    """Resident memory for ``name`` at ``num_ctx``, weights plus context."""
    params_b = parse_parameter_size(parameter_size)
    if params_b <= 0:
        # Infer from the file when the provider did not say: a 4-bit quant runs
        # about half a byte per parameter.
        params_b = (size_bytes / (0.55 * 1024**3)) if size_bytes > 0 else ASSUMED_PARAMS_B
    weights = int(size_bytes * WEIGHT_INFLATION) if size_bytes > 0 else int(params_b * 0.55 * 1024**3)
    overhead = int(params_b * (max(num_ctx, 1) / 1024) * OVERHEAD_PER_B_PARAM_PER_1K_CTX)
    return ModelFootprint(name=name, weights_bytes=weights, overhead_bytes=overhead)


@dataclass(frozen=True)
class ResidentPlan:
    """How to run a set of models on this machine without overcommitting it."""

    co_resident: bool
    keep_alive: str
    budget_bytes: int
    required_bytes: int
    footprints: tuple[ModelFootprint, ...]
    reason: str

    @property
    def budget_gb(self) -> float:
        return self.budget_bytes / 1024**3

    @property
    def required_gb(self) -> float:
        return self.required_bytes / 1024**3

    @property
    def fits(self) -> bool:
        """Whether even one model at a time fits. False means expect swapping to disk."""
        if not self.footprints:
            return True
        return max(fp.total_bytes for fp in self.footprints) <= self.budget_bytes

    def to_dict(self) -> dict:
        return {
            "co_resident": self.co_resident,
            "keep_alive": self.keep_alive,
            "budget_gb": round(self.budget_gb, 1),
            "required_gb": round(self.required_gb, 1),
            "fits": self.fits,
            "reason": self.reason,
            "models": [{"name": fp.name, "gb": round(fp.total_gb, 1)} for fp in self.footprints],
        }


def memory_budget_bytes() -> int:
    """How much RAM the model server may be planned against on this host."""
    ram = host_info().ram_bytes
    if not ram:
        # Unknown memory: plan for the smaller common laptop rather than assume
        # room that may not exist. Being wrong here costs a reload, not a stall.
        ram = 8 * 1024**3
    fraction = settings.MODEL_MEMORY_FRACTION or DEFAULT_MEMORY_FRACTION
    return int(ram * min(max(fraction, 0.1), 0.95))


def plan_resident_set(footprints: list[ModelFootprint]) -> ResidentPlan:
    """Decides whether ``footprints`` can be resident together, and for how long.

    A single model, or none, is always "co-resident" -- there is nothing to
    alternate with, so it should stay loaded as long as possible.
    """
    budget = memory_budget_bytes()
    unique = {fp.name: fp for fp in footprints}
    distinct = tuple(unique.values())
    required = sum(fp.total_bytes for fp in distinct)

    if len(distinct) <= 1:
        return ResidentPlan(
            co_resident=True,
            keep_alive=settings.LLM_KEEP_ALIVE,
            budget_bytes=budget,
            required_bytes=required,
            footprints=distinct,
            reason="one model serves every role, so nothing is ever evicted",
        )

    if required <= budget:
        return ResidentPlan(
            co_resident=True,
            keep_alive=settings.LLM_KEEP_ALIVE,
            budget_bytes=budget,
            required_bytes=required,
            footprints=distinct,
            reason=f"{required / 1024**3:.1f} GB of models fits the {budget / 1024**3:.1f} GB budget",
        )

    return ResidentPlan(
        co_resident=False,
        keep_alive=settings.LLM_KEEP_ALIVE_SWAP,
        budget_bytes=budget,
        required_bytes=required,
        footprints=distinct,
        reason=(
            f"{required / 1024**3:.1f} GB of models exceeds the {budget / 1024**3:.1f} GB budget, "
            f"so each is released after use instead of competing for memory"
        ),
    )


def plan_for_models(names: list[str], provider: str, num_ctx: int) -> ResidentPlan:
    """Builds a plan for ``names`` on ``provider``, measuring them via the registry.

    Only locally-hosted models count. A gateway model occupies memory on somebody
    else's machine, and planning this laptop's RAM around it would answer the
    wrong question entirely.
    """
    wanted = [name for name in dict.fromkeys(names) if name]
    if not wanted or provider not in LOCAL_PROVIDERS:
        return plan_resident_set([])

    try:
        from src.core.llm.registry import model_registry

        installed = {model.name: model for model in model_registry.list_models(provider=provider)}
    except Exception as exc:  # pragma: no cover - discovery is best effort
        logger.warning("Could not measure models for memory planning", error=str(exc))
        return plan_resident_set([])

    footprints = []
    for name in wanted:
        info = installed.get(name) or installed.get(f"{name}:latest")
        if info is None:
            continue
        footprints.append(
            estimate_footprint(
                name=name,
                size_bytes=info.size_bytes,
                parameter_size=info.parameter_size,
                num_ctx=num_ctx,
            )
        )
    return plan_resident_set(footprints)


#: Providers whose models occupy *this* machine's memory.
LOCAL_PROVIDERS = frozenset({"ollama", "lmstudio"})


__all__ = [
    "LOCAL_PROVIDERS",
    "ModelFootprint",
    "ResidentPlan",
    "estimate_footprint",
    "memory_budget_bytes",
    "parse_parameter_size",
    "plan_for_models",
    "plan_resident_set",
]
