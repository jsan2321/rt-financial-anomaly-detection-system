"""
Unit tests for shared.errors (exceptions & ErrorEnvelope).
"""

from shared.context.correlation import correlation_scope
from shared.errors.envelope import ErrorDetail, ErrorEnvelope
from shared.errors.exceptions import (
    RTFADSError,
    ResourceNotFoundError,
    ConflictError,
    InvalidStateTransitionError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    RateLimitExceededError,
    InfrastructureUnavailableError,
)


def test_rtfads_error_base():
    with correlation_scope("err-trace-001"):
        err = RTFADSError(message="Something failed", code="INTERNAL_FAIL", status_code=500)
        assert err.message == "Something failed"
        assert err.code == "INTERNAL_FAIL"
        assert err.status_code == 500
        assert err.correlation_id == "err-trace-001"

        payload = err.to_dict()
        assert payload["error"]["code"] == "INTERNAL_FAIL"
        assert payload["error"]["correlation_id"] == "err-trace-001"


def test_domain_exceptions():
    # 404
    nf = ResourceNotFoundError("Transaction", "tx-999")
    assert nf.status_code == 404
    assert nf.code == "NOT_FOUND"
    assert nf.details == {"resource_type": "Transaction", "resource_id": "tx-999"}

    # 409
    conf = ConflictError("Duplicate request")
    assert conf.status_code == 409
    assert conf.code == "CONFLICT"

    # 409 - State Transition
    trans_err = InvalidStateTransitionError("PENDING", "APPROVED", "alt-123")
    assert trans_err.status_code == 409
    assert trans_err.code == "INVALID_STATE_TRANSITION"
    assert trans_err.details["entity_id"] == "alt-123"

    # 422
    val = ValidationError("Amount must be positive")
    assert val.status_code == 422
    assert val.code == "VALIDATION_ERROR"

    # 401
    auth = AuthenticationError()
    assert auth.status_code == 401
    assert auth.code == "UNAUTHORIZED"

    # 403
    forb = AuthorizationError()
    assert forb.status_code == 403
    assert forb.code == "FORBIDDEN"

    # 429
    rate = RateLimitExceededError()
    assert rate.status_code == 429
    assert rate.code == "RATE_LIMIT_EXCEEDED"

    # 503
    infra = InfrastructureUnavailableError("Redis")
    assert infra.status_code == 503
    assert infra.code == "SERVICE_UNAVAILABLE"


def test_error_envelope_creation():
    envelope = ErrorEnvelope.create(
        code="VALIDATION_ERROR",
        message="Invalid payload",
        correlation_id="cid-999",
        details={"field": "amount", "issue": "cannot be negative"},
    )
    assert envelope.error.code == "VALIDATION_ERROR"
    assert envelope.error.message == "Invalid payload"
    assert envelope.error.correlation_id == "cid-999"
    assert envelope.error.details == {"field": "amount", "issue": "cannot be negative"}
