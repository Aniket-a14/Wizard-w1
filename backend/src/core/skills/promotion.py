"""Noticing that an analysis has become a habit, and offering to name it.

The milestone describes this as promoting a *trajectory* that "succeeds
repeatedly". The trajectories table does not hold that: ``save_trajectory`` fires
only when ``retry_count > 0``, so it records a failure that was then self-healed
and nothing else. On a healthy install almost nothing lands there, and waiting
for a repeat of it would mean the promotion offer effectively never appears.

So two kinds are counted, separately, because they are different claims:

``recurring``
    A successful turn whose question has been asked before. This is the signal
    that actually means "you keep doing this", and it is what most promotions
    will come from.

``recovery``
    A failure-then-fix that has now happened more than once for similar
    questions. "This used to fail and now reliably works" is worth writing down
    for a different reason -- it is a trap, not a routine -- and a skill made
    from it reads differently, so the two are not merged into one counter.

Clustering
----------
Two questions are the same analysis when their instructions embed close together,
which is the same judgement ``retrieve_trajectories`` already makes and reuses its
threshold. A **dismissed or promoted candidate still participates in matching** --
otherwise the next occurrence inserts a fresh row and the offer the user just
declined comes back on the following turn.

Nothing here writes a skill. Crossing the threshold produces a *candidate*; a file
appears only when the user confirms, which is what the milestone means by "not
auto-published silently".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.config import settings
from src.core.database import db_mgr
from src.core.embeddings import embedding_service
from src.utils.logging import logger


KIND_RECURRING = "recurring"
KIND_RECOVERY = "recovery"

KIND_LABELS = {
    KIND_RECURRING: "You have run this analysis before",
    KIND_RECOVERY: "This analysis used to fail and now works",
}


@dataclass
class Candidate:
    """One recurring analysis, as the UI and the event frame see it."""

    id: int
    kind: str
    instruction: str
    occurrences: int
    plan: str = ""
    code: str = ""
    columns: list[str] | None = None

    @property
    def ready(self) -> bool:
        return self.occurrences >= settings.SKILL_PROMOTION_THRESHOLD

    def suggested_name(self) -> str:
        """A slug the user can accept or replace.

        Built from the instruction's content words. Offering a name is what makes
        the promotion form a confirmation rather than a writing task, which is
        the difference between a prompt people accept and one they dismiss.
        """
        from src.core.rag.retriever import tokenize

        words = [word for word in tokenize(self.instruction) if len(word) > 2]
        # `tokenize` returns a set, so recover the instruction's own order --
        # "revenue-by-region" reads as a name and "region-by-revenue" does not.
        lowered = self.instruction.lower()
        ordered = sorted(words, key=lambda word: lowered.find(word))
        slug = "-".join(ordered[:4]) or "saved-analysis"
        return slug[:64].strip("-")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": KIND_LABELS.get(self.kind, self.kind),
            "instruction": self.instruction,
            "occurrences": self.occurrences,
            "threshold": settings.SKILL_PROMOTION_THRESHOLD,
            "suggested_name": self.suggested_name(),
            "plan": self.plan,
            "code": self.code,
        }


def _from_row(entry: dict[str, Any]) -> Candidate:
    return Candidate(
        id=int(entry["id"]),
        kind=entry["kind"],
        instruction=entry["instruction"] or "",
        occurrences=int(entry["occurrences"] or 0),
        plan=entry["plan"],
        code=entry["code"],
        columns=entry["columns"],
    )


def _match(kind: str, instruction: str) -> dict[str, Any] | None:
    """The existing candidate this instruction is another occurrence of."""
    entries = db_mgr.get_skill_candidates(kind=kind, include_settled=True)
    if not entries:
        return None

    ranked = embedding_service.rank(
        instruction, [(entry["instruction"] or "", entry["embedding"]) for entry in entries]
    )
    if not ranked:
        return None

    score, index = ranked[0]
    if score < settings.TRAJECTORY_MIN_SIMILARITY:
        return None
    return entries[index]


def record(
    kind: str,
    instruction: str,
    columns: list[str],
    plan: str = "",
    code: str = "",
) -> Candidate | None:
    """Counts one occurrence. Returns a candidate only when it has *just* become offerable.

    "Just" is the whole contract: returning it on every subsequent run would put
    the same card in front of the user after every turn until they act, which is
    how a useful prompt becomes one people learn to click away. A candidate that
    was already at or over the threshold, already promoted, or dismissed, returns
    ``None``.
    """
    if not settings.SKILLS_ENABLED:
        return None

    text = (instruction or "").strip()
    if not text:
        return None

    try:
        embedding = embedding_service.encode(text.lower())
        existing = _match(kind, text)

        if existing is None:
            candidate_id = db_mgr.add_skill_candidate(kind, text, columns, plan, code, embedding)
            occurrences = 1
        else:
            if existing["dismissed"] or existing["promoted_to"]:
                # Still counted, so the record stays true, but never re-offered.
                db_mgr.bump_skill_candidate(int(existing["id"]), plan, code)
                return None
            candidate_id = int(existing["id"])
            occurrences = db_mgr.bump_skill_candidate(candidate_id, plan, code)
    except Exception as exc:
        # Bookkeeping must never cost a turn that already produced an answer.
        logger.error("Could not record a skill candidate", error=str(exc))
        return None

    if not candidate_id or occurrences != settings.SKILL_PROMOTION_THRESHOLD:
        return None

    logger.info("Analysis reached the promotion threshold", kind=kind, occurrences=occurrences)
    return Candidate(
        id=candidate_id,
        kind=kind,
        instruction=text,
        occurrences=occurrences,
        plan=plan,
        code=code,
        columns=columns,
    )


def record_success(instruction: str, columns: list[str], plan: str = "", code: str = "") -> Candidate | None:
    return record(KIND_RECURRING, instruction, columns, plan, code)


def record_recovery(instruction: str, columns: list[str], plan: str = "", code: str = "") -> Candidate | None:
    return record(KIND_RECOVERY, instruction, columns, plan, code)


def pending() -> list[Candidate]:
    """Every candidate at or over the threshold, still awaiting a decision.

    What the ``/skills`` page lists, so an offer missed in the chat can still be
    found later rather than being a one-shot card.
    """
    return [
        _from_row(entry)
        for entry in db_mgr.get_skill_candidates()
        if int(entry["occurrences"] or 0) >= settings.SKILL_PROMOTION_THRESHOLD
    ]


def get(candidate_id: int) -> Candidate | None:
    for entry in db_mgr.get_skill_candidates(include_settled=True):
        if int(entry["id"]) == candidate_id:
            return _from_row(entry)
    return None


def find(instruction: str) -> Candidate | None:
    """The candidate this question is an occurrence of, **at any count**.

    :func:`pending` answers "what has recurred enough to be offered"; this
    answers "what did this particular analysis get recorded as", which is the
    question the milestone's *other* promotion path asks. A user saying "save
    this one" about the answer in front of them is not waiting for a threshold,
    and the row already exists -- every successful turn records one -- so the
    plan and code that ran are there to draft from.
    """
    text = (instruction or "").strip()
    if not text:
        return None
    try:
        entry = _match(KIND_RECURRING, text)
    except Exception as exc:  # pragma: no cover - retrieval degrading is not fatal
        logger.warning("Could not match an analysis to a candidate", error=str(exc))
        return None
    return _from_row(entry) if entry else None


def dismiss(candidate_id: int) -> bool:
    return db_mgr.settle_skill_candidate(candidate_id)


def mark_promoted(candidate_id: int, skill_name: str) -> bool:
    return db_mgr.settle_skill_candidate(candidate_id, promoted_to=skill_name)


def draft_body(candidate: Candidate) -> str:
    """A first draft of the skill, from what actually ran.

    Pulled from the stored plan and code rather than asked of a model: the
    grounding layer's rule is that what is reported comes from what happened, and
    a model asked to summarise its own past work would produce a plausible
    description of an analysis it is not reading. The user edits this before it
    is saved; a draft they correct is worth more than a blank page.
    """
    lines = [
        "## When to use this",
        "",
        f"Questions like: *{candidate.instruction}*",
        "",
        "## How to approach it",
        "",
        (candidate.plan.strip() or "_Describe the approach that works for this question._"),
    ]
    if candidate.code.strip():
        lines += [
            "",
            "## What worked last time",
            "",
            "```python",
            candidate.code.strip(),
            "```",
            "",
            "_Reference only — the analysis is rewritten for the data in front of it._",
        ]
    return "\n".join(lines)


__all__ = [
    "KIND_LABELS",
    "KIND_RECOVERY",
    "KIND_RECURRING",
    "Candidate",
    "dismiss",
    "draft_body",
    "find",
    "get",
    "mark_promoted",
    "pending",
    "record",
    "record_recovery",
    "record_success",
]
