"""Noticing a recurring analysis, and offering it exactly once.

The milestone describes promotion as counting repeats in the ``trajectories``
table. That table does not hold repeated successes -- ``save_trajectory`` fires
only after a self-heal -- so two kinds are counted separately here, and these
tests pin that they stay separate.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.core.database import db_mgr
from src.core.skills import promotion
from src.core.skills.promotion import KIND_RECOVERY, KIND_RECURRING


COLUMNS = ["region", "revenue", "signup_date"]
QUESTION = "break down revenue by region for the last quarter"


@pytest.fixture(autouse=True)
def _clean_candidates():
    db_mgr.clear_skill_candidates()
    yield
    db_mgr.clear_skill_candidates()


def run(kind: str = KIND_RECURRING, question: str = QUESTION, times: int = 1):
    """Records ``times`` occurrences and returns what each one offered."""
    return [promotion.record(kind, question, COLUMNS, "the plan", "print(1)") for _ in range(times)]


# --------------------------------------------------------------------------- #
# The threshold
# --------------------------------------------------------------------------- #
def test_nothing_is_offered_below_the_threshold() -> None:
    # Derived from the setting rather than spelled `[None, None]`: the rest of
    # this file already follows the configured threshold, and a literal here
    # fails for the right behaviour the moment someone changes it.
    below = settings.SKILL_PROMOTION_THRESHOLD - 1
    assert run(times=below) == [None] * below


def test_the_offer_arrives_exactly_at_the_threshold() -> None:
    offers = run(times=settings.SKILL_PROMOTION_THRESHOLD)

    assert offers[:-1] == [None] * (settings.SKILL_PROMOTION_THRESHOLD - 1)
    candidate = offers[-1]
    assert candidate is not None
    assert candidate.occurrences == settings.SKILL_PROMOTION_THRESHOLD
    assert candidate.kind == KIND_RECURRING


def test_the_offer_is_made_once_not_on_every_later_run() -> None:
    """Re-offering after every turn is how a useful prompt becomes one people
    learn to click away."""
    offers = run(times=settings.SKILL_PROMOTION_THRESHOLD + 3)
    assert len([offer for offer in offers if offer is not None]) == 1


def test_pending_keeps_listing_it_until_it_is_settled() -> None:
    """The one-shot frame is the *offer*; the candidate itself stays findable, so
    a card missed in the chat is not lost."""
    run(times=settings.SKILL_PROMOTION_THRESHOLD + 2)
    assert [candidate.instruction for candidate in promotion.pending()] == [QUESTION]


def test_a_threshold_change_is_honoured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SKILL_PROMOTION_THRESHOLD", 2)
    offers = run(times=2)
    assert offers[0] is None
    assert offers[1] is not None


# --------------------------------------------------------------------------- #
# Clustering
# --------------------------------------------------------------------------- #
def test_the_same_question_bumps_rather_than_inserting() -> None:
    run(times=2)
    assert len(db_mgr.get_skill_candidates()) == 1
    assert db_mgr.get_skill_candidates()[0]["occurrences"] == 2


def test_an_unrelated_question_is_its_own_candidate() -> None:
    run(times=1)
    promotion.record(KIND_RECURRING, "plot the distribution of tips by weekday", COLUMNS, "", "")

    assert len(db_mgr.get_skill_candidates()) == 2
    assert all(entry["occurrences"] == 1 for entry in db_mgr.get_skill_candidates())


def test_the_stored_plan_and_code_are_refreshed_not_frozen() -> None:
    """What the user would promote is how they do this *now*; the first attempt
    at a recurring analysis is usually the worst one."""
    promotion.record(KIND_RECURRING, QUESTION, COLUMNS, "first plan", "print('first')")
    promotion.record(KIND_RECURRING, QUESTION, COLUMNS, "better plan", "print('better')")

    entry = db_mgr.get_skill_candidates()[0]
    assert entry["plan"] == "better plan"
    assert entry["code"] == "print('better')"


def test_an_empty_plan_does_not_erase_a_stored_one() -> None:
    promotion.record(KIND_RECURRING, QUESTION, COLUMNS, "the good plan", "print(1)")
    promotion.record(KIND_RECURRING, QUESTION, COLUMNS, "", "")

    assert db_mgr.get_skill_candidates()[0]["plan"] == "the good plan"


def test_a_blank_question_records_nothing() -> None:
    assert promotion.record(KIND_RECURRING, "   ", COLUMNS) is None
    assert db_mgr.get_skill_candidates() == []


def test_nothing_is_recorded_when_skills_are_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SKILLS_ENABLED", False)
    assert promotion.record(KIND_RECURRING, QUESTION, COLUMNS) is None
    assert db_mgr.get_skill_candidates() == []


# --------------------------------------------------------------------------- #
# The two kinds stay separate
# --------------------------------------------------------------------------- #
def test_recurring_and_recovery_are_counted_independently() -> None:
    """Merging them would lose whichever claim the user actually wanted written
    down: "you keep doing this" and "this used to fail" are different skills."""
    run(kind=KIND_RECURRING, times=settings.SKILL_PROMOTION_THRESHOLD)
    recovery_offers = run(kind=KIND_RECOVERY, times=settings.SKILL_PROMOTION_THRESHOLD)

    assert recovery_offers[-1] is not None
    assert recovery_offers[-1].kind == KIND_RECOVERY

    kinds = sorted(entry["kind"] for entry in db_mgr.get_skill_candidates(include_settled=True))
    assert kinds == [KIND_RECOVERY, KIND_RECURRING]


def test_a_recurring_count_does_not_satisfy_the_recovery_threshold() -> None:
    run(kind=KIND_RECURRING, times=settings.SKILL_PROMOTION_THRESHOLD + 5)
    assert run(kind=KIND_RECOVERY, times=1) == [None]


def test_pending_can_be_filtered_to_one_kind() -> None:
    run(kind=KIND_RECURRING, times=settings.SKILL_PROMOTION_THRESHOLD)
    assert [entry["kind"] for entry in db_mgr.get_skill_candidates(kind=KIND_RECOVERY)] == []


# --------------------------------------------------------------------------- #
# Settling
# --------------------------------------------------------------------------- #
def test_dismissal_is_sticky_across_later_occurrences() -> None:
    """A dismissed candidate must still *match*, or the next occurrence inserts a
    fresh row and the offer the user just declined comes straight back."""
    offers = run(times=settings.SKILL_PROMOTION_THRESHOLD)
    promotion.dismiss(offers[-1].id)

    assert run(times=3) == [None, None, None]
    assert promotion.pending() == []
    # Still one row: counted, never re-offered.
    assert len(db_mgr.get_skill_candidates(include_settled=True)) == 1


def test_a_promoted_candidate_stops_being_offered() -> None:
    offers = run(times=settings.SKILL_PROMOTION_THRESHOLD)
    promotion.mark_promoted(offers[-1].id, "revenue-by-region")

    assert run(times=2) == [None, None]
    assert promotion.pending() == []
    assert db_mgr.get_skill_candidates(include_settled=True)[0]["promoted_to"] == "revenue-by-region"


def test_dismissing_something_absent_reports_it_rather_than_succeeding() -> None:
    """This asserted `is True` and was pinning a defect: `settle_skill_candidate`
    returned unconditionally, so an UPDATE matching no row read as success and
    the dismiss route answered 200 for an id that never existed."""
    assert promotion.dismiss(9999) is False
    assert promotion.pending() == []


def test_get_returns_a_settled_candidate() -> None:
    offers = run(times=settings.SKILL_PROMOTION_THRESHOLD)
    promotion.dismiss(offers[-1].id)
    assert promotion.get(offers[-1].id) is not None


# --------------------------------------------------------------------------- #
# What the offer carries
# --------------------------------------------------------------------------- #
def test_the_suggested_name_follows_the_questions_own_word_order() -> None:
    """`tokenize` returns a set. Without recovering the order,
    "revenue-by-region" comes back as "region-by-revenue"."""
    offers = run(times=settings.SKILL_PROMOTION_THRESHOLD)
    name = offers[-1].suggested_name()

    from src.core.skills.spec import is_valid_skill_name

    assert is_valid_skill_name(name)
    assert name.index("revenue") < name.index("region")


def test_a_question_of_pure_stopwords_still_yields_a_name() -> None:
    from src.core.skills.promotion import Candidate

    assert Candidate(id=1, kind=KIND_RECURRING, instruction="show me the data", occurrences=3).suggested_name()


def test_the_draft_body_is_built_from_what_actually_ran() -> None:
    """Not asked of a model: the grounding rule is that what is reported comes
    from what happened, and a model summarising its own past work would describe
    an analysis it is not reading."""
    offers = run(times=settings.SKILL_PROMOTION_THRESHOLD)
    body = promotion.draft_body(offers[-1])

    assert "the plan" in body
    assert "print(1)" in body
    assert QUESTION in body


def test_the_draft_omits_the_code_section_when_there_was_none() -> None:
    from src.core.skills.promotion import Candidate

    body = promotion.draft_body(Candidate(id=1, kind=KIND_RECURRING, instruction="q", occurrences=3, plan="p"))
    assert "```python" not in body


def test_the_offer_serialises_with_its_threshold() -> None:
    offers = run(times=settings.SKILL_PROMOTION_THRESHOLD)
    payload = offers[-1].to_dict()

    assert payload["threshold"] == settings.SKILL_PROMOTION_THRESHOLD
    assert payload["occurrences"] == settings.SKILL_PROMOTION_THRESHOLD
    assert payload["label"]
    assert payload["suggested_name"]
