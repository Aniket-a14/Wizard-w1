"""The permission profile: what the agent may do without asking.

A dial orthogonal to depth. These tests pin the ruling matrix and the two rules
that must hold whatever the profile says: write-back is never covered by a
blanket approval, and an unknown category asks rather than allows.
"""

from __future__ import annotations

import pytest

from src.core.permissions import (
    CATEGORIES,
    PERMISSION_PROFILES,
    PermissionState,
    category_by_key,
    denial_reason,
    describe_categories,
    describe_profile,
    normalize,
    normalize_ruling,
    reserved_categories,
    unattended_reason,
)


LIVE_KEYS = ("library_install", "network", "workspace_write")


# ---------------------------------------------------------------- profiles --
def test_an_unknown_profile_falls_back_to_the_configured_default() -> None:
    """A stray value must not become a fourth, undefined profile."""
    assert normalize("not-a-profile") == "ask-always"
    assert normalize("") == "ask-always"
    assert normalize(None) == "ask-always"


def test_every_profile_has_a_description() -> None:
    """The picker shows consequences, so a profile with no sentence is unshippable."""
    for profile in PERMISSION_PROFILES:
        assert describe_profile(profile), profile


# ----------------------------------------------------------------- rulings --
@pytest.mark.parametrize("key", LIVE_KEYS)
def test_auto_approve_allows_the_ordinary_categories(key: str) -> None:
    assert PermissionState(profile="auto-approve").ruling_for(key) == "allow"


@pytest.mark.parametrize("key", LIVE_KEYS)
def test_ask_always_asks_about_everything(key: str) -> None:
    assert PermissionState(profile="ask-always").ruling_for(key) == "ask"


def test_custom_starts_from_each_categorys_own_default() -> None:
    """Untouched categories are not uniformly `ask`.

    Writing outside the workspace defaults to deny because that is what the code
    guard already did before a profile existed; making it `ask` would have turned
    a silent, safe refusal into a new interruption on upgrade.
    """
    state = PermissionState(profile="custom")
    assert state.ruling_for("library_install") == "ask"
    assert state.ruling_for("workspace_write") == "deny"


def test_custom_honours_a_per_category_choice() -> None:
    state = PermissionState(profile="custom")
    state.set_ruling("library_install", "allow")
    state.set_ruling("network", "deny")

    assert state.ruling_for("library_install") == "allow"
    assert state.ruling_for("network") == "deny"


def test_the_custom_matrix_survives_switching_profile_away_and_back() -> None:
    """Flipping to auto-approve for one question must not discard the matrix."""
    state = PermissionState(profile="custom")
    state.set_ruling("network", "deny")

    state.profile = "auto-approve"
    assert state.ruling_for("network") == "allow"

    state.profile = "custom"
    assert state.ruling_for("network") == "deny"


def test_an_unknown_category_asks_rather_than_allows() -> None:
    """A gate added without a matching row must interrupt, not wave itself through."""
    assert PermissionState(profile="auto-approve").ruling_for("teleport") == "ask"


def test_an_unparseable_ruling_falls_back_instead_of_raising() -> None:
    assert normalize_ruling("maybe") == "ask"
    assert normalize_ruling("maybe", fallback="deny") == "deny"
    assert normalize_ruling("allow") == "allow"


# --------------------------------------------------------------- write-back --
def test_write_back_is_never_covered_by_auto_approve() -> None:
    """The one category no blanket profile may include.

    Write-back changes data outside this machine, and the spec is explicit that
    it is enabled per connection, deliberately, once — not by picking a
    convenient profile.
    """
    assert PermissionState(profile="auto-approve").ruling_for("db_write") == "ask"


def test_write_back_cannot_be_set_to_allow_in_custom() -> None:
    state = PermissionState(profile="custom")
    with pytest.raises(ValueError, match="per connection"):
        state.set_ruling("db_write", "allow")
    assert state.ruling_for("db_write") == "ask"


def test_write_back_can_still_be_denied_outright() -> None:
    """`always_ask` is a ceiling, not a floor: refusing entirely stays available."""
    state = PermissionState(profile="custom")
    state.set_ruling("db_write", "deny")
    assert state.ruling_for("db_write") == "deny"


def test_setting_an_unknown_category_raises() -> None:
    with pytest.raises(ValueError, match="Unknown permission category"):
        PermissionState(profile="custom").set_ruling("teleport", "allow")


# ------------------------------------------------------------------ grants --
def test_a_grant_is_specific_to_its_subject() -> None:
    """Approving one library is not approving the next one."""
    state = PermissionState(profile="ask-always")
    state.grant("library_install", "lifelines")

    assert state.granted("library_install", "lifelines")
    assert not state.granted("library_install", "geopandas")
    assert not state.granted("network", "lifelines")


def test_allow_root_records_each_directory_once() -> None:
    state = PermissionState()
    state.allow_root("/data/reports")
    state.allow_root("/data/reports")
    state.allow_root("")

    assert state.extra_roots == ("/data/reports",)


# ------------------------------------------------------------- the catalog --
def test_only_tool_use_is_still_reserved() -> None:
    """Milestone 4 landed, so the two connector categories are live.

    `db_connect` and `db_write` now have real call sites -- the connections
    routes and the orchestrator's write gate -- so they no longer belong in the
    reserved set. `tool_use` still does: nothing reaches it until the skills
    system, and a category reported live with nothing behind it is the same
    class of untruth as a toolkit entry advertising a library that is not there.
    """
    reserved = {category.key for category in reserved_categories()}
    assert reserved == {"tool_use"}
    assert category_by_key("db_connect").live  # type: ignore[union-attr]
    assert category_by_key("db_write").live  # type: ignore[union-attr]
    for key in LIVE_KEYS:
        assert category_by_key(key) is not None
        assert category_by_key(key).live  # type: ignore[union-attr]


def test_every_category_carries_a_description_for_the_prompt() -> None:
    """The consent prompt says what is at stake, so an empty one is unshippable."""
    for category in CATEGORIES:
        assert category.description, category.key
        assert category.description != category.label


def test_describe_categories_reports_one_row_per_category() -> None:
    rows = describe_categories()
    assert [row["key"] for row in rows] == [category.key for category in CATEGORIES]


# ----------------------------------------------------------------- reasons --
def test_a_denial_says_which_lever_to_pull() -> None:
    """ "Denied" alone is undebuggable from the UI."""
    declined = denial_reason("library_install", "lifelines", asked=True)
    assert "lifelines" in declined
    assert "declined" in declined

    configured = denial_reason("library_install", "lifelines", asked=False)
    assert "permission profile" in configured


def test_an_unanswerable_ask_explains_that_it_was_never_asked() -> None:
    """A REST caller must not be told the user declined something never shown."""
    reason = unattended_reason("network", "inflation rate")
    assert "no way to ask" in reason
    assert "declined" not in reason
