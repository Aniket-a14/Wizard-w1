"""What one turn is allowed to cost.

Every test here pins a defect that made a single question take fifteen to twenty
minutes on a four-core laptop running 1.5B models, and in one case never finish.
None of them are about correctness of the answer; they are about how many model
round-trips are spent reaching it and how much each one is permitted to produce.

The measurements that motivated them, for a compact-tier `auto` run:

======================================  ======  =====
                                        before  after
======================================  ======  =====
manager/worker round-trips per turn          9      3
output tokens any single call may emit    4096    512  (a decision)
tokens of chain-of-thought re-read on
  every later call of the turn            ~1000      0
======================================  ======  =====
"""

from __future__ import annotations

import pandas as pd
import pytest
from stubs import RecordingLLM

from src.config import settings
from src.core.agent.events import EventCollector, EventType
from src.core.agent.orchestrator import AnalysisOrchestrator, orchestrator
from src.core.session import Session


CODE = "```python\nprint(df['A'].sum())\n```"
DECIDE_CODE = "ACTION: code\nGOAL: compute it"


@pytest.fixture
def recording_llm(monkeypatch):
    """A scripted stub that also records the arguments of every call."""

    def install(responses: list[str]) -> RecordingLLM:
        stub = RecordingLLM(responses)
        for target in ("src.core.agent.orchestrator.llm_provider", "src.core.agent.flow.llm_provider"):
            module, _, attribute = target.rpartition(".")
            monkeypatch.setattr(f"{module}.{attribute}", stub, raising=False)
        return stub

    return install


@pytest.fixture
def tier(monkeypatch):
    """Pins the agent tier, which is otherwise inferred from the live model."""

    def choose(name: str):
        monkeypatch.setattr(settings, "AGENT_TIER", name)

    return choose


async def _run(session: Session, llm, instruction: str = "sum column A", mode: str = "auto"):
    collector = EventCollector()
    result = await orchestrator.run(session=session, instruction=instruction, mode=mode, emitter=collector)
    return result, collector


# --------------------------------------------------------------------------- #
# Round-trip count
# --------------------------------------------------------------------------- #
async def test_a_compact_model_is_never_asked_to_choose_its_next_action(
    loaded_session: Session, recording_llm, tier
) -> None:
    """A compact-tier turn costs three model calls: plan, code, answer.

    It used to cost nine. The loop asked the manager what to do on every
    iteration, and a 1.5B model answering that question is a round-trip spent to
    be told something the transcript already says -- while a reasoning distill
    spent its entire output budget deliberating and returned nothing parseable,
    so the call was paid for and the default was taken anyway.
    """
    tier("compact")
    stub = recording_llm(["1. Sum column A.", CODE, "The sum is 15."])

    result, _ = await _run(loaded_session, stub)

    assert result.status == "completed"
    assert len(stub.calls) == 3, [call["role"] for call in stub.calls]
    assert [call["role"] for call in stub.calls] == ["manager", "worker", "manager"]


async def test_a_successful_step_ends_the_loop_rather_than_starting_another(
    loaded_session: Session, recording_llm, tier
) -> None:
    """An unparseable decision now stops; it used to write more code.

    The default when a model returned prose was `code`, so the failure mode of
    asking a weak model to choose was to keep spending. Code that ran and printed
    something has already produced what the answer is written from.
    """
    tier("balanced")
    # The decision response is deliberately not in the required format.
    stub = recording_llm(["1. Sum it.", CODE, "I think we are probably done here, more or less.", "The sum is 15."])

    result, _ = await _run(loaded_session, stub)

    assert result.status == "completed"
    # plan, code, decide, [no verification: nothing new ran], answer
    assert result.iterations == 2
    assert len(stub.calls) <= 5


async def test_a_failed_step_still_gets_another_attempt(loaded_session: Session, recording_llm, tier) -> None:
    """The early exit keys on success, not on merely having run something.

    Stopping after a failure would turn a recoverable error into the answer.
    """
    decision = AnalysisOrchestrator._decide_deterministically
    state = type("S", (), {})()

    class _Step:
        def __init__(self, ok, observation):
            self.ok, self.observation = ok, observation

    state.instruction = "sum column A"
    state.investigation = type("I", (), {"steps": [_Step(False, "NameError: x")]})()
    assert decision(state).kind.value == "code"

    state.investigation = type("I", (), {"steps": [_Step(True, "15")]})()
    assert decision(state).kind.value == "answer"

    # A step that succeeded but printed nothing has produced nothing to report.
    state.investigation = type("I", (), {"steps": [_Step(True, "   ")]})()
    assert decision(state).kind.value == "code"


