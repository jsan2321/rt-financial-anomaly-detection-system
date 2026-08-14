"""
Correlation ID context management for distributed traceability across RT-FADS.
"""

import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Generator, Optional

CORRELATION_ID_HEADER = "X-Correlation-ID"

# Context variable storing the correlation ID for the current execution thread / async task
_correlation_id_ctx: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str:
    """
    Retrieve the current correlation ID from the context.
    If none is set, generates and sets a new UUIDv4.
    """
    cid = _correlation_id_ctx.get()
    if not cid:
        cid = str(uuid.uuid4())
        _correlation_id_ctx.set(cid)
    return cid


def set_correlation_id(correlation_id: Optional[str] = None) -> Token:
    """
    Explicitly set or bind a correlation ID in the context.
    If no correlation ID is provided, generates a new UUIDv4.
    """
    cid = correlation_id.strip() if correlation_id and correlation_id.strip() else str(uuid.uuid4())
    return _correlation_id_ctx.set(cid)


def reset_correlation_id(token: Token) -> None:
    """Reset the correlation ID context to its prior state using the given token."""
    _correlation_id_ctx.reset(token)


@contextmanager
def correlation_scope(correlation_id: Optional[str] = None) -> Generator[str, None, None]:
    """
    Context manager providing a scoped correlation ID.
    Restores the previous correlation ID upon exit.
    """
    token = set_correlation_id(correlation_id)
    try:
        yield get_correlation_id()
    finally:
        reset_correlation_id(token)
