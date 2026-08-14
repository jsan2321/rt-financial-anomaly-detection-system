"""
Domain exception hierarchy for RT-FADS services.
Provides consistent HTTP status codes, error codes, and correlation tracking.
"""

from typing import Any, Dict, Optional
from shared.context.correlation import get_correlation_id


class RTFADSError(Exception):
    """Base exception class for all RT-FADS domain and runtime errors."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Any] = None,
        correlation_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        self.correlation_id = correlation_id or get_correlation_id()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "correlation_id": self.correlation_id,
                "details": self.details,
            }
        }


class ResourceNotFoundError(RTFADSError):
    """Raised when a requested resource does not exist (HTTP 404)."""

    def __init__(self, resource_type: str, resource_id: str, message: Optional[str] = None):
        msg = message or f"{resource_type} with ID '{resource_id}' not found."
        super().__init__(
            message=msg,
            code="NOT_FOUND",
            status_code=404,
            details={"resource_type": resource_type, "resource_id": resource_id},
        )


class ConflictError(RTFADSError):
    """Raised when a requested operation causes a state conflict or duplicate (HTTP 409)."""

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(
            message=message,
            code="CONFLICT",
            status_code=409,
            details=details,
        )


class InvalidStateTransitionError(ConflictError):
    """Raised when an entity transition violates lifecycle state guards (HTTP 409)."""

    def __init__(self, current_status: str, target_status: str, entity_id: str):
        super().__init__(
            message=(
                f"Cannot transition alert '{entity_id}' from '{current_status}' "
                f"to '{target_status}'. Transition is invalid or was superseded by a concurrent action."
            ),
            details={
                "entity_id": entity_id,
                "current_status": current_status,
                "target_status": target_status,
            },
        )
        self.code = "INVALID_STATE_TRANSITION"


class ValidationError(RTFADSError):
    """Raised when request payload fails domain or schema validation rules (HTTP 422)."""

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=422,
            details=details,
        )


class AuthenticationError(RTFADSError):
    """Raised when authentication credentials are missing, invalid, or expired (HTTP 401)."""

    def __init__(self, message: str = "Authentication credentials were not provided or are invalid."):
        super().__init__(
            message=message,
            code="UNAUTHORIZED",
            status_code=401,
        )


class AuthorizationError(RTFADSError):
    """Raised when an authenticated user lacks required permissions (HTTP 403)."""

    def __init__(self, message: str = "You do not have permission to perform this action."):
        super().__init__(
            message=message,
            code="FORBIDDEN",
            status_code=403,
        )


class RateLimitExceededError(RTFADSError):
    """Raised when client exceeds rate limit thresholds (HTTP 429)."""

    def __init__(self, message: str = "API rate limit exceeded. Please retry later."):
        super().__init__(
            message=message,
            code="RATE_LIMIT_EXCEEDED",
            status_code=429,
        )


class InfrastructureUnavailableError(RTFADSError):
    """Raised when backing storage (PostgreSQL, Redis) is temporarily unreachable (HTTP 503)."""

    def __init__(self, service_name: str, message: Optional[str] = None):
        msg = message or f"Backing dependency '{service_name}' is currently unavailable."
        super().__init__(
            message=msg,
            code="SERVICE_UNAVAILABLE",
            status_code=503,
            details={"dependency": service_name},
        )
