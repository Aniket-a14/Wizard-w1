"""The ``---`` frontmatter block at the top of a ``SKILL.md``.

A restricted YAML subset, parsed here rather than by PyYAML. Two reasons, and the
second is the one that matters:

* PyYAML is not a declared dependency. It arrives transitively through langchain,
  so depending on it here would make the skills system break on an install that
  swapped the model layer -- the sort of coupling ``requirements.txt`` already
  has a comment about.
* Milestone 6 parses this on a file fetched from a stranger's repository.
  ``yaml.safe_load`` is safe in the sense that it will not construct arbitrary
  objects, but it will still happily return deeply nested structures, aliases
  that expand quadratically, and types nothing downstream expects. A parser that
  can only produce strings and lists of strings cannot be talked into any of it.

The subset, deliberately small enough to state completely:

    key: value
    key: "quoted value"
    key: [a, b, c]
    key:
      - a
      - b

Anything else raises :class:`~src.core.skills.spec.InvalidSkill` naming the line,
because a silently dropped field in a security-relevant header is worse than a
refused file.
"""

from __future__ import annotations

import re
from typing import Any

from .spec import InvalidSkill


FENCE = "---"

#: `key: value`, tolerating any indentation for the key itself so a hand-written
#: file with a stray leading space is still read.
KEY_LINE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(?P<value>.*)$")
LIST_ITEM = re.compile(r"^\s*-\s+(?P<value>.*)$")


def _unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def _inline_list(value: str) -> list[str] | None:
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    inner = text[1:-1].strip()
    if not inner:
        return []
    return [_unquote(part) for part in inner.split(",") if _unquote(part)]


def split(text: str) -> tuple[str, str]:
    """Separates the frontmatter block from the body.

    Returns ``("", text)`` when there is no block at all -- a plain markdown file
    with no header is not an error here, it is a file missing its required
    fields, which :func:`parse` is what reports.
    """
    normalised = (text or "").replace("\r\n", "\n").lstrip("﻿")
    if not normalised.lstrip().startswith(FENCE):
        return "", normalised

    lines = normalised.split("\n")
    start = next(index for index, line in enumerate(lines) if line.strip() == FENCE)
    for index in range(start + 1, len(lines)):
        if lines[index].strip() == FENCE:
            return "\n".join(lines[start + 1 : index]), "\n".join(lines[index + 1 :]).strip("\n")

    raise InvalidSkill("The frontmatter block opens with `---` but is never closed.")


def parse(text: str) -> tuple[dict[str, Any], str]:
    """Reads a ``SKILL.md`` into ``(frontmatter, body)``.

    Values are strings or lists of strings; there is no other type in the subset.
    A caller wanting a number gets the string and converts it, which is one less
    place for a version like ``1.10`` to be read as a float and rendered ``1.1``.
    """
    header, body = split(text)
    if not header.strip():
        return {}, body

    data: dict[str, Any] = {}
    pending_key: str | None = None

    for number, raw in enumerate(header.split("\n"), start=1):
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue

        item = LIST_ITEM.match(line)
        if item:
            if pending_key is None:
                raise InvalidSkill(f"Line {number} of the frontmatter is a list item with no key above it: {line!r}")
            value = _unquote(item.group("value"))
            if value:
                data[pending_key].append(value)
            continue

        match = KEY_LINE.match(line.strip())
        if not match:
            raise InvalidSkill(f"Line {number} of the frontmatter is not `key: value`: {line!r}")

        key = match.group("key").strip().lower().replace("-", "_")
        value = match.group("value").strip()

        if not value:
            # A bare `key:` opens a block list. It stays an empty list if no
            # items follow, which is a truthful reading of what was written.
            data[key] = []
            pending_key = key
            continue

        inline = _inline_list(value)
        data[key] = inline if inline is not None else _unquote(value)
        pending_key = None

    return data, body


def render(frontmatter: dict[str, Any], body: str) -> str:
    """The inverse of :func:`parse`, for writing a promoted skill to disk.

    Only what this module can read back is emitted -- a value containing a
    newline is collapsed, because a multi-line scalar is outside the subset and
    writing one would produce a file the loader then refuses.
    """
    lines = [FENCE]
    for key, value in frontmatter.items():
        if value is None or value == "":
            continue
        name = str(key).strip().lower().replace("_", "-")
        if isinstance(value, (list, tuple)):
            items = [str(item).strip() for item in value if str(item).strip()]
            if not items:
                continue
            lines.append(f"{name}: [{', '.join(items)}]")
        else:
            flat = " ".join(str(value).split())
            lines.append(f"{name}: {flat}")
    lines.append(FENCE)
    return "\n".join(lines) + "\n\n" + (body or "").strip() + "\n"


__all__ = ["FENCE", "parse", "render", "split"]
