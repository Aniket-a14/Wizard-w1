"""Consent for a connection, over HTTP.

``orchestrator._permit`` is the gate for an action the *agent* chose: it has a
``RunState``, an emitter and a socket, so it can suspend the turn and ask. A user
clicking Import has none of those. Calling the broker anyway would not fail
outright -- ``emit`` tolerates a ``None`` emitter -- it would do something worse:
emit the question to nobody, wait out ``AGENT_CONSENT_TIMEOUT``, and return a
denial that was never actually declined.

So this is the REST-shaped sibling, and the rule it adds is one line:

    **an authenticated request from the user is itself the answer to an `ask`.**

Asking someone to confirm the button they just pressed is theatre, and worse, it
is training -- the fastest way to get a real prompt clicked through is to show
three meaningless ones first. What is gated is not *saving* a connection, which
reaches nothing; it is **opening** one, the moment rows enter the analysis and
become reachable by generated code and by a cloud-bound prompt.

`deny` is still terminal here. A user on `custom` who set `db_connect: deny`
cannot import by clicking, because `deny` is a real third state and not a
stronger flavour of `ask`.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.permissions import PermissionState, category_by_key, denial_reason

from .spec import ConnectionSpec


@dataclass(frozen=True)
class Ruling:
    """Whether a gated action may proceed over HTTP, and why not if it may not."""

    allowed: bool
    reason: str = ""


def authorize(permissions: PermissionState, category: str, subject: str) -> Ruling:
    """Applies the permission profile to a user-initiated action.

    Records the grant when it proceeds, which is what stops the *agent* being
    asked again about the same connection later in the session: the user has
    already answered this question, in the only way HTTP offers.
    """
    if permissions.granted(category, subject):
        return Ruling(allowed=True)

    ruling = permissions.ruling_for(category)
    if ruling == "deny":
        return Ruling(allowed=False, reason=denial_reason(category, subject, asked=False))

    # `allow` and `ask` both proceed -- see the module docstring. The grant is
    # recorded either way so the agent inherits the answer.
    permissions.grant(category, subject)
    return Ruling(allowed=True)


def require_writable(spec: ConnectionSpec) -> Ruling:
    """Whether write-back has been enabled for this specific connection.

    Checked *before* any consent prompt, deliberately. A question whose only
    permitted answer is no is worse than no question -- the same reasoning that
    keeps the install gate silent when ``SANDBOX_ALLOW_RUNTIME_PIP`` is off.
    """
    if spec.read_only:
        category = category_by_key("db_write")
        label = category.label.lower() if category else "write to a database"
        return Ruling(
            allowed=False,
            reason=(
                f"The connection '{spec.name}' is read-only, so permission to {label} was not requested. "
                "Enable write-back for this connection first — it is off until you turn it on, per connection."
            ),
        )
    return Ruling(allowed=True)


__all__ = ["Ruling", "authorize", "require_writable"]
