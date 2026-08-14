"""
Unit tests for shared.context.correlation.
"""

import asyncio
import uuid
import pytest

from shared.context.correlation import (
    CORRELATION_ID_HEADER,
    get_correlation_id,
    set_correlation_id,
    reset_correlation_id,
    correlation_scope,
)


def test_correlation_id_header_constant():
    assert CORRELATION_ID_HEADER == "X-Correlation-ID"


def test_get_correlation_id_generates_default():
    cid = get_correlation_id()
    assert isinstance(cid, str)
    # Validate it is a valid UUID
    parsed = uuid.UUID(cid)
    assert str(parsed) == cid


def test_set_and_reset_correlation_id():
    custom_id = "test-correlation-12345"
    token = set_correlation_id(custom_id)
    assert get_correlation_id() == custom_id

    reset_correlation_id(token)
    # Once reset, get_correlation_id() creates or retains state appropriately
    assert get_correlation_id() != custom_id


def test_correlation_scope_manager():
    original_id = get_correlation_id()
    scoped_id = "scoped-id-9999"

    with correlation_scope(scoped_id) as active_id:
        assert active_id == scoped_id
        assert get_correlation_id() == scoped_id

    assert get_correlation_id() == original_id


@pytest.mark.asyncio
async def test_async_correlation_isolation():
    """Verify that concurrent async tasks do not leak correlation IDs into each other."""
    task_1_id = "task-alpha-1111"
    task_2_id = "task-beta-2222"
    results = {}

    async def worker(task_name: str, cid: str, delay: float):
        with correlation_scope(cid):
            await asyncio.sleep(delay)
            results[task_name] = get_correlation_id()

    await asyncio.gather(
        worker("worker_1", task_1_id, 0.02),
        worker("worker_2", task_2_id, 0.01),
    )

    assert results["worker_1"] == task_1_id
    assert results["worker_2"] == task_2_id
