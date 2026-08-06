"""Installing a skill from a repository, through the real app.

The fetcher is replaced; nothing else is. What is asserted is the whole route a
user takes — paste a URL, read what came back, approve it, ask the agent about
it, update it — against the real router, the real permission profile and real
files on disk.

The suite pins ``SKILLS_REGISTRY_API`` to a refused port, so a test that forgot
to inject the fake fails immediately instead of reaching github.com.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.api import app
from src.core.session import session_manager
from src.core.skills import install as install_module
from src.core.skills.fetch import FetchError, RemoteEntry
from src.core.skills.index import install_index
from src.core.skills.registry import skill_registry
from src.core.skills.source import SkillSource


SHA_ONE = "1" * 40
SHA_TWO = "2" * 40
URL = "https://github.com/acme/skills"

SKILL = """---
name: cohorts
description: How to define cohorts and compute retention
---

Group customers by signup month, then measure retention per month since.
"""


class StubFetcher:
    def __init__(self, body: str = SKILL, sha: str = SHA_ONE, entries: list[RemoteEntry] | None = None):
        self.body = body
        self.sha = sha
        self.entries = entries or [RemoteEntry(name="SKILL.md", path="SKILL.md", type="file")]

    def resolve(self, source: SkillSource) -> str:
        return self.sha

    def listing(self, source: SkillSource, sha: str) -> list[RemoteEntry]:
        return list(self.entries)

    def read(self, source: SkillSource, sha: str, path: str) -> str:
        return self.body


@pytest.fixture
def client():
    """A client pinned to one session for the whole test.

    Without the header every request creates a *fresh* session, so a permission
    set by one call would not be in force for the next — and a test asserting a
    refusal would pass against a default profile that happened to allow it.
    """
    with TestClient(app) as test_client:
        session_id = test_client.post("/api/session").json()["session_id"]
        test_client.headers.update({"X-Session-Id": session_id})
        yield test_client
    session_manager.shutdown()


@pytest.fixture
def fetcher(monkeypatch):
    """Replaces the client the routes build for themselves."""
    stub = StubFetcher()
    monkeypatch.setattr(install_module, "default_fetcher", lambda: stub)
    return stub


def _stage(client) -> dict:
    response = client.post("/api/skills/install/preview", json={"url": URL})
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Preview and review
# --------------------------------------------------------------------------- #
def test_preview_returns_the_full_contents_and_the_resolved_commit(client, fetcher) -> None:
    """The milestone's central requirement: what is being consented to is on the
    screen at the moment of consent, and so is the exact commit it came from."""
    payload = _stage(client)

    assert payload["sha"] == SHA_ONE
    assert payload["short_sha"] == SHA_ONE[:7]
    assert len(payload["pending"]) == 1
    staged = payload["pending"][0]
    assert staged["name"] == "cohorts"
    assert "retention per month since" in staged["body"]


def test_preview_installs_nothing(client, fetcher) -> None:
    _stage(client)

    assert client.get("/api/skills/cohorts").status_code == 404
    listed = client.get("/api/skills").json()
    assert [skill["name"] for skill in listed["skills"]] == []
    assert len(listed["pending"]) == 1


def test_a_pending_review_is_findable_after_the_tab_is_closed(client, fetcher) -> None:
    _stage(client)
    payload = client.get("/api/skills/pending").json()
    assert [item["name"] for item in payload["pending"]] == ["cohorts"]
    assert payload["root"].endswith("skills-pending")


# --------------------------------------------------------------------------- #
# The network gate
# --------------------------------------------------------------------------- #
def test_a_denied_network_category_refuses_the_install(client, fetcher) -> None:
    """`deny` is a real third state, not a stronger `ask`: a user who set it
    cannot install by clicking."""
    client.post("/api/permissions", json={"profile": "custom", "categories": {"network": "deny"}})

    response = client.post("/api/skills/install/preview", json={"url": URL})

    assert response.status_code == 403
    assert "deny" in response.json()["detail"]
    assert install_module.pending() == []


def test_ask_always_is_answered_by_the_request_itself(client, fetcher) -> None:
    """The REST rule: an authenticated request from the user *is* the answer to
    an `ask`. Asking someone to confirm the button they just pressed is theatre."""
    client.post("/api/permissions", json={"profile": "ask-always"})

    response = client.post("/api/skills/install/preview", json={"url": URL})
    assert response.status_code == 200


def test_local_only_does_not_refuse_an_install(client, fetcher) -> None:
    """No session data, schema or rows leave the machine — this is a download of
    instruction text, the same shape as pulling a model, which the mode does not
    block either. `OUTBOUND_TOOLS` is about tools the agent invokes mid-analysis,
    where the query itself is derived from the user's data."""
    client.post("/api/data-mode", json={"mode": "local-only"})

    response = client.post("/api/skills/install/preview", json={"url": URL})
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# Approval
# --------------------------------------------------------------------------- #
def test_approving_installs_it_with_its_provenance(client, fetcher) -> None:
    staged = _stage(client)["pending"][0]

    response = client.post(f"/api/skills/pending/{staged['id']}/approve")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["layer"] == "user"
    assert body["pinned_sha"] == SHA_ONE
    assert body["source_url"] == URL
    assert client.get("/api/skills/pending").json()["pending"] == []


