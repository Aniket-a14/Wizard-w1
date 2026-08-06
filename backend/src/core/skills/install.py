"""Fetching a skill, holding it for review, and installing it once approved.

The shape of this milestone in one place. Four steps, and the order is the whole
security argument:

    parse -> resolve to a commit -> **stage** -> the user reads it -> approve

Nothing reaches the agent between the third step and the fifth. A staged skill
lives in ``config_dir()/skills-pending/``, a **sibling** of the user skills root
rather than a hidden directory inside it, so it cannot become live through one
bug in ``skill_paths``' ``iterdir`` -- and so "pending" is something a person can
see in a file browser, which is what it is.

Approval is where the file moves into ``config_dir()/skills/`` and the index
records where it came from. Before that moment the skill is inert text in a
directory nothing scans.

Pin, don't track
----------------
``update`` re-resolves the ref the user originally chose -- never a
newly-selected branch -- and compares commits. Same SHA: nothing is written and
it says so. Different SHA: the new body is fetched and a unified diff is
returned, and **still nothing is written**. Applying it takes a second, confirming
call. A skill therefore cannot change under someone between two questions, which
is the property the spec is asking for.

Installing is deliberately not an agent action
----------------------------------------------
It is reachable from the REST API and the CLI only. A fetched skill is untrusted
text that goes into the manager's prompt; if the manager could also install
skills, a fetched skill could instruct the agent to fetch more, and a consent
prompt does not close that because the prompt's wording would be written by the
thing under review. The human starts every install.
"""

from __future__ import annotations

import difflib
import hashlib
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import settings
from src.utils.appdirs import config_dir
from src.utils.logging import logger

from .fetch import Fetcher, FetchError, RemoteEntry, default_fetcher
from .index import install_index
from .loader import load_skill, offending_names
from .registry import skill_registry
from .source import InstallRecord, SkillSource, SourceError, parse_source
from .spec import SKILL_FILENAME, InvalidSkill, Skill, SkillError, SkillLayer


#: Where a repository conventionally keeps several skills. Looked in as well as
#: the root, because both layouts are common and asking the user which one their
#: repository uses is asking them a question we can answer ourselves.
SKILLS_SUBDIR = "skills"

#: Hostnames that mean "this is public GitHub, not an Enterprise install".
#: Compared against a parsed hostname, never searched for inside a URL.
PUBLIC_GITHUB_HOSTS = frozenset({"api.github.com", "github.com"})


class InstallError(SkillError):
    """An install that could not proceed, with the reason."""


def pending_root() -> Path:
    return config_dir() / "skills-pending"


@dataclass
class PendingSkill:
    """A fetched skill waiting to be read.

    ``id`` is derived from the source and the name rather than being a counter,
    so previewing the same URL twice replaces the staged copy instead of piling
    up near-identical cards.
    """

    id: str
    name: str
    description: str
    body: str
    source: SkillSource
    sha: str
    path: str = ""
    staged_at: float = field(default_factory=time.time)
    #: The name of an installed skill this would take precedence over, or that
    #: would take precedence over it. Surfaced before install, because finding out
    #: afterwards means wondering why nothing changed.
    conflicts_with: str | None = None
    conflict_layer: str | None = None

    @property
    def short_sha(self) -> str:
        return self.sha[:7]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "body": self.body,
            "chars": len(self.body),
            "source": self.source.to_dict(),
            "sha": self.sha,
            "short_sha": self.short_sha,
            "staged_at": self.staged_at,
            "conflicts_with": self.conflicts_with,
            "conflict_layer": self.conflict_layer,
        }


@dataclass
class UpdateResult:
    """What an update would do, or did."""

    name: str
    changed: bool
    sha: str
    previous_sha: str
    diff: str = ""
    applied: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "changed": self.changed,
            "sha": self.sha,
            "short_sha": self.sha[:7],
            "previous_sha": self.previous_sha,
            "previous_short_sha": self.previous_sha[:7],
            "diff": self.diff,
            "applied": self.applied,
            "message": self.message,
        }


def _pending_id(source: SkillSource, name: str) -> str:
    digest = hashlib.sha256(f"{source.slug}\n{name}".encode()).hexdigest()
    return digest[:16]


# ---------------------------------------------------------------------- #
# Fetching
# ---------------------------------------------------------------------- #
def _guard_listing(entries: list[RemoteEntry], where: str) -> None:
    """Applies the executable-payload refusal to a listing, before any download.

    The same rule ``loader.load_skill`` applies to a directory on disk, applied
    here to names GitHub has already told us. Refused rather than filtered: an
    author who shipped a helper script should find out that half their skill will
    never run, not discover it later.
    """
    payload = offending_names([entry.name for entry in entries if entry.is_file])
    if payload:
        raise InstallError(
            f"{where} ships executable files ({', '.join(payload[:5])}), which a skill may not do. "
            "A skill is instruction text; code it suggests is written by the agent and sandboxed "
            "like anything else it runs."
        )


