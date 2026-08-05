"""Reading, writing and promoting skills.

Not gated by the permission profile, and deliberately so. Every layer is a local
file the user put there, and promotion is a REST action the user initiated -- the
same reasoning that leaves *saving* a connection ungated while *opening* one is
not. Milestone 6's fetch-from-GitHub is what will need the ``network`` category,
because that is the point where something arrives from outside.

A write aimed at a built-in skill returns **409 with the reason** rather than
succeeding into a file the next ``git pull`` discards.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import require_api_key
from src.api.schemas import (
    SkillCandidateListResponse,
    SkillDetail,
    SkillDraftRequest,
    SkillListResponse,
    SkillRoot,
    SkillSummary,
    SkillWriteRequest,
)
from src.config import settings
from src.core.database import db_mgr
from src.core.skills import promotion
from src.core.skills.registry import skill_registry
from src.core.skills.spec import SkillError, SkillLayer, SkillNotWritable
from src.utils.logging import logger


router = APIRouter(prefix="/api/skills", tags=["skills"])


def _roots() -> list[SkillRoot]:
    return [
        SkillRoot(layer=layer.value, label=layer.label, path=str(path), writable=layer.writable)
        for layer, path in skill_registry.roots().items()
    ]


@router.get("", response_model=SkillListResponse)
async def list_skills() -> SkillListResponse:
    """Every installed skill, the roots they came from, and any pending offer.

    Shadowed skills are included: a built-in overridden by a user copy still
    exists, and hiding it is what makes "I edited it and nothing changed"
    unanswerable.
    """
    skills = await asyncio.to_thread(skill_registry.list, include_shadowed=True)
    usage = await asyncio.to_thread(db_mgr.skill_usage_summary)
    return SkillListResponse(
        skills=[
            SkillSummary(
                **skill.summary(),
                uses=usage.get(skill.name, {}).get("uses", 0),
                last_used=usage.get(skill.name, {}).get("last_used"),
            )
            for skill in skills
        ],
        roots=_roots(),
        candidates=[candidate.to_dict() for candidate in promotion.pending()],
        enabled=settings.SKILLS_ENABLED,
    )


@router.post("/reload", dependencies=[Depends(require_api_key)])
async def reload_skills() -> dict:
    """Re-scans the roots after an edit made outside the app.

    The point of skills being plain files is that a text editor is a valid way to
    change one, and the registry caches. Without this the answer to "I edited the
    file" would be "restart the backend".
    """
    await asyncio.to_thread(skill_registry.reload)
    count = await asyncio.to_thread(len, skill_registry)
    return {"message": f"Reloaded {count} skill(s).", "count": count}


@router.get("/candidates", response_model=SkillCandidateListResponse)
async def list_candidates() -> SkillCandidateListResponse:
    """Analyses that have recurred enough to be worth naming.

    Also served here, not only as a live frame, so an offer missed in the chat is
    still findable rather than being a one-shot card.
    """
    candidates = await asyncio.to_thread(promotion.pending)
    return SkillCandidateListResponse(
        candidates=[candidate.to_dict() for candidate in candidates],
        threshold=settings.SKILL_PROMOTION_THRESHOLD,
    )


@router.get("/candidates/{candidate_id}/draft", dependencies=[Depends(require_api_key)])
async def draft_candidate(candidate_id: int) -> dict:
    """A first draft of the skill this candidate would become.

    Built from the plan and code that actually ran, not asked of a model: the
    grounding layer's rule is that what is reported comes from what happened, and
    a model asked to summarise its own past work would describe an analysis it is
    not reading.
    """
    candidate = await asyncio.to_thread(promotion.get, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail=f"No skill candidate with id {candidate_id}.")
    return {
        "name": candidate.suggested_name(),
        "description": f"How to answer questions like: {candidate.instruction}"[:200],
        "body": promotion.draft_body(candidate),
        "candidate": candidate.to_dict(),
    }


@router.post("/draft", dependencies=[Depends(require_api_key)])
async def draft_from_analysis(request: SkillDraftRequest) -> dict:
    """A draft for an analysis the user picked, rather than one that recurred.

    The milestone asks for both routes into promotion: an offer the agent makes
    when something has recurred, and an explicit "save this one" about an answer
    already on screen. This is the second, and it needs no threshold — every
    successful turn already records a candidate, so the plan and code that ran
    are there to draft from.

    A question with no recorded candidate still gets a draft, from the question
    itself. Refusing would mean the button works or not depending on bookkeeping
    the user cannot see.
    """
    candidate = await asyncio.to_thread(promotion.find, request.instruction)
    if candidate is None:
        candidate = promotion.Candidate(
            id=0, kind=promotion.KIND_RECURRING, instruction=request.instruction.strip(), occurrences=1
        )

    return {
        "name": candidate.suggested_name(),
        "description": f"How to answer questions like: {candidate.instruction}"[:200],
        "body": promotion.draft_body(candidate),
        # Null when nothing was recorded, which the client passes straight back:
        # `POST /api/skills` only settles a candidate when it is given one.
        "candidate_id": candidate.id or None,
        "candidate": candidate.to_dict() if candidate.id else None,
    }


@router.post("/candidates/{candidate_id}/dismiss", dependencies=[Depends(require_api_key)])
async def dismiss_candidate(candidate_id: int) -> dict:
    """Stops offering this analysis for promotion.

    Persisted rather than held for the session: declining once must not mean
    being asked again on the next turn, which is how a useful prompt becomes one
    people learn to click away.
    """
    if not await asyncio.to_thread(promotion.dismiss, candidate_id):
        raise HTTPException(status_code=404, detail=f"No skill candidate with id {candidate_id}.")
    return {"message": "Dismissed. This analysis will not be offered again."}


@router.get("/{name}", response_model=SkillDetail)
async def get_skill(name: str) -> SkillDetail:
    """One skill's full text, and the analyses it has informed.

    The usage list is the browser half of "see which analyses used which skill".
    The live ``skill`` frame answers it during a turn; by the time this page is
    open that frame is gone, so it is read back from what was recorded.
    """
    skill = await asyncio.to_thread(skill_registry.get, name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"No skill called '{name}'.")
    recent = await asyncio.to_thread(db_mgr.get_skill_usage, skill.name)
    usage = await asyncio.to_thread(db_mgr.skill_usage_summary)
    return SkillDetail(
        **skill.to_dict(),
        recent_uses=recent,
        uses=usage.get(skill.name, {}).get("uses", 0),
        last_used=usage.get(skill.name, {}).get("last_used"),
    )


@router.post("", response_model=SkillDetail, dependencies=[Depends(require_api_key)])
async def create_skill(request: SkillWriteRequest) -> SkillDetail:
    """Writes a new skill into the user-global layer.

    Also the promotion endpoint: passing ``candidate_id`` marks that recurring
    analysis as promoted, which is what stops it being offered again. The
    candidate is settled only *after* the file is written, so a failed write
    leaves the offer standing rather than silently consuming it.
    """
    try:
        skill = await asyncio.to_thread(
            skill_registry.write,
            request.name,
            request.description,
            request.body,
            layer=SkillLayer.USER,
            tags=request.tags,
        )
    except SkillNotWritable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if request.candidate_id is not None:
        await asyncio.to_thread(promotion.mark_promoted, request.candidate_id, skill.name)
        logger.info("Promoted an analysis to a skill", skill=skill.name, candidate=request.candidate_id)

    return SkillDetail(**skill.to_dict())


@router.put("/{name}", response_model=SkillDetail, dependencies=[Depends(require_api_key)])
async def update_skill(name: str, request: SkillWriteRequest) -> SkillDetail:
    """Rewrites a skill in place, in whichever writable layer defines it."""
    existing = await asyncio.to_thread(skill_registry.get, name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"No skill called '{name}'.")
    if not existing.layer.writable:
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{existing.name}' ships with Wizard and is replaced on update. "
                "Save a copy under the same name to override it — the user layer takes precedence."
            ),
        )

    try:
        skill = await asyncio.to_thread(
            skill_registry.write,
            existing.name,
            request.description,
            request.body,
            layer=existing.layer,
            tags=request.tags,
        )
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return SkillDetail(**skill.to_dict())


@router.delete("/{name}", dependencies=[Depends(require_api_key)])
async def delete_skill(name: str) -> dict:
    try:
        removed = await asyncio.to_thread(skill_registry.delete, name)
    except SkillNotWritable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not removed:
        raise HTTPException(status_code=404, detail=f"No skill called '{name}'.")
    return {"message": f"Removed '{name}'."}
