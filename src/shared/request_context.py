"""Request-scoped identity of the authenticated user.

A dedicated ``contextvars.ContextVar`` — not structlog's — because "who is
making this request" is a correctness/authorization concern, deep tool code
depends on it being right, and it shouldn't ride along inside the logging
library's context (which exists for log enrichment and could be cleared or
reconfigured independently). Set once per request/session by the API auth
dependencies or the CLI entrypoint; read anywhere downstream (tools, nested
helpers) without threading a parameter through every call.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_current_user_id: ContextVar[Optional[str]] = ContextVar(
    "current_user_id", default=None
)


def set_current_user_id(user_id: Optional[str]) -> None:
    """Bind the authenticated user id for the remainder of this context
    (request, task, or CLI invocation)."""
    _current_user_id.set(user_id)


def current_user_id() -> Optional[str]:
    """The authenticated user id bound by ``set_current_user_id``; None when
    unauthenticated or unset."""
    return _current_user_id.get()


@contextmanager
def bound_user_id(user_id: Optional[str]) -> Iterator[None]:
    """Bind ``user_id`` for the duration of the ``with`` block; for tests
    that need to simulate an authenticated request."""
    token = _current_user_id.set(user_id)
    try:
        yield
    finally:
        _current_user_id.reset(token)