# --------------------------------------------------------------------------- #
# Output budgets
# --------------------------------------------------------------------------- #
async def test_no_call_is_handed_the_global_token_ceiling(loaded_session: Session, recording_llm, tier) -> None:
    """Every call used to be allowed `MAX_TOKENS`, whatever it was for.

    That is free when a model stops on its own and ruinous when it does not: a
    decision worth sixty tokens could run to four thousand.
    """
    tier("balanced")
    stub = recording_llm(["1. Sum it.", CODE, "ACTION: answer\nGOAL: report it", "The sum is 15."])

    await _run(loaded_session, stub)

    assert stub.calls
    for call in stub.calls:
        assert call["max_tokens"] is not None, call
        assert call["max_tokens"] < settings.MAX_TOKENS, call


def test_a_purpose_budget_can_never_raise_the_global_ceiling(monkeypatch) -> None:
    """`MAX_TOKENS` is what someone lowers when their context is small."""
    monkeypatch.setattr(settings, "MAX_TOKENS", 256)
    assert settings.output_budget("code") == 256
    assert settings.output_budget("decision") == 256
    assert settings.output_budget("anything-unknown") == 256


# --------------------------------------------------------------------------- #
# Chain of thought
# --------------------------------------------------------------------------- #
async def test_a_reasoning_plan_is_not_re_read_on_every_later_call(
    loaded_session: Session, recording_llm, tier
) -> None:
    """The defect that cost the most: `<think>` was never recognised.

    `create_planning_prompt` asks for `<thought>` and only that tag was stripped,
    so with a reasoning model in the manager role the raw chain of thought became
    `state.plan` -- and the plan is embedded in every decision prompt and in the
    answer prompt. One unrecognised tag pair prepended a thousand tokens of
    deliberation to every remaining call of the turn.
    """
    tier("balanced")
    thinking = "Let me think. " * 80
    stub = recording_llm(
        [
            f"<think>{thinking}</think>1. Sum column A.",
            CODE,
            "ACTION: answer\nGOAL: report it",
            "The sum is 15.",
        ]
    )

    result, _ = await _run(loaded_session, stub)

    assert result.plan == "1. Sum column A."
    assert "Let me think." not in result.plan
    for prompt in stub.prompts[1:]:
        assert "Let me think." not in prompt


async def test_a_thinking_model_does_not_stream_its_thinking_as_the_answer(
    loaded_session: Session, recording_llm, tier
) -> None:
    """It was emitted as `content_delta`, so the user read the deliberation."""
    tier("compact")
    stub = recording_llm(["1. Sum it.", CODE, "<think>hmm, 15 then</think>The sum is 15."])

    result, collector = await _run(loaded_session, stub)

    assert result.answer == "The sum is 15."
    content = "".join(e.data.get("content", "") for e in collector.events if e.type is EventType.CONTENT_DELTA)
    assert content == "The sum is 15."
    assert "hmm" not in content
    reasoning = "".join(e.data.get("content", "") for e in collector.events if e.type is EventType.REASONING_DELTA)
    assert "hmm, 15 then" in reasoning


def test_code_is_taken_from_the_answer_not_from_the_discarded_draft() -> None:
    """`_extract_code` takes the *first* fenced block it finds.

    A model thinking out loud drafts code inside `<think>`, rejects it, then
    writes the real thing -- so searching the raw response runs the draft.
    """
    response = (
        "<think>Maybe:\n```python\nprint('WRONG')\n```\nno, that drops nulls.</think>\n```python\nprint('RIGHT')\n```"
    )
    assert AnalysisOrchestrator._extract_code(response) == "print('RIGHT')"


# --------------------------------------------------------------------------- #
# Deadline
# --------------------------------------------------------------------------- #
async def test_a_turn_that_runs_out_of_time_still_answers(
    loaded_session: Session, recording_llm, tier, monkeypatch
) -> None:
    """ "It also did not complete" was the other half of the report.

    Nothing bounded a turn, so a slow model produced no answer at all rather
    than a worse one.
    """
    tier("balanced")
    monkeypatch.setattr(settings, "AGENT_TURN_TIMEOUT", 0.0001)
    stub = recording_llm(["1. Sum it.", CODE, DECIDE_CODE, DECIDE_CODE, "The sum is 15."])

    result, collector = await _run(loaded_session, stub)

    assert result.status == "completed"
    assert result.answer
    assert result.iterations == 1
    assert any("Stopped exploring" in warning for warning in result.warnings)
    assert any(e.type is EventType.WARNING for e in collector.events)


