"""What a skill *is*, as inert data.

Deliberately JSON-safe and free of file handles, for the same reason
``security/sandbox/policy.py`` and ``connectors/spec.py`` are: this is the single
description of a unit of know-how, and everything else -- the loader, the
registry, the REST surface, the prompt block -- is a rendering of it. A ``Skill``
can be constructed, serialised and asserted on with nothing on disk.

**A skill is instruction text, never a code path.** Python inside a skill body is
illustrative: the model reads it, and anything it writes from it still goes
through ``_extract_code`` -> ``CodeGuard.scan`` -> the sandbox like any other
generated code. That boundary is enforced in :mod:`~src.core.skills.loader`
rather than described here, because Milestone 6 pulls skills from strangers'
repositories and a documented boundary would not survive that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np


#: Filename inside a skill *directory*. The convention this ecosystem already
#: uses, and what Milestone 6 will fetch from a repository.
SKILL_FILENAME = "SKILL.md"

#: A skill name addresses a directory and appears in a URL path, so it is
#: restricted rather than escaped -- the same reasoning as `is_valid_model_name`.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class SkillError(Exception):
    """Anything that went wrong reading or writing a skill."""


class InvalidSkill(SkillError):
    """A file that is present but cannot be read as a skill.

    Its own type because it is never fatal: the registry logs it and moves on, so
    one malformed file cannot stop the app answering questions.
    """


class SkillNotWritable(SkillError):
    """A write was aimed at a layer that does not accept one.

    Built-in skills live in the checkout, so an edit would be lost on the next
    update. The API turns this into a 409 with the reason rather than a silent
    no-op.
    """


class SkillLayer(StrEnum):
    """Where a skill came from, in ascending precedence.

    Order matters: :meth:`precedence` reads off this declaration, so adding a
    layer is one line here rather than a constant to keep in sync.
    """

    BUILTIN = "builtin"
    USER = "user"
    PROJECT = "project"

    @property
    def precedence(self) -> int:
        return list(SkillLayer).index(self)

    @property
    def writable(self) -> bool:
        """Whether a user edit to this layer survives.

        Built-in skills are part of the checkout; ``git pull`` would discard an
        edit made to one, so the write is refused instead of accepted and lost.
        """
        return self is not SkillLayer.BUILTIN

    @property
    def label(self) -> str:
        return {
            SkillLayer.BUILTIN: "Built-in",
            SkillLayer.USER: "User",
            SkillLayer.PROJECT: "Project",
        }[self]


def is_valid_skill_name(name: str) -> bool:
    return bool(NAME_PATTERN.match((name or "").strip()))


@dataclass
class SkillChunk:
    """One retrievable passage of a skill body.

    The same shape as :class:`~src.core.ingest.documents.DocumentChunk`, because
    skills go through the same retrieval path reference documents do -- and
    therefore degrade to lexical overlap identically when no encoder is loaded.
    """

    skill: str
    index: int
    text: str
    #: The encoder's own output type, so it can go straight back into
    #: `embedding_service.rank` without a conversion that would only be undone.
    embedding: np.ndarray | None = None


@dataclass
class Skill:
    """One unit of know-how, parsed and ready to retrieve."""

    name: str
    description: str
    body: str
    layer: SkillLayer = SkillLayer.USER
    path: str = ""
    tags: list[str] = field(default_factory=list)
    version: str = ""
    chunks: list[SkillChunk] = field(default_factory=list)
    #: Set by Milestone 6 when a skill came from a repository. Present now so an
    #: installed skill's stored shape does not change under it later.
    source_url: str | None = None
    pinned_sha: str | None = None
    #: Name of the layer that overrides this one, when a more specific layer
    #: defines the same name. The UI needs this to explain why editing the
    #: built-in copy changed nothing.
    shadowed_by: str | None = None

    @property
    def char_count(self) -> int:
        return len(self.body)

    def heading(self) -> str:
        """The one-line form used in a prompt block and in the trail."""
        return f"{self.name} — {self.description}" if self.description else self.name

    def summary(self) -> dict[str, Any]:
        """Everything the list view needs, without the body."""
        return {
            "name": self.name,
            "description": self.description,
            "layer": self.layer.value,
            "layer_label": self.layer.label,
            "path": self.path,
            "tags": list(self.tags),
            "version": self.version,
            "chars": self.char_count,
            "chunks": len(self.chunks),
            "writable": self.layer.writable,
            "source_url": self.source_url,
            "pinned_sha": self.pinned_sha,
            "shadowed_by": self.shadowed_by,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.summary(), "body": self.body}


@dataclass
class SkillMatch:
    """One retrieved passage, with the skill it came from."""

    skill: Skill
    text: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.skill.name,
            "layer": self.skill.layer.value,
            "score": round(self.score, 4),
            "text": self.text,
        }


__all__ = [
    "NAME_PATTERN",
    "SKILL_FILENAME",
    "InvalidSkill",
    "Skill",
    "SkillChunk",
    "SkillError",
    "SkillLayer",
    "SkillMatch",
    "SkillNotWritable",
    "is_valid_skill_name",
]
