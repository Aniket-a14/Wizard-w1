"""Reading a skill out of a GitHub repository or gist.

The only module in this package that reaches the network, kept separate for the
same reason ``security/sandbox/child.py`` is: everything else can then be tested
with nothing running, and the one part that cannot is small enough to read.

Why the Contents API and not a tarball
--------------------------------------
``GET /repos/{owner}/{repo}/contents/{path}?ref=<sha>`` returns either a JSON
directory listing or one file's base64 content. Downloading the repository
archive would be fewer requests and is the obvious choice, and it is the wrong
one here for three reasons:

* **The executable-payload refusal can be enforced from the listing, before a
  single byte of content is fetched.** That boundary is the whole trust model of
  this milestone, and enforcing it against names the server already told us costs
  nothing and cannot be raced.
* Nothing arbitrary is ever written to disk — only the ``SKILL.md`` text. No
  archive extraction means no zip-slip, no traversal handling, no symlinks, no
  decompression bomb.
* The listing tells us what is there before we commit to fetching it, so a
  repository with a hundred directories is refused by count rather than
  discovered by downloading it.

What it costs is one request per file and the unauthenticated rate limit of 60
per hour. That limit is reported with GitHub's own reset time rather than as a
generic failure, and a token lifts it.

Pinning happens first, in its own step
--------------------------------------
The ref the user gave — a branch, a tag, or nothing at all meaning the default
branch — is resolved to a commit SHA once, and every request afterwards carries
that SHA. Two requests against a moving branch could otherwise straddle a push
and produce a "pinned" install assembled from two different commits.

Everything here degrades into a stated failure. There is no path that hangs: a
timeout is a :class:`FetchError` naming the host and the timeout, which is what
the caller shows the user.
"""

from __future__ import annotations

import base64
import binascii
import time
from dataclasses import dataclass
from typing import Any, Protocol

from src.config import settings
from src.core.credentials import credential_store
from src.utils.logging import logger

from .source import SkillSource


#: Where the optional token is stored. **Namespaced with a colon on purpose.**
#: ``credential_store.providers_with_keys()`` filters out any key containing one,
#: precisely so a stored secret is not reported as a configured model provider —
#: a bare ``github`` key would appear on the models page as a provider somebody
#: had set up.
GITHUB_CREDENTIAL_KEY = "registry:github"

#: Sent on every request. The version header is what keeps a future breaking
#: change to the API from arriving unannounced in a minor release.
API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class FetchError(RuntimeError):
    """The fetch did not happen, with a sentence the user can act on."""


class RateLimited(FetchError):
    """GitHub refused because this machine has asked too often.

    Its own type because the remedy is specific and time-bound — wait, or add a
    token — and reporting it as a generic failure sends people looking for a
    problem with the URL they typed.
    """


@dataclass(frozen=True)
class RemoteEntry:
    """One entry in a fetched directory listing."""

    name: str
    path: str
    type: str  # "file" | "dir" | "symlink" | "submodule"
    size: int = 0

    @property
    def is_dir(self) -> bool:
        return self.type == "dir"

    @property
    def is_file(self) -> bool:
        return self.type == "file"


class Fetcher(Protocol):
    """What :mod:`~src.core.skills.install` needs from the network.

    A Protocol rather than a concrete client so the whole install flow — staging,
    review, approval, update, the diff — is exercised by the test suite against a
    fake, with no network and no skipped tests. The rule that no test touches the
    real network is not negotiable, and a subsystem that can only be tested by
    reaching out is a subsystem that stops being tested.
    """

    # `raise NotImplementedError` rather than the more familiar trailing `...`.
    # A bare Ellipsis is a statement that does nothing, which is exactly what
    # CodeQL's "statement has no effect" rule is for; the rule is right, and a
    # Protocol method is not an exception to it. Raising also keeps the declared
    # return types honest, which a docstring-only body does not.

    def resolve(self, source: SkillSource) -> str:
        """The commit SHA ``source.ref`` currently points at."""
        raise NotImplementedError

    def listing(self, source: SkillSource, sha: str) -> list[RemoteEntry]:
        """What is at ``source.path``, at that commit."""
        raise NotImplementedError

    def read(self, source: SkillSource, sha: str, path: str) -> str:
        """One text file's contents, at that commit."""
        raise NotImplementedError