async def test_a_deadline_of_zero_disables_the_ceiling(loaded_session: Session, recording_llm, tier, monkeypatch):
    tier("compact")
    monkeypatch.setattr(settings, "AGENT_TURN_TIMEOUT", 0.0)
    stub = recording_llm(["1. Sum it.", CODE, "The sum is 15."])

    result, _ = await _run(loaded_session, stub)

    assert result.status == "completed"
    assert not any("Stopped exploring" in warning for warning in result.warnings)


# --------------------------------------------------------------------------- #
# Prompt size
# --------------------------------------------------------------------------- #
async def test_the_worker_prompt_honours_the_tier_column_budget(
    session: Session, wide_df: pd.DataFrame, recording_llm, tier
) -> None:
    """`TierBudget.max_columns` existed but only ever reached `inspect`.

    A compact model sized for 25 columns was still handed the schema, statistics,
    sample rows and categorical values for 60 -- thousands of tokens to read
    before emitting anything, on the machine least able to afford it.
    """
    tier("compact")
    session.add_dataset("wide.csv", wide_df.copy())
    stub = recording_llm(["1. Look at it.", CODE, "Done."])

    await _run(session, stub, instruction="summarise the features")

    worker_prompt = stub.prompts[1]
    mentioned = sum(1 for index in range(120) if f"| feature_{index} |" in worker_prompt)
    assert 0 < mentioned <= 25, mentioned


def test_a_clean_frame_costs_no_model_call_to_clean(simple_df: pd.DataFrame) -> None:
    """Every upload bought a worker round-trip and a sandbox execution.

    The cleaning prompt names exactly three problems -- missing values, text that
    is really a number or a date, and untrimmed whitespace -- so all three can be
    looked for directly, and finding none means the call returns `pass`.
    """
    from src.core.agent.flow import _needs_cleaning

    assert not _needs_cleaning(simple_df)
    assert not _needs_cleaning(pd.DataFrame())


@pytest.mark.parametrize(
    ("frame", "why"),
    [
        (pd.DataFrame({"a": [1.0, None]}), "missing values"),
        (pd.DataFrame({"a": [" x ", "y"]}), "untrimmed whitespace"),
        (pd.DataFrame({"a": ["1", "2"]}), "numbers stored as text"),
        (pd.DataFrame({"a": ["2024-01-01", "2024-01-02"]}), "dates stored as text"),
    ],
)
def test_a_frame_that_needs_work_still_gets_the_model(frame: pd.DataFrame, why: str) -> None:
    from src.core.agent.flow import _needs_cleaning

    assert _needs_cleaning(frame), why


# --------------------------------------------------------------------------- #
# Diagnosability
#
# The user who hit all of the above had no way to see why. The backend knows
# which settings are working against the machine; /settings should say so.
# --------------------------------------------------------------------------- #
def test_a_reasoning_manager_and_an_oversubscribed_cpu_are_reported(monkeypatch) -> None:
    from src.api.routes.meta import performance_notes
    from src.utils.hostinfo import host_info

    monkeypatch.setattr(settings, "MODEL_NAME", "deepseek-r1:1.5b")
    monkeypatch.setattr(settings, "LLM_NUM_THREAD", host_info().cores * 2)

    notes = " ".join(performance_notes())
    assert "deepseek-r1:1.5b" in notes
    assert "reasoning model" in notes
    assert "LLM_NUM_THREAD" in notes


def test_a_configuration_that_fits_the_machine_says_nothing(monkeypatch) -> None:
    """An empty list is the common case, and silence has to mean "fine"."""
    from src.api.routes.meta import performance_notes
    from src.utils.hostinfo import host_info

    monkeypatch.setattr(settings, "MODEL_NAME", "qwen2.5:3b")
    monkeypatch.setattr(settings, "LLM_NUM_THREAD", host_info().cores)
    monkeypatch.setattr(settings, "LLM_NUM_CTX", 8192)

    assert performance_notes() == []


def test_the_notes_are_checked_by_symptom_not_by_provenance(monkeypatch) -> None:
    """`model_fields_set` cannot answer this, so the machine is compared against.

    The host-sizing validator assigns to these fields, so by the time anyone can
    ask, a derived value looks exactly like a pinned one.
    """
    from src.api.routes.meta import performance_notes

    monkeypatch.setattr(settings, "MODEL_NAME", "")
    monkeypatch.setattr(settings, "LLM_NUM_THREAD", 1)
    monkeypatch.setattr(settings, "LLM_NUM_CTX", 4096)
    assert performance_notes() == []
