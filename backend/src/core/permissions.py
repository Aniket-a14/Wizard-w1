"""How much the agent asks before it acts.

A dial orthogonal to depth. Depth decides how much the agent investigates;
this decides how much it asks first. The two compose freely: a `deep` run under
`auto-approve` and a `fast` run under `ask-always` do the same quality of work
and differ only in how often they stop to ask.

Consent used to be three unrelated special cases -- a process-wide plan gate, a
hardcoded web-search prompt, and a path check that could only ever say no. Here
it is one vocabulary of *categories*, so a new gated action is a row in
``CATEGORIES`` rather than another branch somewhere in the orchestrator.

Sits beside :mod:`src.core.data_mode` rather than under ``core/agent/`` because
the two are read together and answer adjacent questions. They are not the same
question, and rank in one order only: **data mode outranks the profile.** Mode
decides what is possible at all; the profile decides what is asked about among
what is already possible. No profile can consent to something the mode forbids.

Lives outside ``core/agent/`` for the same reason ``data_mode`` does: Milestone
4's connectors are gated by these categories without importing the orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config import settings


PERMISSION_PROFILES: tuple[str, ...] = ("auto-approve", "ask-always", "custom")

#: What a category resolves to for one action. `deny` is a real third state and
#: not a synonym for "ask and say no": it is the answer when there is nobody to
#: ask (a REST turn, an expired prompt), so every gate has a terminal ruling
#: rather than a reason to hang.
RULINGS: tuple[str, ...] = ("allow", "ask", "deny")


@dataclass(frozen=True)
class PermissionCategory:
    """One class of action the agent may need consent for."""

    key: str
    label: str
    #: Shown in the consent prompt and in the settings row, so it has to say what
    #: is at stake rather than restate the label.
    description: str
    #: Where `custom` starts before the user has touched this category.
    default: str = "ask"
    #: Never resolves to `allow` from the profile alone. The spec is explicit
    #: that write-back is opt-in per connection, so no blanket profile may cover
    #: it -- `auto-approve` means "approve the ordinary things", not "approve
    #: everything including the one thing that changes somebody else's data".
    always_ask: bool = False
    #: Whether anything in the running system reaches this gate yet. The
    #: connector categories are declared now so the profile a user sets today is
    #: still the profile in force when Milestone 4 lands, but the UI has to say
    #: they are inert rather than imply a connector exists.
    live: bool = True


CATEGORIES: tuple[PermissionCategory, ...] = (
    PermissionCategory(
        key="library_install",
        label="Install a library",
        description="Install a Python package the analysis needs but the runtime does not have.",
    ),
    PermissionCategory(
        key="network",
        label="Reach the internet",
        description="Any call that leaves this machine, including web search.",
    ),
    PermissionCategory(
        key="workspace_write",
        label="Write outside the workspace",
        description="Read or write a file outside this session's own directory.",
        default="deny",
    ),
    PermissionCategory(
        key="db_connect",
        label="Connect to a database",
        description="Open a read connection to an external database or warehouse.",
    ),
    PermissionCategory(
        key="db_write",
        label="Write to a database",
        description="Modify data in an external database or warehouse.",
        always_ask=True,
    ),
    PermissionCategory(
        key="tool_use",
        label="Use an unapproved tool",
        description="Use a tool or connector this session has not already authorised.",
        live=False,
    ),
)

_BY_KEY: dict[str, PermissionCategory] = {category.key: category for category in CATEGORIES}


def normalize(profile: str | None) -> str:
    """A known profile, falling back to the configured default."""
    candidate = (profile or "").strip().lower()
    return candidate if candidate in PERMISSION_PROFILES else settings.AGENT_PERMISSION_PROFILE


def normalize_ruling(ruling: str | None, fallback: str = "ask") -> str:
    candidate = (ruling or "").strip().lower()
    return candidate if candidate in RULINGS else fallback


def category_by_key(key: str) -> PermissionCategory | None:
    return _BY_KEY.get(key)


def reserved_categories() -> tuple[PermissionCategory, ...]:
    """Categories nothing reaches yet, so the UI can label them honestly."""
    return tuple(category for category in CATEGORIES if not category.live)


@dataclass
class PermissionState:
    """One session's answer to "what should I ask about?".

    Grants are session-scoped and deliberately not persisted. Consent given for
    this analysis is not consent given forever, and a grant that outlived the
    session would be a permission the user could no longer see to revoke.
    """

    profile: str = ""
    #: Per-category rulings, consulted only under `custom`. Kept when the profile
    #: switches away and back, so flipping to `auto-approve` to get one answer
    #: does not silently discard a matrix the user built.
    custom: dict[str, str] = field(default_factory=dict)
    #: (category, subject) pairs already approved this session.
    grants: set[tuple[str, str]] = field(default_factory=set)
    #: Directories the user has approved writing to, unioned into the code
    #: guard's allowed roots. The guard still decides; this is how it is told yes.
    extra_roots: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.profile = normalize(self.profile)

    def ruling_for(self, category_key: str) -> str:
        """What this profile says about a category, before any grant is checked."""
        category = _BY_KEY.get(category_key)
        if category is None:
            # An unknown category asks rather than allows. A gate added without a
            # matching row here should interrupt, not wave itself through.
            return "ask"

        profile = normalize(self.profile)
        if profile == "custom":
            ruling = normalize_ruling(self.custom.get(category_key), category.default)
        elif profile == "auto-approve":
            ruling = "allow"
        else:
            ruling = "ask"

        if category.always_ask and ruling == "allow":
            return "ask"
        return ruling

    def set_ruling(self, category_key: str, ruling: str) -> None:
        """Records a per-category choice, clamping one the category forbids."""
        category = _BY_KEY.get(category_key)
        if category is None:
            raise ValueError(f"Unknown permission category: {category_key}")
        resolved = normalize_ruling(ruling, category.default)
        if category.always_ask and resolved == "allow":
            raise ValueError(
                f"{category.label} cannot be set to allow. It is enabled per connection, "
                "once, deliberately -- not by a profile."
            )
        self.custom[category_key] = resolved

    def granted(self, category_key: str, subject: str = "") -> bool:
        return (category_key, subject) in self.grants

    def grant(self, category_key: str, subject: str = "") -> None:
        self.grants.add((category_key, subject))

    def allow_root(self, root: str) -> None:
        if root and root not in self.extra_roots:
            self.extra_roots = (*self.extra_roots, root)

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": normalize(self.profile),
            "custom": {category.key: self.ruling_for(category.key) for category in CATEGORIES},
            "grants": sorted(f"{key}:{subject}" if subject else key for key, subject in self.grants),
            "extra_roots": list(self.extra_roots),
        }


def describe_profile(profile: str) -> str:
    """One sentence, for the picker and for the settings readout."""
    return {
        "auto-approve": "The agent acts without asking, except where an action changes data outside this machine.",
        "ask-always": "The agent asks before installing anything, reaching the network, or writing outside its workspace.",
        "custom": "You decide per category what the agent may do without asking.",
    }.get(normalize(profile), "")


def describe_categories() -> list[dict[str, object]]:
    """The category table, for the settings matrix."""
    return [
        {
            "key": category.key,
            "label": category.label,
            "description": category.description,
            "always_ask": category.always_ask,
            "live": category.live,
        }
        for category in CATEGORIES
    ]


def denial_reason(category_key: str, subject: str = "", *, asked: bool) -> str:
    """Why an action did not happen, in words the user can act on."""
    category = _BY_KEY.get(category_key)
    label = category.label.lower() if category else category_key.replace("_", " ")
    what = f" ({subject})" if subject else ""
    if asked:
        return f"Permission to {label}{what} was declined, so that step did not run."
    return (
        f"Permission to {label}{what} is set to deny, so that step did not run. "
        "Change the permission profile to be asked instead."
    )


def unattended_reason(category_key: str, subject: str = "") -> str:
    """Why an `ask` became a `deny` when there was nobody to ask."""
    category = _BY_KEY.get(category_key)
    label = category.label.lower() if category else category_key.replace("_", " ")
    what = f" ({subject})" if subject else ""
    return (
        f"Permission to {label}{what} needs confirmation, and this request has no way to ask for it. "
        "Use the chat connection, or set that category to allow."
    )


__all__ = [
    "CATEGORIES",
    "PERMISSION_PROFILES",
    "RULINGS",
    "PermissionCategory",
    "PermissionState",
    "category_by_key",
    "denial_reason",
    "describe_categories",
    "describe_profile",
    "normalize",
    "normalize_ruling",
    "reserved_categories",
    "unattended_reason",
]
