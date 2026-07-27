"""The action space and its parser.

The loop is only as reliable as its ability to read a model's choice. A 1.5B
model asked for ``ACTION: code`` will produce ``**Action:** Code.``, or a
sentence, or nothing usable at all — and none of those may abort the run. These
tests pin that: every input resolves to a runnable decision.
"""

from __future__ import annotations

import pytest

from src.core.agent.actions import (
    SELECTABLE,
    ActionKind,
    Investigation,
    Step,
    parse_decision,
)


# --------------------------------------------------------------------------- #
# Well-formed decisions
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,kind,goal",
    [
        ("ACTION: code\nGOAL: compute revenue by month", ActionKind.CODE, "compute revenue by month"),
        ("ACTION: answer\nGOAL: report the total", ActionKind.ANSWER, "report the total"),
        ("ACTION: inspect\nGOAL: check nulls", ActionKind.INSPECT, "check nulls"),
        ("ACTION: reflect\nGOAL: revise the plan", ActionKind.REFLECT, "revise the plan"),
        ("ACTION: consult\nGOAL: find the fee rule", ActionKind.CONSULT, "find the fee rule"),
    ],
)
def test_exact_format_is_read_exactly(raw: str, kind: ActionKind, goal: str) -> None:
    decision = parse_decision(raw)
    assert decision.kind is kind
    assert decision.goal == goal
    assert not decision.inferred


@pytest.mark.parametrize(
    "raw",
    [
        "**ACTION:** code\n**GOAL:** do the thing",
        "`ACTION`: code\n`GOAL`: do the thing",
        "ACTION = code\nGOAL = do the thing",
        "*action*: code\n*goal*: do the thing",
        "ACTION:code\nGOAL:do the thing",
    ],
)
def test_markdown_decoration_does_not_defeat_the_parser(raw: str) -> None:
    """Models bold the label at least as often as they follow the format.

    Rejecting `**ACTION:** code` would throw away a correct decision over
    typography, and the fallback would silently do something else.
    """
    decision = parse_decision(raw)
    assert decision.kind is ActionKind.CODE
    assert not decision.inferred


def test_action_and_goal_on_one_line() -> None:
    decision = parse_decision("ACTION: code — join orders to customers on customer_id")
    assert decision.kind is ActionKind.CODE
    assert decision.goal == "join orders to customers on customer_id"


def test_rationale_is_captured_when_offered() -> None:
    decision = parse_decision("ACTION: reflect\nGOAL: rethink\nWHY: the join key is dirty")
    assert decision.rationale == "the join key is dirty"


# --------------------------------------------------------------------------- #
# Malformed decisions must still produce a runnable action
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,kind",
    [
        ("I will now compute the monthly totals.", ActionKind.CODE),
        ("Let me examine the null structure first.", ActionKind.INSPECT),
        ("I think we can conclude from this.", ActionKind.ANSWER),
        ("Time to revise my approach.", ActionKind.REFLECT),
    ],
)
def test_prose_falls_back_to_the_first_action_word(raw: str, kind: ActionKind) -> None:
    decision = parse_decision(raw)
    assert decision.kind is kind
    assert decision.inferred, "a prose match is a guess and must be reported as one"


@pytest.mark.parametrize("raw", ["", "   ", "###", "aaaa bbbb cccc", "42"])
def test_unreadable_output_never_raises(raw: str) -> None:
    """A parse failure must cost an iteration, not the whole run."""
    decision = parse_decision(raw)
    assert decision.kind in SELECTABLE
    assert decision.inferred


def test_default_is_configurable_for_the_final_iteration() -> None:
    """On the last permitted iteration the only useful fallback is to answer."""
    assert parse_decision("gibberish", default=ActionKind.ANSWER).kind is ActionKind.ANSWER
    assert parse_decision("gibberish", default=ActionKind.CODE).kind is ActionKind.CODE


def test_a_disallowed_choice_is_not_honoured() -> None:
    """A compact-tier run offers no reflection, so asking for it must not get it."""
    allowed = (ActionKind.CODE, ActionKind.ANSWER)
    decision = parse_decision("ACTION: reflect\nGOAL: rethink", allowed=allowed)
    assert decision.kind in allowed


def test_only_the_first_word_of_the_action_line_selects_the_action() -> None:
    """Otherwise a verb inside the goal picks the action instead of the label."""
    decision = parse_decision("ACTION: code\nGOAL: inspect the answer column and finish")
    assert decision.kind is ActionKind.CODE


# --------------------------------------------------------------------------- #
# Investigation transcript
# --------------------------------------------------------------------------- #
def test_transcript_keeps_recent_steps_in_full_and_collapses_older_ones() -> None:
    """Unbounded growth pushes the question out of the model's context.

    The old pipeline had the opposite failure: it passed 200 characters between
    steps, so later steps could not see what earlier ones computed.
    """
    investigation = Investigation()
    for index in range(6):
        investigation.record(
            Step(
                index=index,
                kind=ActionKind.CODE,
                goal=f"step {index}",
                observation=f"line one of {index}\nline two of {index}",
            )
        )

    rendered = investigation.render(observation_chars=4000)

    # The three most recent survive whole.
    assert "line two of 5" in rendered
    assert "line two of 4" in rendered
    assert "line two of 3" in rendered
    # Older ones keep only their first line.
    assert "line one of 0" in rendered
    assert "line two of 0" not in rendered


def test_a_single_huge_observation_is_trimmed_from_the_middle() -> None:
    """Head and tail both matter: setup at the top, the result at the bottom."""
    step = Step(index=1, kind=ActionKind.CODE, goal="dump", observation="HEAD" + ("x" * 5000) + "TAIL")
    rendered = step.render(limit=400)

    assert "HEAD" in rendered
    assert "TAIL" in rendered
    assert "omitted" in rendered
    assert len(rendered) < 700


def test_executed_output_collects_only_successful_steps() -> None:
    """The grounding check runs against this; a traceback is not a result."""
    investigation = Investigation()
    investigation.record(Step(index=1, kind=ActionKind.CODE, goal="a", observation="total 42", ok=True))
    investigation.record(Step(index=2, kind=ActionKind.CODE, goal="b", observation="KeyError: 99", ok=False))

    assert "42" in investigation.executed_output
    assert "99" not in investigation.executed_output


def test_last_successful_code_ignores_failed_attempts() -> None:
    investigation = Investigation()
    investigation.record(Step(index=1, kind=ActionKind.CODE, goal="a", observation="ok", ok=True, code="good = 1"))
    investigation.record(Step(index=2, kind=ActionKind.CODE, goal="b", observation="boom", ok=False, code="bad = 2"))

    assert investigation.last_successful_code == "good = 1"


def test_findings_and_assumptions_deduplicate() -> None:
    """The same caveat surfacing on three iterations is still one caveat."""
    investigation = Investigation()
    investigation.note_finding("Orders before 2020 have no region.")
    investigation.note_finding("Orders before 2020 have no region.")
    investigation.note_assumption("Nulls were dropped.")
    investigation.note_assumption("  Nulls were dropped.  ")

    assert investigation.findings == ["Orders before 2020 have no region."]
    assert investigation.assumptions == ["Nulls were dropped."]
