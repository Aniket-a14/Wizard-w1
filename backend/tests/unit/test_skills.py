"""The skills format, the loader's refusals, and layered resolution.

Most of this runs against a temporary directory with nothing else started, which
is the point of splitting ``core/skills`` the way ``core/connectors`` is split:
the format and the precedence rules are assertable with no model loaded and
nothing on the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.skills.frontmatter import parse, render, split
from src.core.skills.loader import executable_payload, load_skill, skill_paths
from src.core.skills.registry import SkillRegistry
from src.core.skills.spec import InvalidSkill, SkillLayer, SkillNotWritable, is_valid_skill_name


VALID = """---
name: fee-rules
description: How fees are applied and when they are waived
tags: [fees, billing]
version: 1.2
---

## The rule

A fee is applied at capture, not at authorisation.
"""


def write_skill(root: Path, name: str, text: str, *, directory: bool = True) -> Path:
    if directory:
        target = root / name
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(text, encoding="utf-8")
        return target
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Frontmatter
# --------------------------------------------------------------------------- #
def test_frontmatter_reads_the_supported_subset() -> None:
    data, body = parse(VALID)

    assert data["name"] == "fee-rules"
    assert data["description"] == "How fees are applied and when they are waived"
    assert data["tags"] == ["fees", "billing"]
    # Version stays a string. Read as a number, `1.10` would render as `1.1`.
    assert data["version"] == "1.2"
    assert body.startswith("## The rule")


def test_a_block_list_is_read_as_a_list() -> None:
    data, _ = parse("---\nname: x\ndescription: y\ntags:\n  - alpha\n  - beta\n---\n\nBody.\n")
    assert data["tags"] == ["alpha", "beta"]


def test_quotes_are_stripped_and_hyphenated_keys_normalise() -> None:
    data, _ = parse("---\nname: \"x\"\ndescription: 'y'\nsource-url: http://example.com/a\n---\n\nBody.\n")
    assert data["name"] == "x"
    assert data["description"] == "y"
    assert data["source_url"] == "http://example.com/a"


def test_an_unterminated_fence_is_refused_rather_than_guessed() -> None:
    with pytest.raises(InvalidSkill, match="never closed"):
        parse("---\nname: x\ndescription: y\n\nBody with no closing fence.\n")


def test_a_line_outside_the_subset_names_itself() -> None:
    with pytest.raises(InvalidSkill, match="not `key: value`"):
        parse("---\nname: x\nthis is not a mapping\n---\n\nBody.\n")


def test_a_list_item_with_no_key_above_it_is_refused() -> None:
    with pytest.raises(InvalidSkill, match="no key above it"):
        parse("---\n  - orphan\nname: x\n---\n\nBody.\n")


def test_no_frontmatter_yields_the_whole_text_as_body() -> None:
    header, body = split("Just a markdown file.\n")
    assert header == ""
    assert body.strip() == "Just a markdown file."


def test_render_round_trips_through_parse() -> None:
    text = render({"name": "x", "description": "y", "tags": ["a", "b"]}, "The body.")
    data, body = parse(text)

    assert data == {"name": "x", "description": "y", "tags": ["a", "b"]}
    assert body.strip() == "The body."


def test_render_flattens_a_multiline_value() -> None:
    """A newline in a scalar is outside the subset, so writing one would produce
    a file the loader then refuses to read back."""
    text = render({"name": "x", "description": "line one\nline two"}, "Body.")
    data, _ = parse(text)
    assert data["description"] == "line one line two"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def test_a_directory_skill_loads(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "fee-rules", VALID)
    skill = load_skill(path, SkillLayer.USER, embed=False)

    assert skill.name == "fee-rules"
    assert skill.layer is SkillLayer.USER
    assert "capture" in skill.body
    assert skill.tags == ["fees", "billing"]


def test_a_bare_markdown_file_loads_the_same_way(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "fee-rules", VALID, directory=False)
    skill = load_skill(path, SkillLayer.PROJECT, embed=False)

    assert skill.name == "fee-rules"
    assert skill.layer is SkillLayer.PROJECT


def test_the_name_falls_back_to_the_filename(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "inferred", "---\ndescription: Has no name field\n---\n\nBody.\n")
    assert load_skill(path, SkillLayer.USER, embed=False).name == "inferred"


def test_a_missing_description_is_refused_by_name(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "x", "---\nname: x\n---\n\nBody.\n")
    with pytest.raises(InvalidSkill, match="description"):
        load_skill(path, SkillLayer.USER, embed=False)


def test_frontmatter_with_no_instructions_is_refused(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "x", "---\nname: x\ndescription: y\n---\n")
    with pytest.raises(InvalidSkill, match="no instructions"):
        load_skill(path, SkillLayer.USER, embed=False)


def test_an_unusable_name_is_refused(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "x", "---\nname: Bad Name!\ndescription: y\n---\n\nBody.\n")
    with pytest.raises(InvalidSkill, match="not a usable skill name"):
        load_skill(path, SkillLayer.USER, embed=False)


def test_the_description_is_searchable(tmp_path: Path) -> None:
    """It lives in the frontmatter, not the body, and it is the one line written
    to be matched against -- so without prepending it, it is the one line that
    never gets searched."""
    path = write_skill(tmp_path, "fee-rules", VALID)
    skill = load_skill(path, SkillLayer.USER)
    assert any("waived" in chunk.text for chunk in skill.chunks)


# --------------------------------------------------------------------------- #
# The executable-payload boundary
# --------------------------------------------------------------------------- #
def test_a_skill_shipping_a_script_is_refused_and_names_the_file(tmp_path: Path) -> None:
    """Milestone 6's trust boundary, enforced at load rather than documented.

    A skill is instruction text. Refused rather than ignored, so the author finds
    out now instead of discovering later that half their skill never ran.
    """
    path = write_skill(tmp_path, "sneaky", VALID)
    (path / "helper.py").write_text("import os\n", encoding="utf-8")

    with pytest.raises(InvalidSkill, match="helper.py"):
        load_skill(path, SkillLayer.USER, embed=False)


@pytest.mark.parametrize("filename", ["run.sh", "go.ps1", "x.bat", "mod.pyc", "lib.so", "a.exe"])
def test_every_executable_suffix_is_caught(tmp_path: Path, filename: str) -> None:
    path = write_skill(tmp_path, f"s-{filename.replace('.', '-')}", VALID)
    (path / filename).write_text("", encoding="utf-8")
    assert executable_payload(path) == [filename]


def test_a_nested_script_is_caught_too(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "nested", VALID)
    (path / "lib").mkdir()
    (path / "lib" / "helper.py").write_text("", encoding="utf-8")
    with pytest.raises(InvalidSkill, match="helper.py"):
        load_skill(path, SkillLayer.USER, embed=False)


def test_a_markdown_only_bundle_is_fine(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "docs", VALID)
    (path / "reference.md").write_text("More prose.\n", encoding="utf-8")
    assert load_skill(path, SkillLayer.USER, embed=False).name == "fee-rules"


# --------------------------------------------------------------------------- #
# Discovery and layering
# --------------------------------------------------------------------------- #
def test_a_directory_wins_over_a_same_named_file(tmp_path: Path) -> None:
    write_skill(tmp_path, "dup", VALID)
    write_skill(tmp_path, "dup", VALID, directory=False)
    assert [p.name for p in skill_paths(tmp_path)] == ["dup"]


def test_a_missing_root_is_empty_not_an_error(tmp_path: Path) -> None:
    assert skill_paths(tmp_path / "nope") == []


def _registry(monkeypatch, builtin: Path, user: Path, project: Path) -> SkillRegistry:
    from src.core.skills import registry as registry_module

    monkeypatch.setitem(registry_module.ROOTS, SkillLayer.BUILTIN, lambda: builtin)
    monkeypatch.setitem(registry_module.ROOTS, SkillLayer.USER, lambda: user)
    monkeypatch.setitem(registry_module.ROOTS, SkillLayer.PROJECT, lambda: project)
    return SkillRegistry()


def test_a_more_specific_layer_shadows_a_less_specific_one(tmp_path: Path, monkeypatch) -> None:
    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    write_skill(builtin, "shared", VALID.replace("A fee is applied", "BUILTIN body"))
    write_skill(user, "shared", VALID.replace("A fee is applied", "USER body"))

    registry = _registry(monkeypatch, builtin, user, project)
    resolved = registry.get("fee-rules")

    assert resolved is not None
    assert resolved.layer is SkillLayer.USER
    assert "USER body" in resolved.body


def test_the_shadowed_copy_is_still_listed_with_its_overrider(tmp_path: Path, monkeypatch) -> None:
    """Otherwise editing the built-in appears to do nothing and there is no way
    to find out why."""
    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    write_skill(builtin, "shared", VALID)
    write_skill(user, "shared", VALID)

    registry = _registry(monkeypatch, builtin, user, project)
    listed = registry.list(include_shadowed=True)

    shadowed = [skill for skill in listed if skill.shadowed_by]
    assert len(shadowed) == 1
    assert shadowed[0].layer is SkillLayer.BUILTIN
    assert shadowed[0].shadowed_by == "user"


def test_project_beats_user(tmp_path: Path, monkeypatch) -> None:
    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    write_skill(user, "shared", VALID)
    write_skill(project, "shared", VALID)

    registry = _registry(monkeypatch, builtin, user, project)
    assert registry.get("fee-rules").layer is SkillLayer.PROJECT


def test_a_malformed_skill_is_skipped_not_fatal(tmp_path: Path, monkeypatch) -> None:
    """One bad file on disk must not stop the app answering questions -- the same
    rule the connection store follows for a corrupt connections.json."""
    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    write_skill(user, "good", VALID)
    write_skill(user, "broken", "---\nname: broken\n---\n\nNo description.\n")

    registry = _registry(monkeypatch, builtin, user, project)
    names = [skill.name for skill in registry.list()]

    assert names == ["fee-rules"]


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
def test_search_finds_the_relevant_skill_without_an_encoder(tmp_path: Path, monkeypatch) -> None:
    """The suite forces the hashing fallback, so this is the air-gapped path.

    It is coverage-scored rather than cosine-scored for exactly this case: the
    hashing encoder ranked an unrelated question *above* a relevant one.
    """
    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    write_skill(
        user,
        "fees",
        "---\nname: fees\ndescription: How fees are applied and waived\n---\n\nA fee is charged at capture.\n",
    )
    write_skill(
        user,
        "cohorts",
        "---\nname: cohorts\ndescription: Cohort retention and churn\n---\n\nAnchor the cohort on first purchase.\n",
    )

    registry = _registry(monkeypatch, builtin, user, project)

    assert [m.skill.name for m in registry.search("how are fees applied")] == ["fees"]
    assert [m.skill.name for m in registry.search("cohort retention")] == ["cohorts"]


def test_an_unrelated_question_matches_nothing(tmp_path: Path, monkeypatch) -> None:
    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    write_skill(user, "fees", VALID)

    registry = _registry(monkeypatch, builtin, user, project)
    assert registry.search("what is the capital of france") == []


def test_at_most_one_passage_per_skill(tmp_path: Path, monkeypatch) -> None:
    body = "\n\n".join(f"Fee paragraph {index} about fees and billing charges." for index in range(12))
    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    write_skill(user, "fees", f"---\nname: fees\ndescription: Fees and billing\n---\n\n{body}\n")

    registry = _registry(monkeypatch, builtin, user, project)
    matches = registry.search("fees and billing charges", limit=5)

    assert len({match.skill.name for match in matches}) == len(matches)


def test_the_rendered_block_stays_inside_its_budget(tmp_path: Path, monkeypatch) -> None:
    """The cap covers the whole block, including the preamble and headings.

    Charging only the bodies is how an 1,800-character block measured 2,200.
    """
    long_body = "\n\n".join(f"Cohort paragraph {index} about retention and churn." for index in range(60))
    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    for name in ("alpha", "beta"):
        write_skill(user, name, f"---\nname: {name}\ndescription: Retention and churn\n---\n\n{long_body}\n")

    registry = _registry(monkeypatch, builtin, user, project)
    matches = registry.search("retention and churn", limit=2)
    block = registry.render_block(matches, limit=1200)

    assert len(matches) == 2
    assert len(block) <= 1200
    assert "… [truncated]" in block


def test_no_matches_renders_nothing_at_all(tmp_path: Path, monkeypatch) -> None:
    registry = _registry(monkeypatch, tmp_path / "b", tmp_path / "u", tmp_path / "p")
    assert registry.render_block([]) == ""


def test_search_is_off_when_skills_are_disabled(tmp_path: Path, monkeypatch) -> None:
    from src.config import settings

    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    write_skill(user, "fees", VALID)
    registry = _registry(monkeypatch, builtin, user, project)

    monkeypatch.setattr(settings, "SKILLS_ENABLED", False)
    assert registry.search("how are fees applied") == []


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #
def test_a_written_skill_reads_back(tmp_path: Path, monkeypatch) -> None:
    registry = _registry(monkeypatch, tmp_path / "b", tmp_path / "u", tmp_path / "p")
    written = registry.write("new-skill", "What it is for", "The instructions.", tags=["a"])

    assert written.name == "new-skill"
    assert registry.get("new-skill").body == "The instructions."
    # Always the directory form, which is what Milestone 6 installs into.
    assert Path(written.path).name == "SKILL.md"


def test_a_builtin_cannot_be_written_or_deleted(tmp_path: Path, monkeypatch) -> None:
    """It lives in the checkout, so an edit would be lost on the next update.
    Refused with a reason rather than accepted and silently discarded."""
    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    write_skill(builtin, "shipped", VALID)
    registry = _registry(monkeypatch, builtin, user, project)

    with pytest.raises(SkillNotWritable, match="replaced on update"):
        registry.write("fee-rules", "d", "b", layer=SkillLayer.BUILTIN)
    with pytest.raises(SkillNotWritable, match="cannot be removed"):
        registry.delete("fee-rules")


def test_deleting_removes_the_empty_directory_but_not_a_used_one(tmp_path: Path, monkeypatch) -> None:
    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    registry = _registry(monkeypatch, builtin, user, project)

    registry.write("bare", "d", "b")
    assert registry.delete("bare") is True
    assert not (user / "bare").exists()

    registry.write("kept", "d", "b")
    (user / "kept" / "notes.md").write_text("mine\n", encoding="utf-8")
    assert registry.delete("kept") is True
    # The extra file was put there by the user; only a bare directory is removed.
    assert (user / "kept" / "notes.md").exists()


def test_deleting_something_absent_is_false_not_an_error(tmp_path: Path, monkeypatch) -> None:
    registry = _registry(monkeypatch, tmp_path / "b", tmp_path / "u", tmp_path / "p")
    removed = registry.delete("never-existed")
    assert removed is False


@pytest.mark.parametrize("name", ["", "Bad Name", "with/slash", "..", "-leading", "x" * 65])
def test_unusable_names_are_refused(name: str) -> None:
    assert is_valid_skill_name(name) is False


@pytest.mark.parametrize("name", ["a", "fee-rules", "cohort_analysis", "v1.2", "abc123"])
def test_usable_names_are_accepted(name: str) -> None:
    assert is_valid_skill_name(name) is True


# --------------------------------------------------------------------------- #
# Defects found in review of the milestone-5 PR
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("opening", ["----", "-----", "---title"])
def test_a_markdown_rule_at_the_top_does_not_abort_the_scan(opening: str, tmp_path: Path, monkeypatch) -> None:
    """`split` tested a prefix in one place and exact equality in another.

    A bare `<name>.md` opening with `----` passed the prefix test and matched no
    line equal to `---`, so `next()` raised `StopIteration` — which `load_skill`
    does not catch and `_scan` does not either. One such file in any layer took
    every skill with it.
    """
    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    registry = _registry(monkeypatch, builtin, user, project)

    user.mkdir(parents=True)
    (user / "rule.md").write_text(f"{opening}\nnot frontmatter\n", encoding="utf-8")
    registry.write("survivor", "Still here", "Instructions.")

    # The malformed file is skipped for the reason it is actually wrong — no
    # required fields — and the valid skill beside it still loads.
    assert [skill.name for skill in registry.list()] == ["survivor"]


def test_clearing_user_skills_reaches_a_shadowed_one(tmp_path: Path, monkeypatch) -> None:
    """`list()` returns only resolved skills, so a user skill hidden behind a
    project one of the same name survived teardown and leaked into the next
    test. Removal goes by path, since `delete(name)` would resolve that name to
    the project copy and take the wrong file."""
    builtin, user, project = tmp_path / "b", tmp_path / "u", tmp_path / "p"
    registry = _registry(monkeypatch, builtin, user, project)

    registry.write("shared", "The user copy", "User instructions.")
    registry.write("shared", "The project copy", "Project instructions.", layer=SkillLayer.PROJECT)
    assert registry.get("shared").layer is SkillLayer.PROJECT

    registry.clear_user_skills()

    assert not (user / "shared").exists()
    assert (project / "shared" / "SKILL.md").exists()