def test_the_installed_skill_survives_a_reload_with_its_pin(client, fetcher) -> None:
    """Provenance is stamped on from the local index after every scan, so it does
    not depend on anything the fetched file says about itself."""
    staged = _stage(client)["pending"][0]
    client.post(f"/api/skills/pending/{staged['id']}/approve")

    client.post("/api/skills/reload")
    detail = client.get("/api/skills/cohorts").json()
    assert detail["pinned_sha"] == SHA_ONE
    assert detail["source_url"] == URL


def test_discarding_leaves_nothing_behind(client, fetcher) -> None:
    staged = _stage(client)["pending"][0]

    discarded = client.delete(f"/api/skills/pending/{staged['id']}")
    assert discarded.status_code == 200
    assert client.get("/api/skills/pending").json()["pending"] == []
    assert client.get("/api/skills/cohorts").status_code == 404


def test_approving_a_stale_id_says_so(client, fetcher) -> None:
    response = client.post("/api/skills/pending/nope/approve")
    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# Update
# --------------------------------------------------------------------------- #
def test_checking_for_an_update_reports_without_writing(client, fetcher) -> None:
    staged = _stage(client)["pending"][0]
    client.post(f"/api/skills/pending/{staged['id']}/approve")

    fetcher.sha = SHA_TWO
    fetcher.body = SKILL.replace("signup month", "first purchase")
    response = client.post("/api/skills/cohorts/update", json={"apply": False})

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["changed"] is True
    assert result["applied"] is False
    assert "first purchase" in result["diff"]
    # Unchanged on disk: the diff is a step, not a courtesy.
    assert "signup month" in client.get("/api/skills/cohorts").json()["body"]


def test_applying_the_update_moves_the_pin(client, fetcher) -> None:
    staged = _stage(client)["pending"][0]
    client.post(f"/api/skills/pending/{staged['id']}/approve")

    fetcher.sha = SHA_TWO
    fetcher.body = SKILL.replace("signup month", "first purchase")
    result = client.post("/api/skills/cohorts/update", json={"apply": True}).json()

    assert result["applied"] is True
    detail = client.get("/api/skills/cohorts").json()
    assert "first purchase" in detail["body"]
    assert detail["pinned_sha"] == SHA_TWO


def test_an_unchanged_commit_reports_up_to_date(client, fetcher) -> None:
    staged = _stage(client)["pending"][0]
    client.post(f"/api/skills/pending/{staged['id']}/approve")

    result = client.post("/api/skills/cohorts/update", json={"apply": True}).json()
    assert result["changed"] is False
    assert "Nothing to update" in result["message"]


def test_updating_a_hand_written_skill_is_a_404_with_the_reason(client, fetcher) -> None:
    client.post("/api/skills", json={"name": "mine", "description": "Local", "body": "By hand."})
    response = client.post("/api/skills/mine/update", json={})
    assert response.status_code == 404
    assert "not installed from a repository" in response.json()["detail"]


def test_deleting_an_installed_skill_forgets_where_it_came_from(client, fetcher) -> None:
    staged = _stage(client)["pending"][0]
    client.post(f"/api/skills/pending/{staged['id']}/approve")

    removed = client.delete("/api/skills/cohorts")
    assert removed.status_code == 200
    assert install_index.get("cohorts") is None
    assert skill_registry.get("cohorts") is None


# --------------------------------------------------------------------------- #
# Failure reporting
# --------------------------------------------------------------------------- #
def test_an_upstream_failure_is_a_502_not_a_400(client, monkeypatch) -> None:
    """The request was fine and the far end is what failed. A 400 would send the
    user back to re-read a URL that is not the problem."""

    class Broken:
        def resolve(self, source):
            raise FetchError("GitHub's rate limit for this machine is spent.")

    monkeypatch.setattr(install_module, "default_fetcher", lambda: Broken())
    response = client.post("/api/skills/install/preview", json={"url": URL})

    assert response.status_code == 502
    assert "rate limit" in response.json()["detail"]


def test_a_non_github_url_is_a_400(client, fetcher) -> None:
    response = client.post("/api/skills/install/preview", json={"url": "https://evil.example.com/a/b"})
    assert response.status_code == 400
    assert "not a GitHub host" in response.json()["detail"]


def test_an_executable_payload_is_refused_through_the_api(client, monkeypatch) -> None:
    stub = StubFetcher(
        entries=[
            RemoteEntry(name="SKILL.md", path="SKILL.md", type="file"),
            RemoteEntry(name="install.sh", path="install.sh", type="file"),
        ]
    )
    monkeypatch.setattr(install_module, "default_fetcher", lambda: stub)

    response = client.post("/api/skills/install/preview", json={"url": URL})

    assert response.status_code == 400
    assert "install.sh" in response.json()["detail"]
    assert client.get("/api/skills/pending").json()["pending"] == []


def test_the_token_is_never_returned_only_whether_one_exists(client) -> None:
    assert client.get("/api/skills").json()["registry"]["token_saved"] is False

    saved = client.post("/api/skills/token", json={"token": "ghp_secret_value"}).json()
    assert saved["token_saved"] is True
    assert "ghp_secret" not in client.get("/api/skills").text

    client.post("/api/skills/token", json={"token": ""})
    assert client.get("/api/skills").json()["registry"]["token_saved"] is False
