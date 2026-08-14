"""
Correlation ID ASGI middleware for FastAPI Gateway service.
Extracts X-Correlation-ID header or generates a new UUIDv4, setting the context variable.
"""

from typing import Callable
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from shared.context.correlation import CORRELATION_ID_HEADER, set_correlation_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware enforcing correlation ID extraction, propagation, and response tagging."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        incoming_corr_id = request.headers.get(CORRELATION_ID_HEADER)
        if incoming_corr_id:
            corr_id = incoming_corr_id.strip()
        else:
            corr_id = str(uuid.uuid4())

        set_correlation_id(corr_id)

        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = corr_id
        return response
