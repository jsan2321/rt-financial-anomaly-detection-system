"""
Ingestion service for RT-FADS Gateway.
Handles idempotent transaction submission, atomic outbox record creation, and OpenTelemetry instrumentation.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.errors.exceptions import ResourceNotFoundError
from shared.events.event_types import DEFAULT_EVENT_VERSION, EVENT_TRANSACTION_CREATED
from shared.models import Alert, OutboxEvent, Transaction
from shared.models.enums import OutboxStatus, TransactionStatus
from shared.telemetry import (
    inject_trace_context,
    processing_latency_seconds,
    trace_span,
    transactions_received_total,
    transactions_rejected_total,
)

from ..schemas.transactions import (
    AlertSummaryResponse,
    TransactionAcceptedResponse,
    TransactionCreateRequest,
    TransactionDetailResponse,
)


class IngestionService:
    """Service handling transaction submission and querying."""

    async def submit_transaction(
        self,
        session: AsyncSession,
        payload: TransactionCreateRequest,
        correlation_id: str,
    ) -> TransactionAcceptedResponse:
        """
        Submits a transaction asynchronously with idempotent deduplication, atomic outbox insert,
        and distributed trace propagation (NFR-OBS-002).
        Returns HTTP 202 Accepted response payload.
        """
        corr_uuid = (
            uuid.UUID(correlation_id)
            if isinstance(correlation_id, str)
            else correlation_id
        )

        with trace_span(
            "gateway.ingest_transaction",
            attributes={
                "transaction_id": str(payload.idempotency_key or "pending"),
                "user_id": str(payload.user_id),
                "amount": float(payload.amount),
                "currency": payload.currency,
                "country": payload.country,
                "merchant_category": payload.merchant_category,
            },
        ):
            with processing_latency_seconds.time(stage="gateway_ingest"):
                try:
                    # Generate server-side UUIDv4 idempotency key if client omitted one (FR-ING-002)
                    idempotency_key = payload.idempotency_key or str(uuid.uuid4())

                    # Check for existing idempotency key (FR-ING-005)
                    stmt = select(Transaction).where(Transaction.idempotency_key == idempotency_key)
                    result = await session.execute(stmt)
                    existing_txn = result.scalar_one_or_none()

                    if existing_txn:
                        # Duplicate submission detected: return reference to original transaction without secondary writes
                        transactions_received_total.inc(status="duplicate")
                        return TransactionAcceptedResponse(
                            transaction_id=existing_txn.id,
                            status=TransactionStatus(existing_txn.status),
                            correlation_id=str(existing_txn.correlation_id),
                            status_url=f"/api/v1/transactions/{existing_txn.id}",
                        )

                    now = datetime.now(timezone.utc)
                    txn_id = uuid.uuid4()

                    # 1. Create Transaction entity
                    transaction = Transaction(
                        id=txn_id,
                        user_id=payload.user_id,
                        amount=payload.amount,
                        currency=payload.currency,
                        country=payload.country,
                        merchant_category=payload.merchant_category,
                        status=TransactionStatus.SUBMITTED.value,
                        idempotency_key=idempotency_key,
                        metadata_=payload.metadata or {},
                        correlation_id=corr_uuid,
                        created_at=now,
                    )

                    # 2. Create OutboxEvent for transactional relay (ADR-003)
                    # Inject W3C trace context into outbox payload for distributed span linking
                    trace_carrier: dict = {}
                    inject_trace_context(trace_carrier)

                    outbox_payload = {
                        "transaction_id": str(txn_id),
                        "user_id": str(payload.user_id),
                        "amount": str(payload.amount),
                        "currency": payload.currency,
                        "country": payload.country,
                        "merchant_category": payload.merchant_category,
                        "created_at": now.isoformat(),
                        "metadata": payload.metadata or {},
                        "_trace_context": trace_carrier,
                    }

                    outbox_event = OutboxEvent(
                        id=uuid.uuid4(),
                        event_type=EVENT_TRANSACTION_CREATED,
                        event_version=DEFAULT_EVENT_VERSION,
                        payload=outbox_payload,
                        correlation_id=corr_uuid,
                        producer_service="gateway",
                        status=OutboxStatus.PENDING.value,
                        retry_count=0,
                        created_at=now,
                    )

                    # Commit atomically in a single DB transaction (FR-ING-004)
                    session.add(transaction)
                    session.add(outbox_event)
                    await session.commit()

                    transactions_received_total.inc(status="accepted")

                    return TransactionAcceptedResponse(
                        transaction_id=txn_id,
                        status=TransactionStatus.SUBMITTED,
                        correlation_id=str(corr_uuid),
                        status_url=f"/api/v1/transactions/{txn_id}",
                    )

                except Exception as exc:
                    transactions_rejected_total.inc(reason="ingestion_error")
                    raise

    async def get_transaction(
        self,
        session: AsyncSession,
        transaction_id: uuid.UUID,
    ) -> TransactionDetailResponse:
        """
        Retrieves transaction details and any attached alert summary (FR-ING-010).
        """
        with trace_span("gateway.get_transaction", attributes={"transaction_id": str(transaction_id)}):
            stmt = select(Transaction).where(Transaction.id == transaction_id)
            result = await session.execute(stmt)
            txn = result.scalar_one_or_none()

            if not txn:
                raise ResourceNotFoundError("Transaction", str(transaction_id))

            # Check for associated alert
            alert_stmt = select(Alert).where(Alert.transaction_id == transaction_id)
            alert_result = await session.execute(alert_stmt)
            alert = alert_result.scalar_one_or_none()

            alert_summary = None
            if alert:
                alert_summary = AlertSummaryResponse(
                    id=alert.id,
                    status=alert.status,
                    severity=alert.severity,
                )

            return TransactionDetailResponse(
                transaction_id=txn.id,
                user_id=txn.user_id,
                amount=txn.amount,
                currency=txn.currency,
                country=txn.country,
                merchant_category=txn.merchant_category,
                status=TransactionStatus(txn.status),
                created_at=txn.created_at,
                processed_at=txn.processed_at,
                correlation_id=txn.correlation_id,
                alert=alert_summary,
            )