def _candidate_dirs(entries: list[RemoteEntry]) -> list[RemoteEntry]:
    return [entry for entry in entries if entry.is_dir and not entry.name.startswith(".")]


def _has_skill_file(entries: list[RemoteEntry]) -> bool:
    return any(entry.is_file and entry.name.lower() == SKILL_FILENAME.lower() for entry in entries)


def _parse_fetched(text: str, source: SkillSource) -> tuple[str, str, str]:
    """Reads fetched text as a skill, without touching the registry or the disk.

    Reuses ``load_skill`` by writing to a temporary file rather than duplicating
    the frontmatter handling: the validation a fetched skill has to pass is
    exactly the validation a local one passes, and a second implementation of it
    is a second set of rules to keep in step.
    """
    import tempfile

    default = source.path.rsplit("/", 1)[-1] if source.path else source.repo or source.gist_id
    with tempfile.TemporaryDirectory(prefix="wizard-skill-") as tmp:
        directory = Path(tmp) / (default or "skill")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / SKILL_FILENAME).write_text(text, encoding="utf-8")
        try:
            skill = load_skill(directory, SkillLayer.USER, embed=False)
        except InvalidSkill as exc:
            raise InstallError(f"That is not a usable skill: {exc}")
    return skill.name, skill.description, skill.body


def discover(source: SkillSource, sha: str, fetcher: Fetcher) -> list[tuple[SkillSource, str]]:
    """Every skill at this source, as ``(source, SKILL.md text)`` pairs.

    Bounded to **one level** of subdirectory. A repository holding a hundred
    directories would otherwise cost a hundred requests to look at, and the
    layouts that actually exist -- one skill at the root, or several under
    ``skills/`` -- are both covered by looking one level down.
    """
    entries = fetcher.listing(source, sha)

    if _has_skill_file(entries):
        _guard_listing(entries, f"'{source.slug}'")
        return [(source, fetcher.read(source, sha, _skill_path(source, entries)))]

    roots: list[tuple[SkillSource, list[RemoteEntry]]] = [(source, entries)]
    subdir = next((entry for entry in entries if entry.is_dir and entry.name.lower() == SKILLS_SUBDIR), None)
    if subdir is not None:
        nested = source.with_path(subdir.path)
        roots.append((nested, fetcher.listing(nested, sha)))

    found: list[tuple[SkillSource, str]] = []
    for root, listing in roots:
        for entry in _candidate_dirs(listing):
            child = root.with_path(entry.path)
            child_entries = fetcher.listing(child, sha)
            if not _has_skill_file(child_entries):
                continue
            _guard_listing(child_entries, f"'{entry.name}'")
            found.append((child, fetcher.read(child, sha, _skill_path(child, child_entries))))

    if not found:
        raise InstallError(
            f"No {SKILL_FILENAME} found at {source.slug}. A skill source is a directory holding "
            f"{SKILL_FILENAME}, or a repository whose subdirectories each hold one."
        )
    return found


def _skill_path(source: SkillSource, entries: list[RemoteEntry]) -> str:
    """The path to fetch, spelled the way the listing spelled it.

    A gist's entries are bare filenames while a repository's carry the full path,
    and the file may be ``SKILL.md`` or ``skill.md``. Reading it back off the
    listing means neither difference has to be guessed at.
    """
    for entry in entries:
        if entry.is_file and entry.name.lower() == SKILL_FILENAME.lower():
            return entry.path or entry.name
    raise InstallError(f"'{source.slug}' has no {SKILL_FILENAME}.")


# ---------------------------------------------------------------------- #
# Staging
# ---------------------------------------------------------------------- #
def preview(url: str, fetcher: Fetcher | None = None) -> list[PendingSkill]:
    """Fetches a source, pins it, and stages every skill in it for review.

    Nothing is installed here and nothing is retrievable by the agent. The return
    value is what the review UI renders: the full body of each skill, the commit
    it is pinned to, and whether it would collide with something already present.
    """
    client = fetcher or default_fetcher()
    try:
        source = parse_source(url, extra_hosts=_enterprise_hosts())
    except SourceError as exc:
        raise InstallError(str(exc))

    sha = client.resolve(source)
    staged: list[PendingSkill] = []
    for child, text in discover(source, sha, client):
        name, description, body = _parse_fetched(text, child)
        pending = PendingSkill(
            id=_pending_id(child, name),
            name=name,
            description=description,
            body=body,
            source=child,
            sha=sha,
        )
        _note_conflict(pending)
        pending.path = str(_stage(pending, text))
        staged.append(pending)

    logger.info("Staged skills for review", source=source.slug, sha=sha[:7], count=len(staged))
    return staged


