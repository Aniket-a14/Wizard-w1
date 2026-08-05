"""The skills surface through the real app.

Real files in a real directory, so what is asserted is the whole path a user
takes -- browse, create, edit, promote, remove -- rather than a mock of it. The
suite pins both derived skill roots to temp directories, so nothing here reads a
developer's own skills or the ones Wizard ships.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.api import app
from src.config import settings
from src.core.database import db_mgr
from src.core.session import session_manager
from src.core.skills import promotion
from src.core.skills.registry import skill_registry
from src.core.skills.spec import SkillLayer


BUILTIN = """---
name: shipped-skill
description: Something Wizard ships with
---

The shipped instructions.
"""


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    session_manager.shutdown()


@pytest.fixture
def builtin_skill(monkeypatch, tmp_path: Path):
    """Puts one skill into the read-only layer for this test only."""
    from src.core.skills import registry as registry_module

    root = tmp_path / "builtin"
    (root / "shipped-skill").mkdir(parents=True)
    (root / "shipped-skill" / "SKILL.md").write_text(BUILTIN, encoding="utf-8")

    monkeypatch.setitem(registry_module.ROOTS, SkillLayer.BUILTIN, lambda: root)
    skill_registry.reload()
    yield root
    skill_registry.reload()


# --------------------------------------------------------------------------- #
# Browsing
# --------------------------------------------------------------------------- #
def test_an_install_with_no_skills_lists_its_roots_anyway(client) -> None:
    """The empty state still has to say where a skill would go, or "add one" has
    no answer."""
    body = client.get("/api/skills").json()

    assert body["skills"] == []
    assert {root["layer"] for root in body["roots"]} == {"builtin", "user", "project"}
    assert body["enabled"] is True


def test_the_builtin_layer_is_reported_read_only(client) -> None:
    roots = {root["layer"]: root["writable"] for root in client.get("/api/skills").json()["roots"]}
    assert roots == {"builtin": False, "user": True, "project": True}


def test_a_shipped_skill_is_listed_and_readable(client, builtin_skill) -> None:
    listed = client.get("/api/skills").json()["skills"]
    assert [skill["name"] for skill in listed] == ["shipped-skill"]
    assert listed[0]["writable"] is False

    detail = client.get("/api/skills/shipped-skill").json()
    assert detail["body"].strip() == "The shipped instructions."


def test_an_unknown_skill_is_a_404(client) -> None:
    assert client.get("/api/skills/nope").status_code == 404


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #
def test_create_read_update_delete(client) -> None:
    created = client.post(
        "/api/skills",
        json={"name": "fee-rules", "description": "How fees apply", "body": "Charge at capture.", "tags": ["fees"]},
    )
    assert created.status_code == 200
    assert created.json()["layer"] == "user"
    assert created.json()["tags"] == ["fees"]

    assert client.get("/api/skills/fee-rules").json()["body"] == "Charge at capture."

    updated = client.put(
        "/api/skills/fee-rules",
        json={"name": "fee-rules", "description": "How fees apply", "body": "Charge at authorisation."},
    )
    assert updated.json()["body"] == "Charge at authorisation."

    assert client.delete("/api/skills/fee-rules").status_code == 200
    assert client.get("/api/skills/fee-rules").status_code == 404


def test_a_written_skill_is_a_real_file_on_disk(client) -> None:
    """Acceptance criterion 2: a user can open and edit the file directly."""
    client.post("/api/skills", json={"name": "on-disk", "description": "d", "body": "The body."})

    path = Path(client.get("/api/skills/on-disk").json()["path"])
    assert path.is_file()
    assert path.name == "SKILL.md"
    assert "The body." in path.read_text(encoding="utf-8")


def test_an_edit_made_outside_the_app_is_picked_up_by_reload(client) -> None:
    """Skills are plain files, so a text editor is a valid way to change one."""
    client.post("/api/skills", json={"name": "edited", "description": "d", "body": "Original."})
    path = Path(client.get("/api/skills/edited").json()["path"])

    path.write_text(path.read_text(encoding="utf-8").replace("Original.", "Changed by hand."), encoding="utf-8")
    assert client.post("/api/skills/reload").status_code == 200
    assert client.get("/api/skills/edited").json()["body"] == "Changed by hand."


def test_writing_a_builtin_is_refused_with_a_reason(client, builtin_skill) -> None:
    """409 with the reason, not a silent no-op into a file the next update
    discards."""
    response = client.put(
        "/api/skills/shipped-skill",
        json={"name": "shipped-skill", "description": "d", "body": "Mine now."},
    )
    assert response.status_code == 409
    assert "ships with Wizard" in response.json()["detail"]
    assert client.get("/api/skills/shipped-skill").json()["body"].strip() == "The shipped instructions."


def test_deleting_a_builtin_is_refused(client, builtin_skill) -> None:
    response = client.delete("/api/skills/shipped-skill")
    assert response.status_code == 409
    assert "cannot be removed" in response.json()["detail"]


def test_a_user_skill_shadows_a_builtin_of_the_same_name(client, builtin_skill) -> None:
    """The documented way to override something shipped, and the shadowed copy
    stays listed so it is clear what happened."""
    client.post("/api/skills", json={"name": "shipped-skill", "description": "Mine", "body": "My version."})

    assert client.get("/api/skills/shipped-skill").json()["body"] == "My version."

    listed = client.get("/api/skills").json()["skills"]
    shadowed = [skill for skill in listed if skill["shadowed_by"]]
    assert len(shadowed) == 1
    assert shadowed[0]["layer"] == "builtin"
    assert shadowed[0]["shadowed_by"] == "user"


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"name": "Bad Name", "description": "d", "body": "b"}, "not a usable skill name"),
        ({"name": "ok", "description": "", "body": "b"}, "one-line description"),
        ({"name": "ok", "description": "d", "body": "  "}, "needs instructions"),
    ],
)
def test_an_unusable_skill_is_a_400_that_says_why(client, payload: dict, reason: str) -> None:
    response = client.post("/api/skills", json=payload)
    assert response.status_code == 400
    assert reason in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Promotion
# --------------------------------------------------------------------------- #
@pytest.fixture
def candidate():
    db_mgr.clear_skill_candidates()
    offered = None
    for _ in range(settings.SKILL_PROMOTION_THRESHOLD):
        offered = promotion.record_success(
            "break down revenue by region", ["region", "revenue"], "the plan", "print('x')"
        )
    yield offered
    db_mgr.clear_skill_candidates()


def test_a_recurring_analysis_is_listed_as_a_candidate(client, candidate) -> None:
    body = client.get("/api/skills/candidates").json()

    assert body["threshold"] == settings.SKILL_PROMOTION_THRESHOLD
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["occurrences"] == settings.SKILL_PROMOTION_THRESHOLD


def test_the_draft_comes_from_the_analysis_that_ran(client, candidate) -> None:
    draft = client.get(f"/api/skills/candidates/{candidate.id}/draft").json()

    assert draft["name"]
    assert "the plan" in draft["body"]
    assert "print('x')" in draft["body"]


def test_promoting_writes_the_skill_and_settles_the_candidate(client, candidate) -> None:
    created = client.post(
        "/api/skills",
        json={
            "name": "revenue-by-region",
            "description": "How to break revenue down by region",
            "body": "Group by region, then sum.",
            "candidate_id": candidate.id,
        },
    )
    assert created.status_code == 200
    assert created.json()["layer"] == "user"

    assert client.get("/api/skills/candidates").json()["candidates"] == []
    assert db_mgr.get_skill_candidates(include_settled=True)[0]["promoted_to"] == "revenue-by-region"


def test_a_failed_write_leaves_the_offer_standing(client, candidate) -> None:
    """The candidate is settled only after the file exists, or a rejected name
    would silently consume the offer."""
    assert client.post("/api/skills", json={"name": "Bad Name", "description": "d", "body": "b"}).status_code == 400
    assert len(client.get("/api/skills/candidates").json()["candidates"]) == 1


def test_dismissing_stops_the_offer_permanently(client, candidate) -> None:
    assert client.post(f"/api/skills/candidates/{candidate.id}/dismiss").status_code == 200
    assert client.get("/api/skills/candidates").json()["candidates"] == []

    # And it stays gone as the analysis keeps recurring.
    promotion.record_success("break down revenue by region", ["region", "revenue"])
    assert client.get("/api/skills/candidates").json()["candidates"] == []


def test_a_draft_for_an_unknown_candidate_is_a_404(client) -> None:
    assert client.get("/api/skills/candidates/999/draft").status_code == 404


def test_the_candidates_route_is_not_shadowed_by_the_name_route(client) -> None:
    """`/api/skills/candidates` and `/api/skills/{name}` overlap; declaration
    order is what keeps the literal path winning."""
    assert client.get("/api/skills/candidates").status_code == 200


# --------------------------------------------------------------------------- #
# "See which analyses used which skill"
#
# The milestone asks the browser to show this, and the live `skill` frame cannot:
# it is gone by the time the page is opened. These pin the recorded half.
# --------------------------------------------------------------------------- #
def test_a_skill_reports_how_many_analyses_it_informed(client, builtin_skill) -> None:
    db_mgr.record_skill_usage(["shipped-skill"], "which cohorts are churning")
    db_mgr.record_skill_usage(["shipped-skill"], "revenue by region please")

    listed = client.get("/api/skills").json()["skills"]
    entry = next(item for item in listed if item["name"] == "shipped-skill")
    assert entry["uses"] == 2
    assert entry["last_used"] is not None


def test_a_skill_names_the_questions_it_informed(client, builtin_skill) -> None:
    db_mgr.record_skill_usage(["shipped-skill"], "which cohorts are churning")

    detail = client.get("/api/skills/shipped-skill").json()
    assert [use["instruction"] for use in detail["recent_uses"]] == ["which cohorts are churning"]


def test_an_unused_skill_reports_zero_rather_than_nothing(client, builtin_skill) -> None:
    """Absent usage is a real answer -- "never used" -- not missing data."""
    entry = next(item for item in client.get("/api/skills").json()["skills"] if item["name"] == "shipped-skill")
    assert entry["uses"] == 0
    assert entry["last_used"] is None
    assert client.get("/api/skills/shipped-skill").json()["recent_uses"] == []


# --------------------------------------------------------------------------- #
# Promoting an analysis the user picked, rather than one that recurred
# --------------------------------------------------------------------------- #
def test_a_completed_analysis_can_be_drafted_without_a_threshold(client) -> None:
    """The milestone's second promotion route: no recurrence needed, and the
    plan and code that ran are what the draft is built from."""
    promotion.record_success("break down revenue by region", ["region"], "1. Group by region", "df.groupby('region')")

    drafted = client.post("/api/skills/draft", json={"instruction": "break down revenue by region"})
    assert drafted.status_code == 200

    payload = drafted.json()
    assert payload["candidate_id"] is not None
    assert "df.groupby('region')" in payload["body"]
    assert payload["name"]


def test_a_never_seen_question_still_drafts(client) -> None:
    """Whether the button works must not depend on bookkeeping the user cannot
    see, so a question with no recorded candidate drafts from itself."""
    payload = client.post("/api/skills/draft", json={"instruction": "something asked once"}).json()
    assert payload["candidate_id"] is None
    assert "something asked once" in payload["body"]


def test_an_explicit_promotion_writes_a_skill_and_settles_the_candidate(client) -> None:
    promotion.record_success("break down revenue by region", ["region"], "1. Group by region", "code()")
    draft = client.post("/api/skills/draft", json={"instruction": "break down revenue by region"}).json()

    created = client.post(
        "/api/skills",
        json={
            "name": "revenue-by-region",
            "description": "How to break revenue down by region",
            "body": draft["body"],
            "candidate_id": draft["candidate_id"],
        },
    )
    assert created.status_code == 200
    assert created.json()["layer"] == "user"
    assert db_mgr.get_skill_candidates(include_settled=True)[0]["promoted_to"] == "revenue-by-region"


def test_the_draft_route_is_not_shadowed_by_the_name_route(client) -> None:
    """`POST /api/skills/draft` sits under the same prefix as `/{name}`, which
    only accepts GET/PUT/DELETE -- but declaration order is still what decides."""
    assert client.post("/api/skills/draft", json={"instruction": "anything"}).status_code == 200
