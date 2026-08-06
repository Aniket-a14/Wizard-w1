"""Consent for a connection, over HTTP.

The general rule -- **an authenticated request from the user is itself the answer
to an `ask`** -- moved to :func:`src.core.permissions.authorize` when Milestone
6's skill install became its second caller. It reads only a ``PermissionState``
and was never connector-specific; a helper with two callers belongs with the
thing it operates on rather than with whoever needed it first. It is re-exported
here so no call site had to move with it.

What is left is the one rule that is genuinely about connections: what gets gated
is not *saving* a connection, which reaches nothing, but **opening** one -- the
moment rows enter the analysis and become reachable by generated code and by a
cloud-bound prompt.
"""

from __future__ import annotations

from src.core.permissions import Ruling, authorize, category_by_key

from .spec import ConnectionSpec


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
