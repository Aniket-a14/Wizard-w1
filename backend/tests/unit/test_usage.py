"""Token accounting and cost.

The rule these protect: a cost figure is reported when it is knowable and absent
when it is not. A fabricated dollar amount is worse than no dollar amount, which
is the grounding layer's philosophy applied to the meter.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.llm.usage import (
    SessionUsage,
    TokenUsage,
    UsageLedger,
    extract_usage,
    price_for,
)


# --------------------------------------------------------------------------- #
# Extraction — three shapes, because the installed client versions differ
# --------------------------------------------------------------------------- #
def test_usage_metadata_is_read_when_present() -> None:
    response = SimpleNamespace(usage_metadata={"input_tokens": 120, "output_tokens": 34})
    usage = extract_usage(response)
    assert (usage.input_tokens, usage.output_tokens, usage.exact) == (120, 34, True)


def test_openai_style_token_usage_is_read() -> None:
    response = SimpleNamespace(response_metadata={"token_usage": {"prompt_tokens": 80, "completion_tokens": 12}})
    usage = extract_usage(response)
    assert (usage.input_tokens, usage.output_tokens, usage.exact) == (80, 12, True)


def test_ollama_eval_counts_are_read() -> None:
    response = SimpleNamespace(response_metadata={"prompt_eval_count": 200, "eval_count": 45})
    usage = extract_usage(response)
    assert (usage.input_tokens, usage.output_tokens, usage.exact) == (200, 45, True)


def test_a_response_reporting_nothing_is_estimated_and_says_so() -> None:
    usage = extract_usage(None, prompt="a" * 400, text="b" * 40)
    assert usage.input_tokens == 100
    assert usage.output_tokens == 10
    assert usage.exact is False


# --------------------------------------------------------------------------- #
# Pricing
# --------------------------------------------------------------------------- #
def test_a_versioned_model_id_matches_its_price() -> None:
    assert price_for("claude-sonnet-4-5-20250929") == (3.0, 15.0)


def test_an_unpriced_model_has_no_price() -> None:
    assert price_for("qwen2.5-coder:7b") is None
    assert price_for("") is None


def test_a_local_model_is_never_costed() -> None:
    usage = SessionUsage()
    usage.add("ollama", "qwen3:8b", "manager", TokenUsage(1000, 500))
    assert usage.to_dict()["cost_usd"] is None
    assert usage.to_dict()["any_cloud"] is False


def test_a_priced_cloud_model_is_costed() -> None:
    usage = SessionUsage()
    usage.add("anthropic", "claude-sonnet-4-5", "manager", TokenUsage(1_000_000, 1_000_000))
    totals = usage.to_dict()
    assert totals["cost_usd"] == pytest.approx(18.0)
    assert totals["any_cloud"] is True


def test_an_unpriced_cloud_model_reports_tokens_and_no_cost() -> None:
    """Never a guessed number, and the model is named so the readout can say
    which one it could not price rather than quietly under-reporting."""
    usage = SessionUsage()
    usage.add("custom_gateway", "some-private-model", "worker", TokenUsage(500, 100))
    totals = usage.to_dict()
    assert totals["total_tokens"] == 600
    assert totals["cost_usd"] is None
    assert totals["unpriced_models"] == ["some-private-model"]


def test_no_calls_means_no_cost_not_zero_cost() -> None:
    """`None` and `0.0` mean different things and both reach the UI."""
    assert SessionUsage().to_dict()["cost_usd"] is None


# --------------------------------------------------------------------------- #
# The ledger
# --------------------------------------------------------------------------- #
def test_calls_accumulate_per_provider_model_and_role() -> None:
    ledger = UsageLedger()
    ledger.record("s1", "anthropic", "claude-sonnet-4-5", "manager", TokenUsage(10, 5))
    ledger.record("s1", "anthropic", "claude-sonnet-4-5", "manager", TokenUsage(20, 5))
    ledger.record("s1", "ollama", "qwen3:8b", "worker", TokenUsage(30, 10))

    totals = ledger.totals("s1")
    assert totals["calls"] == 3
    assert totals["total_tokens"] == 80
    assert len(totals["records"]) == 2


def test_sessions_do_not_see_each_other() -> None:
    ledger = UsageLedger()
    ledger.record("s1", "anthropic", "claude-sonnet-4-5", "manager", TokenUsage(10, 5))
    assert ledger.totals("s2")["calls"] == 0


def test_a_call_that_reported_no_tokens_is_not_recorded() -> None:
    ledger = UsageLedger()
    ledger.record("s1", "ollama", "qwen3:8b", "manager", TokenUsage(0, 0))
    assert ledger.totals("s1")["calls"] == 0


def test_one_estimated_call_marks_the_whole_total_estimated() -> None:
    ledger = UsageLedger()
    ledger.record("s1", "ollama", "qwen3:8b", "manager", TokenUsage(10, 5, exact=True))
    ledger.record("s1", "ollama", "qwen3:8b", "manager", TokenUsage(10, 5, exact=False))
    assert ledger.totals("s1")["estimated"] is True


def test_disposing_a_session_forgets_its_usage() -> None:
    ledger = UsageLedger()
    ledger.record("s1", "anthropic", "claude-sonnet-4-5", "manager", TokenUsage(10, 5))
    ledger.forget("s1")
    assert ledger.totals("s1")["calls"] == 0


def test_totals_many_merges_records_across_ids() -> None:
    """The building block Milestone 7 uses to keep a turn's cost readout honest.

    A subagent's LLM calls book under its own composite session id rather
    than the parent's (see `SubagentSession`), so the parent's own `totals()`
    alone would under-report a turn that used subagents. Records are merged by
    `(provider, model, role)`, so a subagent's `worker` calls fold into the
    same bucket the main loop's own do -- correct for "what did this turn
    cost," and each id is still independently queryable for a per-branch
    breakdown.
    """
    ledger = UsageLedger()
    ledger.record("parent", "ollama", "qwen2.5-coder", "manager", TokenUsage(100, 20))
    ledger.record("parent::sub:sub1", "ollama", "qwen2.5-coder", "worker", TokenUsage(50, 10))
    ledger.record("parent::sub:sub2", "ollama", "qwen2.5-coder", "worker", TokenUsage(30, 5))

    merged = ledger.totals_many(["parent", "parent::sub:sub1", "parent::sub:sub2"])
    assert merged["calls"] == 3
    assert merged["input_tokens"] == 180
    assert merged["output_tokens"] == 35
    # Merged into one record per (provider, model, role): two `worker` rows
    # from two different subagents collapse into one bucket, not two.
    assert len(merged["records"]) == 2

    # Each id is still independently queryable.
    assert ledger.totals("parent::sub:sub1")["calls"] == 1

    # An id with nothing recorded (a branch that never ran) contributes nothing.
    assert ledger.totals_many(["parent", "never-spawned"]) == ledger.totals("parent")


# --------------------------------------------------------------------------- #
# Recording through the provider
# --------------------------------------------------------------------------- #
async def test_a_streamed_call_is_booked_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Usage arrives on one chunk of a stream. Booking per chunk would multiply
    the reported cost of every streamed plan and answer by its token count."""
    from src.core.llm import llm_provider
    from src.core.llm.usage import usage_ledger

    class Chunk:
        def __init__(self, content: str, usage: dict | None = None):
            self.content = content
            self.usage_metadata = usage

    class Client:
        async def astream(self, prompt: str):
            yield Chunk("hel")
            yield Chunk("lo")
            yield Chunk("", {"input_tokens": 42, "output_tokens": 7})

    monkeypatch.setattr(llm_provider, "get_client", lambda spec: Client())
    usage_ledger.forget("stream-session")

    produced = [chunk async for chunk in llm_provider.astream("hi", session_id="stream-session")]

    assert "".join(produced) == "hello"
    totals = usage_ledger.totals("stream-session")
    assert totals["calls"] == 1
    assert totals["input_tokens"] == 42
    assert totals["output_tokens"] == 7


async def test_a_failing_meter_never_fails_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.llm import llm_provider

    class Client:
        async def ainvoke(self, prompt: str):
            return SimpleNamespace(content="the answer", usage_metadata={"input_tokens": 1, "output_tokens": 1})

    def explode(*args, **kwargs):
        raise RuntimeError("ledger is broken")

    monkeypatch.setattr(llm_provider, "get_client", lambda spec: Client())
    monkeypatch.setattr("src.core.llm.provider.usage_ledger.record", explode)

    assert await llm_provider.acomplete("hi", session_id="s1") == "the answer"