class GitHubFetcher:
    """The real client. One ``httpx`` call per method, no state beyond the token."""

    def __init__(self, api_root: str | None = None, token: str | None = None):
        self._api_root = (api_root or settings.SKILLS_REGISTRY_API).rstrip("/")
        self._token = token if token is not None else credential_store.get(GITHUB_CREDENTIAL_KEY)

    # ------------------------------------------------------------------ #
    def _headers(self) -> dict[str, str]:
        headers = dict(API_HEADERS)
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        import httpx

        url = f"{self._api_root}/{path.lstrip('/')}"
        try:
            response = httpx.get(
                url,
                params=params,
                headers=self._headers(),
                timeout=settings.SKILLS_FETCH_TIMEOUT,
                follow_redirects=True,
            )
        except httpx.TimeoutException:
            raise FetchError(
                f"{self._api_root} did not answer within {settings.SKILLS_FETCH_TIMEOUT:.0f}s. "
                "Check the connection and try again."
            )
        except httpx.HTTPError as exc:
            raise FetchError(f"Could not reach {self._api_root}: {exc}")

        if response.status_code == 404:
            raise FetchError(
                "GitHub has nothing at that address. Check the URL, the branch, and — for a private "
                "repository — that a token with access to it is saved."
            )
        if response.status_code in {401, 403}:
            raise self._refusal(response)
        if response.status_code >= 400:
            raise FetchError(f"GitHub answered {response.status_code} for {path}.")

        try:
            return response.json()
        except ValueError:
            raise FetchError(f"GitHub returned something that is not JSON for {path}.")

    def _refusal(self, response: Any) -> FetchError:
        """Tells a spent rate limit apart from a genuine authorisation failure.

        The two arrive as the same status code and mean opposite things: one is
        "wait eleven minutes", the other is "this will never work without a
        token". ``X-RateLimit-Remaining: 0`` is what distinguishes them, and the
        reset timestamp turns "try later" into an actual time.
        """
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            reset = response.headers.get("X-RateLimit-Reset", "")
            try:
                wait = max(0, int(float(reset)) - int(time.time()))
                when = f" It resets in about {max(1, wait // 60)} minute(s)."
            except (TypeError, ValueError):
                when = ""
            hint = "" if self._token else " Saving a GitHub token raises the limit from 60 requests an hour to 5,000."
            return RateLimited(f"GitHub's rate limit for this machine is spent.{when}{hint}")

        return FetchError(
            "GitHub refused the request. A private repository needs a saved token with access to it."
            if not self._token
            else "GitHub refused the request. The saved token may lack access to that repository."
        )

    # ------------------------------------------------------------------ #
    def resolve(self, source: SkillSource) -> str:
        if source.is_gist:
            payload = self._get(f"gists/{source.gist_id}")
            history = payload.get("history") if isinstance(payload, dict) else None
            if isinstance(history, list) and history and isinstance(history[0], dict):
                version = str(history[0].get("version") or "").strip()
                if version:
                    return version
            raise FetchError("That gist did not report a revision, so there is nothing to pin to.")

        # `commits/{ref}` accepts a branch, a tag or a SHA and answers with the
        # commit, so one call covers every form of ref including "not given".
        ref = source.ref or self._default_branch(source)
        payload = self._get(f"repos/{source.owner}/{source.repo}/commits/{ref}")
        sha = str(payload.get("sha") or "").strip() if isinstance(payload, dict) else ""
        if not sha:
            raise FetchError(f"GitHub did not report a commit for '{ref}'.")
        return sha

    def _default_branch(self, source: SkillSource) -> str:
        payload = self._get(f"repos/{source.owner}/{source.repo}")
        branch = str(payload.get("default_branch") or "").strip() if isinstance(payload, dict) else ""
        if not branch:
            raise FetchError(f"Could not work out the default branch of {source.owner}/{source.repo}.")
        return branch

    def listing(self, source: SkillSource, sha: str) -> list[RemoteEntry]:
        if source.is_gist:
            return self._gist_listing(source, sha)

        payload = self._get(
            f"repos/{source.owner}/{source.repo}/contents/{source.path}".rstrip("/"),
            params={"ref": sha},
        )
        if isinstance(payload, dict):
            # A path naming a file answers with the file, not a one-item list.
            payload = [payload]
        if not isinstance(payload, list):
            raise FetchError("GitHub returned an unreadable directory listing.")

        entries = [
            RemoteEntry(
                name=str(item.get("name") or ""),
                path=str(item.get("path") or ""),
                type=str(item.get("type") or ""),
                size=int(item.get("size") or 0),
            )
            for item in payload
            if isinstance(item, dict) and item.get("name")
        ]
        if len(entries) > settings.SKILLS_FETCH_MAX_FILES:
            raise FetchError(
                f"That directory holds {len(entries)} entries, more than the {settings.SKILLS_FETCH_MAX_FILES} "
                "a skill source is allowed. Point at the skill's own directory rather than the whole repository."
            )
        return entries

    def _gist_path(self, source: SkillSource, sha: str) -> str:
        """A gist request that carries the pin, when there is one.

        ``gists/{id}`` answers with the *current* revision. Reading through it
        after pinning to ``history[0].version`` would record a commit that does
        not identify the bytes that were read — and an update check would then
        compare a stored SHA against a body fetched from HEAD, which is the
        "pin, don't track" guarantee quietly not holding for gists. The revision
        goes in the path, the way the API spells it.
        """
        return f"gists/{source.gist_id}/{sha}" if sha else f"gists/{source.gist_id}"

    def _gist_listing(self, source: SkillSource, sha: str) -> list[RemoteEntry]:
        payload = self._get(self._gist_path(source, sha))
        files = payload.get("files") if isinstance(payload, dict) else None
        if not isinstance(files, dict):
            raise FetchError("That gist has no files in it.")
        return [
            RemoteEntry(name=str(name), path=str(name), type="file", size=int((meta or {}).get("size") or 0))
            for name, meta in files.items()
        ]

    def read(self, source: SkillSource, sha: str, path: str) -> str:
        if source.is_gist:
            return self._gist_read(source, sha, path)

        payload = self._get(f"repos/{source.owner}/{source.repo}/contents/{path}", params={"ref": sha})
        if not isinstance(payload, dict):
            raise FetchError(f"'{path}' is a directory, not a file.")

        size = int(payload.get("size") or 0)
        if size > settings.SKILLS_FETCH_MAX_BYTES:
            raise FetchError(
                f"'{path}' is {size:,} bytes, over the {settings.SKILLS_FETCH_MAX_BYTES:,}-byte ceiling "
                "for a skill file."
            )

        encoding = str(payload.get("encoding") or "")
        content = str(payload.get("content") or "")
        if encoding != "base64":
            # Over ~1 MB the Contents API stops inlining and reports no encoding.
            # The size check above catches that first; this is the honest answer
            # if the ceiling is ever raised past it.
            raise FetchError(f"GitHub did not inline the contents of '{path}'.")
        return _decode(content, path)

    def _gist_read(self, source: SkillSource, sha: str, path: str) -> str:
        payload = self._get(self._gist_path(source, sha))
        files = payload.get("files") if isinstance(payload, dict) else None
        entry = files.get(path) if isinstance(files, dict) else None
        if not isinstance(entry, dict):
            raise FetchError(f"That gist has no file called '{path}'.")

        # The same ceiling the repository path applies. `truncated` is the gist
        # API's own limit and sits around 1 MB, so checking only that would
        # accept a file four times over the configured maximum.
        size = int(entry.get("size") or 0)
        if size > settings.SKILLS_FETCH_MAX_BYTES:
            raise FetchError(
                f"'{path}' is {size:,} bytes, over the {settings.SKILLS_FETCH_MAX_BYTES:,}-byte ceiling "
                "for a skill file."
            )
        if entry.get("truncated"):
            raise FetchError(f"'{path}' is too large for the gist API to return in full.")
        return str(entry.get("content") or "")


def _decode(content: str, path: str) -> str:
    try:
        raw = base64.b64decode(content, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise FetchError(f"Could not decode '{path}': {exc}")
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def default_fetcher() -> Fetcher:
    """The client the routes and the CLI use, built per call.

    Per call rather than cached, because the token can be saved while the backend
    is running and a cached client would keep using the rate limit it started
    with. One object per install is not a cost worth optimising.
    """
    return GitHubFetcher()


def token_saved() -> bool:
    """Whether a GitHub token is stored, for the UI to say so without reading it."""
    return credential_store.has(GITHUB_CREDENTIAL_KEY)


def save_token(token: str) -> bool:
    cleaned = (token or "").strip()
    if not cleaned:
        removed = credential_store.delete(GITHUB_CREDENTIAL_KEY)
        logger.info("Removed the stored GitHub token")
        return removed
    return credential_store.set(GITHUB_CREDENTIAL_KEY, cleaned)


__all__ = [
    "API_HEADERS",
    "GITHUB_CREDENTIAL_KEY",
    "FetchError",
    "Fetcher",
    "GitHubFetcher",
    "RateLimited",
    "RemoteEntry",
    "default_fetcher",
    "save_token",
    "token_saved",
]