def _enterprise_hosts() -> frozenset[str]:
    """The GitHub Enterprise hostname implied by ``SKILLS_REGISTRY_API``, if any.

    Derived rather than configured twice. Somebody running Enterprise sets the API
    root; making them also list the web hostname would be two settings that must
    agree, and one of them would eventually not.

    **The host is parsed and compared exactly, never matched as a substring.**
    ``"api.github.com" in root`` reads as the same test and is not one:
    ``https://api.github.com.example.invalid`` contains that string while being a
    different host entirely, so the setting would be classified by a name that
    merely appears inside it. Which way that goes wrong is not the point — a
    hostname test that can be satisfied by a substring is the wrong test.
    """
    from urllib.parse import urlparse

    root = (settings.SKILLS_REGISTRY_API or "").strip()
    if not root:
        return frozenset()
    host = urlparse(root).netloc.split("@")[-1].split(":")[0].lower()
    if not host or host in PUBLIC_GITHUB_HOSTS:
        return frozenset()
    # Enterprise serves its API at `<host>/api/v3`, so the web host is the same.
    return frozenset({host, host.removeprefix("api.")})


def _note_conflict(pending: PendingSkill) -> None:
    existing = skill_registry.get(pending.name)
    if existing is None:
        return
    pending.conflicts_with = existing.name
    pending.conflict_layer = existing.layer.value


def _stage(pending: PendingSkill, text: str) -> Path:
    """Writes the fetched file into the pending root, byte-identical to upstream.

    Byte-identical matters: it is what makes the update diff exact rather than a
    diff against something re-rendered by this codebase. Nothing else from the
    source is written -- one file, whose name we chose.
    """
    directory = pending_root() / pending.id
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / SKILL_FILENAME).write_text(text, encoding="utf-8")
        (directory / "SOURCE.json").write_text(_stamp(pending), encoding="utf-8")
    except OSError as exc:
        raise InstallError(f"Could not stage the skill for review: {exc}")
    return directory / SKILL_FILENAME


def _stamp(pending: PendingSkill) -> str:
    import json

    return json.dumps(
        {
            "id": pending.id,
            "name": pending.name,
            "sha": pending.sha,
            "staged_at": pending.staged_at,
            "source": pending.source.to_dict(),
        },
        indent=2,
    )


def pending() -> list[PendingSkill]:
    """Everything staged and not yet approved or discarded.

    Read back off disk rather than held in memory, so a review survives a backend
    restart -- a fetch takes seconds and the reading it exists for does not.
    """
    root = pending_root()
    if not root.is_dir():
        return []

    import json

    items: list[PendingSkill] = []
    for directory in sorted(root.iterdir()):
        source_file = directory / SKILL_FILENAME
        stamp_file = directory / "SOURCE.json"
        if not (source_file.is_file() and stamp_file.is_file()):
            continue
        try:
            stamp = json.loads(stamp_file.read_text(encoding="utf-8"))
            text = source_file.read_text(encoding="utf-8")
            name, description, body = _parse_fetched(text, SkillSource.from_dict(stamp.get("source") or {}))
        except (OSError, ValueError, InstallError) as exc:
            logger.warning("Skipped an unreadable staged skill", path=str(directory), error=str(exc))
            continue

        item = PendingSkill(
            id=str(stamp.get("id") or directory.name),
            name=name,
            description=description,
            body=body,
            source=SkillSource.from_dict(stamp.get("source") or {}),
            sha=str(stamp.get("sha") or ""),
            path=str(source_file),
            staged_at=float(stamp.get("staged_at") or 0.0),
        )
        _note_conflict(item)
        items.append(item)
    return items


def get_pending(pending_id: str) -> PendingSkill | None:
    wanted = (pending_id or "").strip()
    return next((item for item in pending() if item.id == wanted), None)


def discard(pending_id: str) -> bool:
    """Throws a staged skill away without installing it."""
    item = get_pending(pending_id)
    if item is None:
        return False
    shutil.rmtree(pending_root() / item.id, ignore_errors=True)
    return True


def clear_pending() -> None:
    """Empties the staging root. For the test suite's teardown."""
    shutil.rmtree(pending_root(), ignore_errors=True)


