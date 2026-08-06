"""Fetching, staging, reviewing, installing and updating — against a fake fetcher.

`Fetcher` is a Protocol precisely so this file exists: the whole install flow is
exercised with no network and nothing skipped. A subsystem that can only be tested
by reaching out is a subsystem that stops being tested.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.core.skills import install
from src.core.skills.fetch import RemoteEntry
from src.core.skills.index import install_index
from src.core.skills.registry import skill_registry
from src.core.skills.source import SkillSource
from src.core.skills.spec import SkillLayer


SHA_ONE = "1" * 40
SHA_TWO = "2" * 40


def installed_body(name: str) -> str:
    skill = skill_registry.get(name)
    assert skill is not None, f"'{name}' is not installed"
    return skill.body


def skill_text(
    name: str = "cohorts", description: str = "How to build cohorts", body: str = "Group by signup month."
) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"


class FakeFetcher:
    """A repository in a dict. Records every call so cost can be asserted.

    ``tree`` maps a path (``""`` is the root) to the entries at it; ``files`` maps
    a path to its text.
    """

    def __init__(self, tree: dict[str, list[RemoteEntry]], files: dict[str, str], sha: str = SHA_ONE):
        self.tree = tree
        self.files = files
        self.sha = sha
        self.calls: list[str] = []

    def resolve(self, source: SkillSource) -> str:
        self.calls.append(f"resolve:{source.slug}")
        return self.sha

    def listing(self, source: SkillSource, sha: str) -> list[RemoteEntry]:
        self.calls.append(f"list:{source.path}")
        assert sha == self.sha, "every request after the pin must carry the resolved commit"
        return list(self.tree.get(source.path, []))

    def read(self, source: SkillSource, sha: str, path: str) -> str:
        self.calls.append(f"read:{path}")
        assert sha == self.sha
        return self.files[path]


def single_skill_repo(text: str | None = None) -> FakeFetcher:
    return FakeFetcher(
        tree={
            "": [
                RemoteEntry(name="SKILL.md", path="SKILL.md", type="file"),
                RemoteEntry(name="README.md", path="README.md", type="file"),
            ]
        },
        files={"SKILL.md": text if text is not None else skill_text()},
    )


# --------------------------------------------------------------------------- #
# Preview and staging
# --------------------------------------------------------------------------- #
def test_preview_stages_without_installing():
    staged = install.preview("acme/skills", single_skill_repo())

    assert [item.name for item in staged] == ["cohorts"]
    assert staged[0].sha == SHA_ONE
    assert staged[0].body == "Group by signup month."
    # The whole point: nothing the agent can reach has changed.
    assert skill_registry.get("cohorts") is None
    assert install_index.get("cohorts") is None


def test_a_staged_skill_survives_being_forgotten_in_memory():
    """Staging goes to disk so a review interrupted by a closed tab is findable
    again rather than costing a second fetch."""
    install.preview("acme/skills", single_skill_repo())
    skill_registry.reload()

    reread = install.pending()
    assert [item.name for item in reread] == ["cohorts"]
    assert reread[0].body == "Group by signup month."


def test_previewing_the_same_source_twice_replaces_rather_than_piles_up():
    install.preview("acme/skills", single_skill_repo())
    install.preview("acme/skills", single_skill_repo())
    assert len(install.pending()) == 1


def test_the_staged_root_is_a_sibling_of_the_skills_root_not_a_child_of_it():
    """So a staged skill cannot become live through one bug in `skill_paths`'
    `iterdir` — and so "pending" is something a person can see in a file browser."""
    install.preview("acme/skills", single_skill_repo())

    staging = install.pending_root()
    assert staging.name == "skills-pending"
    assert staging not in skill_registry.roots().values()
    assert skill_registry.roots()[SkillLayer.USER] not in staging.parents
    assert skill_registry.get("cohorts") is None


# --------------------------------------------------------------------------- #
# The trust boundary
# --------------------------------------------------------------------------- #
def test_an_executable_payload_is_refused_before_anything_is_downloaded():
    fetcher = FakeFetcher(
        tree={
            "": [
                RemoteEntry(name="SKILL.md", path="SKILL.md", type="file"),
                RemoteEntry(name="helper.py", path="helper.py", type="file"),
            ]
        },
        files={"SKILL.md": skill_text()},
    )
    with pytest.raises(install.InstallError, match="helper.py"):
        install.preview("acme/skills", fetcher)

    assert not any(call.startswith("read:") for call in fetcher.calls), (
        "the refusal must come off the listing, before a byte of content is fetched"
    )
    assert install.pending() == []


def test_a_file_without_a_description_is_refused_as_unusable():
    fetcher = single_skill_repo("---\nname: cohorts\n---\n\nSome instructions.\n")
    with pytest.raises(install.InstallError, match="description"):
        install.preview("acme/skills", fetcher)


def test_a_source_with_no_skill_file_is_refused_by_name():
    fetcher = FakeFetcher(tree={"": [RemoteEntry(name="README.md", path="README.md", type="file")]}, files={})
    with pytest.raises(install.InstallError, match="SKILL.md"):
        install.preview("acme/skills", fetcher)


def test_frontmatter_cannot_claim_a_provenance_it_does_not_have():
    """A fetched file describing its own origin is a claim, not a record. The
    loader stopped reading these two keys when Milestone 6 made them spoofable."""
    hostile = (
        "---\nname: cohorts\ndescription: d\n"
        "source_url: https://github.com/trusted/vendor\npinned_sha: deadbeefdeadbeef\n---\n\nBody.\n"
    )
    install.preview("acme/skills", single_skill_repo(hostile))
    skill = install.approve(install.pending()[0].id)

    assert skill.source_url == "https://github.com/acme/skills"
    assert skill.pinned_sha == SHA_ONE


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def test_several_skills_under_a_skills_directory_are_all_found():
    fetcher = FakeFetcher(
        tree={
            "": [
                RemoteEntry(name="skills", path="skills", type="dir"),
                RemoteEntry(name="README.md", path="README.md", type="file"),
            ],
            "skills": [
                RemoteEntry(name="cohorts", path="skills/cohorts", type="dir"),
                RemoteEntry(name="churn", path="skills/churn", type="dir"),
            ],
            "skills/cohorts": [RemoteEntry(name="SKILL.md", path="skills/cohorts/SKILL.md", type="file")],
            "skills/churn": [RemoteEntry(name="SKILL.md", path="skills/churn/SKILL.md", type="file")],
        },
        files={
            "skills/cohorts/SKILL.md": skill_text("cohorts", "Cohorts", "Group by month."),
            "skills/churn/SKILL.md": skill_text("churn", "Churn", "Count the leavers."),
        },
    )
    staged = install.preview("acme/skills", fetcher)
    assert sorted(item.name for item in staged) == ["churn", "cohorts"]
    # Each records the directory it came from, so an update goes back to that
    # directory rather than re-scanning the whole repository.
    assert sorted(item.source.path for item in staged) == ["skills/churn", "skills/cohorts"]


def test_discovery_does_not_descend_past_one_level():
    """A repository with a deep tree must not cost a request per directory."""
    fetcher = FakeFetcher(
        tree={
            "": [RemoteEntry(name="pack", path="pack", type="dir")],
            "pack": [RemoteEntry(name="deeper", path="pack/deeper", type="dir")],
            "pack/deeper": [RemoteEntry(name="SKILL.md", path="pack/deeper/SKILL.md", type="file")],
        },
        files={"pack/deeper/SKILL.md": skill_text()},
    )
    with pytest.raises(install.InstallError):
        install.preview("acme/skills", fetcher)


# --------------------------------------------------------------------------- #
# Approval
# --------------------------------------------------------------------------- #
def test_approving_installs_and_records_where_it_came_from():
    install.preview("acme/skills", single_skill_repo())
    skill = install.approve(install.pending()[0].id)

    assert skill.layer.value == "user"
    assert skill_registry.get("cohorts") is not None
    assert install.pending() == [], "the staged copy goes once it is installed"

    record = install_index.get("cohorts")
    assert record is not None
    assert (record.sha, record.source.url) == (SHA_ONE, "https://github.com/acme/skills")


def test_an_installed_skill_is_retrievable_by_the_agent():
    """The end of the acceptance sentence: available to the agent, through the
    ordinary retrieval path, with the same gates as everything else."""
    install.preview("acme/skills", single_skill_repo())
    install.approve(install.pending()[0].id)

    matches = skill_registry.search("how do I build cohorts", limit=1)
    assert [match.skill.name for match in matches] == ["cohorts"]


def test_a_conflict_with_an_existing_skill_is_reported_before_install():
    skill_registry.write("cohorts", "Mine", "My own version.")
    staged = install.preview("acme/skills", single_skill_repo())

    assert staged[0].conflicts_with == "cohorts"
    assert staged[0].conflict_layer == "user"


def test_discarding_installs_nothing():
    install.preview("acme/skills", single_skill_repo())
    discarded = install.discard(install.pending()[0].id)
    assert discarded is True
    assert install.pending() == []
    assert skill_registry.get("cohorts") is None


def test_approving_something_that_is_not_staged_is_an_error():
    with pytest.raises(install.InstallError):
        install.approve("nope")


# --------------------------------------------------------------------------- #
# Update — pin, don't track
# --------------------------------------------------------------------------- #
def _install_one() -> None:
    install.preview("acme/skills", single_skill_repo())
    install.approve(install.pending()[0].id)


def test_the_same_commit_reports_up_to_date_and_writes_nothing():
    _install_one()
    fetcher = single_skill_repo(skill_text(body="Something completely different."))

    result = install.check_update("cohorts", fetcher)

    assert result.changed is False
    assert "Nothing to update" in result.message
    assert installed_body("cohorts") == "Group by signup month."
    assert not any(call.startswith("read:") for call in fetcher.calls), (
        "an unchanged commit must not cost a content fetch"
    )


def test_a_new_commit_produces_a_diff_and_still_writes_nothing():
    _install_one()
    fetcher = single_skill_repo(skill_text(body="Group by first purchase instead."))
    fetcher.sha = SHA_TWO

    result = install.check_update("cohorts", fetcher)

    assert result.changed is True
    assert result.applied is False
    assert "first purchase" in result.diff
    assert "signup month" in result.diff
    assert installed_body("cohorts") == "Group by signup month.", (
        "checking for an update must not change the installed skill"
    )


def test_applying_the_update_replaces_the_file_and_moves_the_pin():
    _install_one()
    fetcher = single_skill_repo(skill_text(body="Group by first purchase instead."))
    fetcher.sha = SHA_TWO

    result = install.apply_update("cohorts", fetcher)

    assert result.applied is True
    assert installed_body("cohorts") == "Group by first purchase instead."
    record = install_index.get("cohorts")
    assert record is not None and record.sha == SHA_TWO


def test_the_diff_is_against_the_file_on_disk_not_against_upstream_at_install_time():
    """A local edit must show as context, not as an incoming change — otherwise
    the user is told upstream made edits they made themselves."""
    _install_one()
    skill_registry.write("cohorts", "How to build cohorts", "My own edited body.")

    fetcher = single_skill_repo(skill_text(body="Upstream's new body."))
    fetcher.sha = SHA_TWO
    result = install.check_update("cohorts", fetcher)

    assert "My own edited body." in result.diff
    assert "Upstream's new body." in result.diff


def test_updating_a_hand_written_skill_is_refused_with_the_reason():
    skill_registry.write("mine", "Local", "Written by hand.")
    with pytest.raises(install.InstallError, match="not installed from a repository"):
        install.check_update("mine", single_skill_repo())


def test_uninstalling_takes_the_index_entry_with_the_file():
    """A record left behind would offer an update for a skill that is not there."""
    _install_one()
    removed = install.uninstall("cohorts")
    assert removed is True
    assert skill_registry.get("cohorts") is None
    assert install_index.get("cohorts") is None


# --------------------------------------------------------------------------- #
# GitHub Enterprise
# --------------------------------------------------------------------------- #
def test_the_enterprise_host_is_compared_exactly_not_matched_as_a_substring(monkeypatch):
    """`"api.github.com" in root` reads as a hostname test and is not one.

    A root of `https://api.github.com.example.invalid` contains that string while
    being an entirely different host, so the setting would be classified by a name
    that merely appears inside it. The host is parsed and compared instead.
    """
    monkeypatch.setattr(settings, "SKILLS_REGISTRY_API", "https://api.github.com")
    assert install._enterprise_hosts() == frozenset()

    monkeypatch.setattr(settings, "SKILLS_REGISTRY_API", "https://api.github.com.example.invalid")
    assert install._enterprise_hosts() == frozenset({"api.github.com.example.invalid", "github.com.example.invalid"})

    monkeypatch.setattr(settings, "SKILLS_REGISTRY_API", "https://github.example.com/api/v3")
    assert install._enterprise_hosts() == frozenset({"github.example.com"})


def test_an_enterprise_root_lets_its_own_web_host_through(monkeypatch):
    """The point of deriving it: the operator configures the API root, and URLs
    from the matching web host are then accepted without a second setting."""
    from src.core.skills.source import parse_source

    monkeypatch.setattr(settings, "SKILLS_REGISTRY_API", "https://github.example.com/api/v3")
    source = parse_source("https://github.example.com/acme/skills", extra_hosts=install._enterprise_hosts())
    assert (source.owner, source.repo) == ("acme", "skills")
