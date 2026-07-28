"""Separating a reasoning model's thinking from what it actually said.

The behaviour these pin is not cosmetic. `state.plan` is embedded in every later
decision prompt and in the answer prompt, so a chain of thought left inside it is
re-read by the model on every subsequent call of the turn.
"""

from __future__ import annotations

import pytest

from src.core.llm.reasoning import (
    ReasoningStream,
    looks_like_reasoning_model,
    split_reasoning,
    strip_reasoning,
)


@pytest.mark.parametrize(
    ("raw", "reasoning", "visible"),
    [
        ("<think>weighing it up</think>ACTION: answer", "weighing it up", "ACTION: answer"),
        ("<THINK>shouting</THINK>quiet", "shouting", "quiet"),
        ("<think >spaced</think >x", "spaced", "x"),
        # DeepSeek-R1 through Ollama returns the literal tags in `content`.
        ("<think>\nlong\nmultiline\n</think>\n\nThe answer is 4.", "long\nmultiline", "The answer is 4."),
        # No tags at all: everything is visible.
        ("ACTION: code\nGOAL: load it", "", "ACTION: code\nGOAL: load it"),
        ("", "", ""),
    ],
)
def test_a_reasoning_block_is_separated_from_the_response(raw, reasoning, visible):
    assert split_reasoning(raw) == (reasoning, visible)


def test_a_prefilled_opening_tag_leaves_an_orphan_close():
    """Some servers put `<think>` in the prompt, so the reply starts mid-thought."""
    assert split_reasoning("still deliberating</think>ACTION: answer") == (
        "still deliberating",
        "ACTION: answer",
    )


def test_a_block_that_never_closes_yields_no_visible_text():
    """What a hard `num_predict` cap produces when a model thinks past its budget.

    Empty is the honest answer. Returning the half-monologue would put a model's
    private deliberation in front of the user as though it were the result.
    """
    reasoning, visible = split_reasoning("<think>I should start by considering")
    assert visible == ""
    assert reasoning == "I should start by considering"


def test_our_own_thought_tag_is_handled_by_the_same_function():
    """`create_planning_prompt` asks for `<thought>`; models emit `<think>`.

    Both were reasoning and only one was recognised, which is the whole defect.
    """
    assert strip_reasoning("<thought>mine</thought>plan") == "plan"
    assert strip_reasoning("<think>theirs</think>plan") == "plan"


def test_several_blocks_are_all_removed():
    reasoning, visible = split_reasoning("<think>a</think>one<think>b</think>two")
    assert visible == "onetwo"
    assert reasoning == "a\n\nb"


def test_reasoning_models_are_recognised_by_name():
    assert looks_like_reasoning_model("deepseek-r1:1.5b")
    assert looks_like_reasoning_model("qwq:32b")
    assert not looks_like_reasoning_model("qwen2.5-coder:1.5b")
    assert not looks_like_reasoning_model("")


# ---------------------------------------------------------------------- #
# Streaming
# ---------------------------------------------------------------------- #
def _drive(deltas: list[str]) -> tuple[str, str]:
    """Feeds a stream and returns the (reasoning, visible) it classified."""
    stream = ReasoningStream()
    reasoning: list[str] = []
    visible: list[str] = []
    for delta in [*deltas, ""]:
        for is_reasoning, text in stream.feed(delta):
            (reasoning if is_reasoning else visible).append(text)
    for is_reasoning, text in stream.flush():
        (reasoning if is_reasoning else visible).append(text)
    return "".join(reasoning), "".join(visible)


def test_streaming_classifies_the_same_way_as_the_whole_string():
    raw = "<think>deliberating at length</think>The answer is 4."
    assert _drive(list(raw)) == ("deliberating at length", "The answer is 4.")


def test_a_tag_split_across_deltas_is_still_recognised():
    """Token boundaries fall inside tags constantly; `<thi` + `nk>` is one tag."""
    assert _drive(["<thi", "nk>", "hmm", "</thi", "nk>", "done"]) == ("hmm", "done")


def test_a_partial_tag_is_never_emitted_as_content():
    """`<thi` must not reach the UI as text only to be retracted."""
    stream = ReasoningStream()
    assert stream.feed("answer <thi") == [(False, "answer ")]


def test_text_with_no_reasoning_block_streams_as_visible():
    """Regression: it used to stream as *reasoning* until a tag showed up.

    The `fast` planning prompt asks for no reasoning block at all, so every fast
    plan went to the thinking panel and the plan panel stayed empty.
    """
    assert _drive(["1. Load", " the data", "\n2. Group"]) == ("", "1. Load the data\n2. Group")


def test_an_unclosed_stream_flushes_as_reasoning():
    assert _drive(["<think>", "cut off here"]) == ("cut off here", "")
