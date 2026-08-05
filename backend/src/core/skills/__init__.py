"""Skills — reusable, inspectable know-how the agent can cite.

The session's other memories are private and opaque: the semantic cache, working
memory and trajectories all shape what the agent does without anyone being able
to read, edit or name them. A skill is the same idea made legible -- a markdown
file with frontmatter, in a layered location, retrieved through the same path
reference documents already use.

Layout mirrors ``core/connectors/`` and ``security/sandbox/``: inert data in
:mod:`spec`, a pure parser in :mod:`frontmatter`, one-file reading in
:mod:`loader`, the layered store in :mod:`registry`, and the promotion pipeline
in :mod:`promotion`. Most of it is testable with nothing on disk and no model
loaded.
"""

from .promotion import Candidate, record_recovery, record_success
from .registry import skill_registry
from .spec import InvalidSkill, Skill, SkillError, SkillLayer, SkillMatch, SkillNotWritable


__all__ = [
    "Candidate",
    "InvalidSkill",
    "Skill",
    "SkillError",
    "SkillLayer",
    "SkillMatch",
    "SkillNotWritable",
    "record_recovery",
    "record_success",
    "skill_registry",
]
