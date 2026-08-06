"""Where a skill came from, as inert data.

This layer's ``spec.py``: no HTTP, no file handles, nothing that has to be
running. A URL is turned into a :class:`SkillSource` here and every later
question — which API path to ask for, what to show the user, what to re-resolve
on update — is answered off that object.

**A source is parsed, not sniffed.** ``github.com`` and ``gist.github.com`` are
matched explicitly and anything else is refused by name. Accepting an arbitrary
host would look more general and be strictly worse: the fetcher speaks the GitHub
REST API, so a URL from anywhere else resolves to requests that mean nothing at
the other end, and the failure surfaces as a confusing 404 rather than "that is
not a GitHub URL". ``SKILLS_REGISTRY_API`` exists for the one case that is really
the same thing wearing a different hostname — GitHub Enterprise — and it is a
setting rather than a pattern to match, because only the operator knows it.

The install record lives here too. It is what
:mod:`~src.core.skills.index` persists and what the UI renders as provenance, and
it is deliberately the *only* place that claim comes from — see
:func:`~src.core.skills.index.InstallIndex.overlay` for why a fetched file's own
frontmatter is not trusted to describe its origin.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


#: The two hosts this understands, plus whatever ``SKILLS_REGISTRY_API`` points
#: at. Checked case-insensitively and with any ``www.`` prefix removed.
GITHUB_HOSTS = frozenset({"github.com"})
GIST_HOSTS = frozenset({"gist.github.com"})

#: A commit SHA, as GitHub returns it. Used to tell a pinned ref from a symbolic
#: one, so ``update`` can report "already pinned to a commit" honestly.
SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")

#: Owner, repository and gist ids reach a URL path, so they are restricted rather
#: than escaped — the same reasoning as ``is_valid_model_name`` and
#: ``is_valid_skill_name``. A path segment starting with ``-`` could be read as a
#: flag by something downstream; requiring an alphanumeric first character is the
#: whole story.
SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

#: A ref may contain slashes (``release/1.2``) but must not climb out of the URL
#: it is interpolated into.
REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


class SourceError(ValueError):
    """A URL that cannot be read as a skill source, with the reason."""


def _clean_host(netloc: str) -> str:
    host = netloc.split("@")[-1].split(":")[0].strip().lower()
    return host[4:] if host.startswith("www.") else host


def _check_segment(value: str, what: str) -> str:
    if not SEGMENT_PATTERN.match(value):
        raise SourceError(f"'{value}' is not a usable {what}.")
    return value


def _check_path(value: str) -> str:
    """Rejects a path that would climb out of the repository it addresses.

    ``..`` never reaches the filesystem here — content arrives over an API and
    only ``SKILL.md`` is ever written — but a traversal segment in a path is a
    statement of intent, and the honest answer to it is a refusal rather than a
    request that happens not to work.
    """
    cleaned = value.strip("/")
    if not cleaned:
        return ""
    parts = [part for part in cleaned.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise SourceError(f"'{value}' contains a path segment that climbs out of the repository.")
    for part in parts:
        _check_segment(part, "path segment")
    return "/".join(parts)


@dataclass(frozen=True)
class SkillSource:
    """A resolved-enough description of where to fetch from.

    ``ref`` is what the *user* asked for — a branch, a tag, a SHA, or empty
    meaning the repository's default branch. It is stored and re-resolved on
    update; the pin that comes out of resolving it is kept separately, because
    "pin, don't track" is exactly the statement that those two are different
    things.
    """

    kind: str  # "repo" | "gist"
    owner: str = ""
    repo: str = ""
    ref: str = ""
    path: str = ""
    gist_id: str = ""
    #: The canonical https address of this source, **not** the string as typed.
    #: It is what the UI renders as provenance and what the permission grant is
    #: keyed on, and both want one spelling: `acme/skills`, `acme/skills.git` and
    #: the full URL are the same repository, and keying a grant on the typing
    #: would ask again for a source already approved.
    url: str = ""

    @property
    def is_gist(self) -> bool:
        return self.kind == "gist"

    @property
    def slug(self) -> str:
        """How this source is named in a message to the user."""
        if self.is_gist:
            return f"gist:{self.gist_id}"
        base = f"{self.owner}/{self.repo}"
        return f"{base}/{self.path}" if self.path else base

    @property
    def ref_is_sha(self) -> bool:
        return bool(SHA_PATTERN.match(self.ref))

    def with_path(self, path: str) -> SkillSource:
        """The same source addressing a subdirectory of it.

        Used by discovery: one repository can hold several skills, and each
        installed skill records the path it actually came from so an update goes
        back to that directory rather than re-scanning the whole repository.
        """
        return SkillSource(
            kind=self.kind,
            owner=self.owner,
            repo=self.repo,
            ref=self.ref,
            path=_check_path(path),
            gist_id=self.gist_id,
            url=self.url,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "owner": self.owner,
            "repo": self.repo,
            "ref": self.ref,
            "path": self.path,
            "gist_id": self.gist_id,
            "url": self.url,
            "slug": self.slug,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillSource:
        return cls(
            kind=str(data.get("kind") or "repo"),
            owner=str(data.get("owner") or ""),
            repo=str(data.get("repo") or ""),
            ref=str(data.get("ref") or ""),
            path=str(data.get("path") or ""),
            gist_id=str(data.get("gist_id") or ""),
            url=str(data.get("url") or ""),
        )


def parse_source(url: str, *, extra_hosts: frozenset[str] | None = None) -> SkillSource:
    """Reads a GitHub repository or gist URL into a :class:`SkillSource`.

    Accepted, because these are the forms people actually paste:

    * ``https://github.com/owner/repo``            (and with ``.git``)
    * ``https://github.com/owner/repo/tree/<ref>/<path>``
    * ``https://github.com/owner/repo/blob/<ref>/<path>/SKILL.md``
    * ``owner/repo`` and ``owner/repo@<ref>``      — the shorthand a CLI invites
    * ``https://gist.github.com/<user>/<id>``      (and without the user segment)

    A ``blob`` URL pointing straight at ``SKILL.md`` resolves to the directory
    containing it. That is not tidying up after the user: clicking a skill file in
    the GitHub UI and copying the address bar is the most likely way anyone
    obtains one of these URLs, and refusing it would fail the common case to
    enforce a distinction the fetcher does not care about.
    """
    raw = (url or "").strip()
    if not raw:
        raise SourceError("Give a GitHub repository or gist URL.")

    # `owner/repo` and `owner/repo@ref` have no scheme, so they are recognised
    # before urlparse, which would read `owner` as the scheme of `owner/repo@ref`.
    if "://" not in raw and not raw.startswith("//"):
        shorthand, _, ref = raw.partition("@")
        parts = [part for part in shorthand.strip("/").split("/") if part]
        if len(parts) == 2 and "." not in parts[0]:
            return _repo_source(parts[0], parts[1], ref.strip(), "", "github.com")
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    host = _clean_host(parsed.netloc)
    if not host:
        raise SourceError(f"'{url}' is not a URL.")

    segments = [segment for segment in parsed.path.split("/") if segment]

    if host in GIST_HOSTS:
        if not segments:
            raise SourceError("That gist URL has no gist id in it.")
        # `gist.github.com/<user>/<id>` and `gist.github.com/<id>` are both real.
        gist_id = _check_segment(segments[-1], "gist id")
        return SkillSource(kind="gist", gist_id=gist_id, url=f"https://gist.github.com/{gist_id}")

    allowed = GITHUB_HOSTS | (extra_hosts or frozenset())
    if host not in allowed:
        raise SourceError(
            f"'{host}' is not a GitHub host. Skills are installed from github.com or gist.github.com — "
            "set SKILLS_REGISTRY_API if you use GitHub Enterprise."
        )

    if len(segments) < 2:
        raise SourceError(f"'{url}' does not name a repository. Expected github.com/owner/repo.")

    owner = _check_segment(segments[0], "repository owner")
    repo = _check_segment(segments[1].removesuffix(".git"), "repository name")

    ref = ""
    path = ""
    if len(segments) > 2:
        marker = segments[2]
        if marker not in {"tree", "blob"}:
            raise SourceError(
                f"'{url}' is not a repository or directory URL. Expected github.com/owner/repo "
                "or github.com/owner/repo/tree/<branch>/<path>."
            )
        if len(segments) < 4:
            raise SourceError(f"'{url}' has a '{marker}' segment but no branch, tag or commit after it.")
        ref = segments[3]
        rest = segments[4:]
        # A URL pointing at the file itself names the directory holding it.
        if marker == "blob" and rest and rest[-1].lower().endswith((".md", ".markdown")):
            rest = rest[:-1]
        path = "/".join(rest)

    return _repo_source(owner, repo, ref, path, host)


def _repo_source(owner: str, repo: str, ref: str, path: str, host: str) -> SkillSource:
    cleaned_ref = (ref or "").strip()
    if cleaned_ref and not REF_PATTERN.match(cleaned_ref):
        raise SourceError(f"'{ref}' is not a usable branch, tag or commit.")

    clean_owner = _check_segment(owner, "repository owner")
    clean_repo = _check_segment(repo.removesuffix(".git"), "repository name")
    clean_path = _check_path(path)

    url = f"https://{host}/{clean_owner}/{clean_repo}"
    if cleaned_ref:
        url = f"{url}/tree/{cleaned_ref}" + (f"/{clean_path}" if clean_path else "")
    elif clean_path:
        url = f"{url}/tree/HEAD/{clean_path}"

    return SkillSource(
        kind="repo",
        owner=clean_owner,
        repo=clean_repo,
        ref=cleaned_ref,
        path=clean_path,
        url=url,
    )


@dataclass
class InstallRecord:
    """What this machine knows about a skill it installed from somewhere else.

    Persisted by :mod:`~src.core.skills.index`. ``ref`` and ``sha`` are both kept
    and they are not the same fact: ``ref`` is the moving thing the user chose to
    follow, ``sha`` is the immovable thing currently installed. ``update``
    re-resolves the first and replaces the second, which is the whole of "pin,
    don't track" in two fields.
    """

    name: str
    source: SkillSource
    sha: str
    installed_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def short_sha(self) -> str:
        return self.sha[:7]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source.to_dict(),
            "sha": self.sha,
            "short_sha": self.short_sha,
            "installed_at": self.installed_at,
            "updated_at": self.updated_at,
        }

    def summary(self) -> dict[str, Any]:
        """The provenance fields overlaid onto a :class:`~src.core.skills.spec.Skill`."""
        return {
            "source_url": self.source.url,
            "source_ref": self.source.ref,
            "pinned_sha": self.sha,
            "installed_at": self.installed_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstallRecord:
        source = data.get("source")
        if not isinstance(source, dict):
            raise ValueError("An install record needs a source.")
        name = str(data.get("name") or "").strip().lower()
        sha = str(data.get("sha") or "").strip()
        if not name or not sha:
            raise ValueError("An install record needs a name and a commit.")
        now = time.time()
        return cls(
            name=name,
            source=SkillSource.from_dict(source),
            sha=sha,
            installed_at=float(data.get("installed_at") or now),
            updated_at=float(data.get("updated_at") or now),
        )


__all__ = [
    "GIST_HOSTS",
    "GITHUB_HOSTS",
    "InstallRecord",
    "SkillSource",
    "SourceError",
    "parse_source",
]