# ---------------------------------------------------------------------- #
# Approval
# ---------------------------------------------------------------------- #
def approve(pending_id: str) -> Skill:
    """Moves a reviewed skill into the user layer and records where it came from.

    The index entry is written **after** the file, so a failed write leaves
    nothing claiming to be installed. The staged copy is removed last, so a
    crash between the two leaves the review standing rather than losing the fetch.
    """
    item = get_pending(pending_id)
    if item is None:
        raise InstallError(f"Nothing staged under id {pending_id!r}. It may already have been installed.")

    staged = Path(item.path)
    try:
        text = staged.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstallError(f"Could not read the staged skill: {exc}")

    target = skill_registry.path_for(item.name, SkillLayer.USER)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise InstallError(f"Could not install the skill: {exc}")

    install_index.record(InstallRecord(name=item.name, source=item.source, sha=item.sha, updated_at=time.time()))
    skill_registry.reload()
    shutil.rmtree(pending_root() / item.id, ignore_errors=True)

    installed = skill_registry.get(item.name)
    if installed is None:  # pragma: no cover - only reachable if the write raced a delete
        raise InstallError("The skill was installed but could not be read back.")
    logger.info("Installed a skill", skill=item.name, source=item.source.slug, sha=item.short_sha)
    return installed


# ---------------------------------------------------------------------- #
# Updating
# ---------------------------------------------------------------------- #
def check_update(name: str, fetcher: Fetcher | None = None) -> UpdateResult:
    """Re-resolves the stored ref and reports what would change. Writes nothing."""
    record = install_index.get(name)
    if record is None:
        raise InstallError(f"'{name}' was not installed from a repository, so there is nothing to update it from.")

    skill = skill_registry.get(record.name)
    if skill is None:
        raise InstallError(f"'{name}' is recorded as installed but is not on disk. Install it again.")

    client = fetcher or default_fetcher()
    sha = client.resolve(record.source)
    if sha == record.sha:
        return UpdateResult(
            name=record.name,
            changed=False,
            sha=sha,
            previous_sha=record.sha,
            message=f"Already at {record.short_sha}. Nothing to update.",
        )

    try:
        text = _fetch_body(record.source, sha, client)
    except FetchError as exc:
        raise InstallError(str(exc))

    # Diffed against the file on disk, not against what upstream looked like at
    # install time. Those differ the moment somebody edits an installed skill,
    # and diffing the wrong one would present their own edits as incoming changes.
    current = Path(skill.path).read_text(encoding="utf-8")
    diff = "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            text.splitlines(keepends=True),
            fromfile=f"{record.name} (installed, {record.short_sha})",
            tofile=f"{record.name} (upstream, {sha[:7]})",
        )
    )
    return UpdateResult(
        name=record.name,
        changed=True,
        sha=sha,
        previous_sha=record.sha,
        diff=diff or "(the file is identical; only the commit moved)",
        message=f"{record.short_sha} → {sha[:7]}.",
    )


def apply_update(name: str, fetcher: Fetcher | None = None) -> UpdateResult:
    """Fetches the new commit and replaces the installed file.

    Deliberately re-checks rather than trusting a SHA passed in from the client:
    the diff the user approved and the bytes written have to come from the same
    fetch, or the review guarantee is only as good as the round trip.
    """
    result = check_update(name, fetcher)
    if not result.changed:
        return result

    record = install_index.get(name)
    skill = skill_registry.get(name)
    if record is None or skill is None:  # pragma: no cover - check_update raises first
        raise InstallError(f"'{name}' is no longer installed.")

    client = fetcher or default_fetcher()
    text = _fetch_body(record.source, result.sha, client)
    try:
        Path(skill.path).write_text(text, encoding="utf-8")
    except OSError as exc:
        raise InstallError(f"Could not write the updated skill: {exc}")

    install_index.record(InstallRecord(name=record.name, source=record.source, sha=result.sha, updated_at=time.time()))
    skill_registry.reload()
    logger.info("Updated a skill", skill=record.name, sha=result.sha[:7], was=record.short_sha)
    result.applied = True
    result.message = f"Updated {record.name} from {record.short_sha} to {result.sha[:7]}."
    return result


def _fetch_body(source: SkillSource, sha: str, fetcher: Fetcher) -> str:
    entries = fetcher.listing(source, sha)
    _guard_listing(entries, f"'{source.slug}'")
    return fetcher.read(source, sha, _skill_path(source, entries))


def uninstall(name: str) -> bool:
    """Removes an installed skill and forgets where it came from."""
    removed = skill_registry.delete(name)
    install_index.forget(name)
    return removed


__all__ = [
    "SKILLS_SUBDIR",
    "InstallError",
    "PendingSkill",
    "UpdateResult",
    "apply_update",
    "approve",
    "check_update",
    "clear_pending",
    "discard",
    "discover",
    "get_pending",
    "pending",
    "pending_root",
    "preview",
    "uninstall",
]
