"""
Standard Error Envelope schema and FastAPI response adapters.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Inner error payload containing code, message, correlation_id, and optional details."""
    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error description")
    correlation_id: str = Field(..., description="Trace correlation ID for error diagnosis")
    details: Optional[Any] = Field(default=None, description="Additional contextual error metadata or validation field errors")


class ErrorEnvelope(BaseModel):
    """Standard outer error envelope conforming to API contracts."""
    error: ErrorDetail

    @classmethod
    def create(
        cls,
        code: str,
        message: str,
        correlation_id: str,
        details: Optional[Any] = None,
    ) -> "ErrorEnvelope":
        return cls(
            error=ErrorDetail(
                code=code,
                message=message,
                correlation_id=correlation_id,
                details=details,
            )
        )


def create_error_envelope(
    code: str,
    message: str,
    correlation_id: str,
    details: Optional[Any] = None,
) -> Dict[str, Any]:
    """Helper creating standard error dictionary payload."""
    return ErrorEnvelope.create(
        code=code,
        message=message,
        correlation_id=correlation_id,
        details=details,
    ).model_dump()
