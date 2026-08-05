"""URL parsing, the payload rule, and the install index — the inert half of Milestone 6.

Nothing here touches the network or a fetcher. `source.py` and `index.py` are
this layer's `spec.py` and `store.py`, so most of what the milestone decided can
be asserted with nothing running.
"""

from __future__ import annotations

import pytest

from src.core.skills.index import InstallIndex
from src.core.skills.loader import offending_names
from src.core.skills.source import InstallRecord, SkillSource, SourceError, parse_source
from src.core.skills.spec import Skill, SkillLayer


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("url", "owner", "repo", "ref", "path"),
    [
        ("https://github.com/acme/skills", "acme", "skills", "", ""),
        ("https://github.com/acme/skills.git", "acme", "skills", "", ""),
        ("https://www.github.com/acme/skills/", "acme", "skills", "", ""),
        ("https://github.com/acme/skills/tree/main", "acme", "skills", "main", ""),
        ("https://github.com/acme/skills/tree/main/cohorts", "acme", "skills", "main", "cohorts"),
        ("https://github.com/acme/skills/tree/release/1.2/a/b", "acme", "skills", "release", "1.2/a/b"),
        ("acme/skills", "acme", "skills", "", ""),
        ("acme/skills@v1.2", "acme", "skills", "v1.2", ""),
    ],
)
def test_repository_urls_parse(url, owner, repo, ref, path):
    source = parse_source(url)
    assert (source.kind, source.owner, source.repo, source.ref, source.path) == ("repo", owner, repo, ref, path)


def test_a_blob_url_pointing_at_the_file_resolves_to_its_directory():
    """Clicking SKILL.md in the GitHub UI and copying the address bar is the most
    likely way anybody obtains one of these URLs. Refusing it would fail the
    common case to enforce a distinction the fetcher does not care about."""
    source = parse_source("https://github.com/acme/skills/blob/main/cohorts/SKILL.md")
    assert source.path == "cohorts"


def test_gist_urls_parse_with_or_without_the_user_segment():
    assert parse_source("https://gist.github.com/bob/abc123").gist_id == "abc123"
    assert parse_source("https://gist.github.com/abc123").gist_id == "abc123"


def test_the_url_is_canonicalised_not_kept_verbatim():
    """Three spellings of one repository must produce one permission subject, or
    approving a source once would still ask again for the same source."""
    canonical = "https://github.com/acme/skills"
    assert parse_source("acme/skills").url == canonical
    assert parse_source("https://github.com/acme/skills.git").url == canonical
    assert parse_source("https://www.github.com/acme/skills/").url == canonical


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://evil.example.com/acme/skills",
        "https://gitlab.com/acme/skills",
        "https://github.com/acme",
        "https://github.com/acme/skills/issues/4",
        "https://github.com/acme/skills/tree",
    ],
)
def test_anything_that_is_not_a_github_source_is_refused(url):
    with pytest.raises(SourceError):
        parse_source(url)


def test_a_traversal_segment_is_refused_rather_than_normalised():
    """`..` never reaches the filesystem here, but a traversal segment is a
    statement of intent and the honest answer to it is a refusal."""
    with pytest.raises(SourceError):
        parse_source("https://github.com/acme/skills/tree/main/../../etc")


def test_a_flag_shaped_owner_is_refused():
    with pytest.raises(SourceError):
        parse_source("https://github.com/--help/skills")


# --------------------------------------------------------------------------- #
# The payload rule
# --------------------------------------------------------------------------- #
def test_the_executable_rule_reads_a_list_of_names():
    """The same function decides for a directory on disk and for a listing
    fetched from GitHub — which is the point of extracting it."""
    assert offending_names(["SKILL.md", "README.md", "helper.py"]) == ["helper.py"]
    assert offending_names(["SKILL.md", "notes.txt"]) == []
    assert offending_names(["setup.SH", "run.Bat"]) == ["setup.SH", "run.Bat"]


# --------------------------------------------------------------------------- #
# The index
# --------------------------------------------------------------------------- #
def _record(name: str = "cohorts", sha: str = "a" * 40) -> InstallRecord:
    return InstallRecord(name=name, source=parse_source("acme/skills"), sha=sha)


def test_the_index_round_trips_through_disk(tmp_path):
    index = InstallIndex(tmp_path / "installed.json")
    assert index.record(_record())

    reread = InstallIndex(tmp_path / "installed.json")
    stored = reread.get("cohorts")
    assert stored is not None
    assert stored.sha == "a" * 40
    assert stored.source.url == "https://github.com/acme/skills"


def test_an_update_keeps_the_original_install_time(tmp_path):
    """When it was first obtained and when it last changed are different
    questions, and the UI shows both."""
    index = InstallIndex(tmp_path / "installed.json")
    index.record(InstallRecord(name="cohorts", source=parse_source("acme/skills"), sha="a" * 40, installed_at=100.0))
    index.record(InstallRecord(name="cohorts", source=parse_source("acme/skills"), sha="b" * 40, updated_at=500.0))

    stored = index.get("cohorts")
    assert stored is not None
    assert (stored.installed_at, stored.updated_at, stored.sha) == (100.0, 500.0, "b" * 40)


def test_a_corrupt_index_reads_as_empty_rather_than_raising(tmp_path):
    path = tmp_path / "installed.json"
    path.write_text("{ not json", encoding="utf-8")
    assert InstallIndex(path).list() == []


def test_overlay_stamps_provenance_onto_a_user_skill(tmp_path):
    index = InstallIndex(tmp_path / "installed.json")
    index.record(_record(sha="c" * 40))

    skill = Skill(name="cohorts", description="d", body="b", layer=SkillLayer.USER)
    index.overlay([skill])

    assert skill.pinned_sha == "c" * 40
    assert skill.source_url == "https://github.com/acme/skills"
    assert skill.updated_at is not None


def test_overlay_leaves_other_layers_alone(tmp_path):
    """Nothing installs into the built-in layer (it is the checkout) or the
    project layer (it came with the repository), so a matching name there is a
    different skill that happens to share one."""
    index = InstallIndex(tmp_path / "installed.json")
    index.record(_record())

    builtin = Skill(name="cohorts", description="d", body="b", layer=SkillLayer.BUILTIN)
    project = Skill(name="cohorts", description="d", body="b", layer=SkillLayer.PROJECT)
    index.overlay([builtin, project])

    assert builtin.pinned_sha is None
    assert project.pinned_sha is None


def test_forgetting_removes_the_record(tmp_path):
    index = InstallIndex(tmp_path / "installed.json")
    index.record(_record())
    assert index.forget("cohorts") is True
    assert index.get("cohorts") is None
    assert index.forget("cohorts") is False


def test_a_record_needs_a_name_and_a_commit():
    with pytest.raises(ValueError):
        InstallRecord.from_dict({"source": SkillSource(kind="repo").to_dict(), "sha": ""})
