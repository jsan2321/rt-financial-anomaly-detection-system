"""
Transactions API router for Gateway service.
Exposes POST /transactions and GET /transactions/{id}.
"""

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from shared.context.correlation import get_correlation_id
from shared.db.session import get_db_session

from ..schemas.transactions import (
    TransactionAcceptedResponse,
    TransactionCreateRequest,
    TransactionDetailResponse,
)
from ..services.ingestion import IngestionService

router = APIRouter(prefix="/transactions", tags=["Transactions"])
ingestion_service = IngestionService()


@router.post(
    "",
    response_model=TransactionAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit transaction for asynchronous anomaly evaluation",
)
async def create_transaction(
    payload: TransactionCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> TransactionAcceptedResponse:
    """
    Submits a transaction. Idempotently writes to PostgreSQL and inserts OutboxEvent.
    Returns 202 Accepted without blocking on evaluation.
    """
    corr_id = get_correlation_id()
    return await ingestion_service.submit_transaction(
        session=db,
        payload=payload,
        correlation_id=corr_id,
    )


@router.get(
    "/{transaction_id}",
    response_model=TransactionDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get transaction status and alert summary",
)
async def get_transaction(
    transaction_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> TransactionDetailResponse:
    """
    Fetches the current status and alert summary for a transaction.
    """
    return await ingestion_service.get_transaction(
        session=db,
        transaction_id=transaction_id,
    )
