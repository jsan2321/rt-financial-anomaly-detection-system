"""
Detection pipeline orchestrator for RT-FADS Processor service.
Coordinates velocity lookups, risk profiles, rule evaluation, ML scoring,
composite decision generation, atomic DB updates, and outbox event creation.
Instrumented with OpenTelemetry distributed trace spans and Prometheus metrics (NFR-OBS-002, NFR-OBS-004).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.context.correlation import set_correlation_id
from shared.events.envelope import EventEnvelope
from shared.events.event_types import DEFAULT_EVENT_VERSION, EVENT_ALERT_CREATED
from shared.logging.json_logger import get_json_logger
from shared.models import Alert, OutboxEvent, ProcessedEvent, RiskProfile, Transaction
from shared.models.enums import AlertStatus, OutboxStatus, TransactionStatus
from shared.telemetry import (
    alerts_created_total,
    inject_trace_context,
    processing_latency_seconds,
    trace_span,
)

from ..domain.composite_scoring import compute_detection_decision
from ..domain.demo_strategy import DemoOverrideStrategy, NullDemoStrategy
from ..domain.ml_model import MLAnomalyScorer
from ..domain.rules import evaluate_rules
from ..domain.schemas import (
    DetectionResult,
    RiskProfileSnapshot,
    ScoringWeights,
    TransactionContext,
    VelocityContext,
)
from .rule_cache import RuleCache

logger = get_json_logger(__name__)


class DetectionPipeline:
    """End-to-end anomaly detection pipeline for transaction processing."""

    def __init__(
        self,
        rule_cache: RuleCache,
        ml_detector: MLAnomalyScorer,
        demo_strategy: Optional[DemoOverrideStrategy] = None,
        scoring_weights: Optional[ScoringWeights] = None,
        velocity_window_minutes: int = 10,
        consumer_group: str = "processor-group",
    ) -> None:
        self.rule_cache = rule_cache
        self.ml_detector = ml_detector
        self.demo_strategy = demo_strategy or NullDemoStrategy()
        self.scoring_weights = scoring_weights or ScoringWeights()
        self.velocity_window_minutes = velocity_window_minutes
        self.consumer_group = consumer_group

    async def get_velocity_context(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        reference_time: datetime,
    ) -> VelocityContext:
        """
        Queries TimescaleDB Transaction hypertable for user velocity in the trailing window.
        """
        window_start = reference_time - timedelta(minutes=self.velocity_window_minutes)

        stmt = select(
            func.count(Transaction.id).label("txn_count"),
            func.coalesce(func.sum(Transaction.amount), Decimal("0.00")).label("total_amount"),
        ).where(
            Transaction.user_id == user_id,
            Transaction.created_at >= window_start,
            Transaction.created_at <= reference_time,
        )

        result = await session.execute(stmt)
        row = result.one()
        count = row.txn_count or 0
        total = Decimal(str(row.total_amount or "0.00"))

        return VelocityContext(
            user_id=user_id,
            window_minutes=self.velocity_window_minutes,
            transaction_count=count,
            total_amount=total,
        )

    async def get_risk_profile_snapshot(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
    ) -> RiskProfileSnapshot:
        """
        Retrieves user risk profile or returns initial 0.0 baseline snapshot.
        """
        stmt = select(RiskProfile).where(RiskProfile.user_id == user_id)
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()

        if profile:
            return RiskProfileSnapshot(
                user_id=profile.user_id,
                risk_score=Decimal(str(profile.risk_score)),
                total_alerts=profile.total_alerts,
                false_positive_count=profile.false_positive_count,
                last_recalculated_at=profile.last_recalculated_at,
            )

        return RiskProfileSnapshot(
            user_id=user_id,
            risk_score=Decimal("0.0000"),
            total_alerts=0,
            false_positive_count=0,
            last_recalculated_at=None,
        )

    async def process_transaction_event(
        self,
        session: AsyncSession,
        event_envelope: EventEnvelope[Dict[str, Any]],
    ) -> DetectionResult:
        """
        Executes full detection pipeline and applies all DB updates within the active transaction.
        Commits upon completion.
        """
        correlation_id = event_envelope.correlation_id
        set_correlation_id(correlation_id)

        corr_uuid = uuid.UUID(correlation_id) if isinstance(correlation_id, str) else correlation_id
        event_uuid = (
            uuid.UUID(event_envelope.event_id)
            if isinstance(event_envelope.event_id, str)
            else event_envelope.event_id
        )

        payload = event_envelope.payload

        # 1. Parse Transaction Context
        txn_created_at = (
            datetime.fromisoformat(payload["created_at"])
            if isinstance(payload.get("created_at"), str)
            else payload.get("created_at", datetime.now(timezone.utc))
        )
        if txn_created_at.tzinfo is None:
            txn_created_at = txn_created_at.replace(tzinfo=timezone.utc)

        txn_ctx = TransactionContext(
            id=uuid.UUID(str(payload["transaction_id"])),
            user_id=uuid.UUID(str(payload["user_id"])),
            amount=Decimal(str(payload["amount"])),
            currency=str(payload.get("currency", "USD")),
            country=str(payload.get("country", "")),
            merchant_category=str(payload.get("merchant_category", "")),
            created_at=txn_created_at,
            metadata=payload.get("metadata", {}),
            correlation_id=corr_uuid,
        )

        logger.info(
            "Processing transaction in detection pipeline",
            extra={"transaction_id": str(txn_ctx.id), "user_id": str(txn_ctx.user_id)},
        )

        # 2. Gather Contexts (Velocity & Risk Profile)
        velocity_ctx = await self.get_velocity_context(
            session=session,
            user_id=txn_ctx.user_id,
            reference_time=txn_ctx.created_at,
        )

        risk_snapshot = await self.get_risk_profile_snapshot(
            session=session,
            user_id=txn_ctx.user_id,
        )

        # 3. Deterministic Rules Evaluation
        with trace_span(
            "processor.evaluate_rules",
            attributes={
                "transaction_id": str(txn_ctx.id),
                "user_id": str(txn_ctx.user_id),
            },
        ):
            active_rules = await self.rule_cache.get_active_rules(session)
            rule_matches = evaluate_rules(
                rules=active_rules,
                transaction=txn_ctx,
                velocity=velocity_ctx,
                risk_profile=risk_snapshot,
            )

        # 4. ML Anomaly Scoring
        with trace_span(
            "processor.ml_inference",
            attributes={
                "transaction_id": str(txn_ctx.id),
                "user_id": str(txn_ctx.user_id),
            },
        ):
            with processing_latency_seconds.time(stage="ml_inference"):
                ml_score = self.ml_detector.score(
                    transaction=txn_ctx,
                    velocity=velocity_ctx,
                )

        # 5. Composite Risk Decision
        with trace_span(
            "processor.composite_scoring",
            attributes={
                "transaction_id": str(txn_ctx.id),
                "ml_score": float(ml_score),
            },
        ):
            decision = compute_detection_decision(
                transaction=txn_ctx,
                rule_matches=rule_matches,
                ml_score=ml_score,
                risk_profile=risk_snapshot,
                weights=self.scoring_weights,
            )

            # 6. Apply DEMO_MODE Strategy Override
            final_decision = self.demo_strategy.override(
                transaction=txn_ctx,
                decision=decision,
            )

        now = datetime.now(timezone.utc)

        # 7. Atomic DB Modifications (Single Transaction)
        with trace_span(
            "processor.db_write",
            attributes={
                "transaction_id": str(txn_ctx.id),
                "should_alert": final_decision.should_alert,
                "severity": final_decision.severity.value,
            },
        ):
            with processing_latency_seconds.time(stage="db_commit"):
                # 7a. Update Transaction Status to PROCESSED
                update_txn_stmt = (
                    update(Transaction)
                    .where(
                        Transaction.id == txn_ctx.id,
                        Transaction.created_at == txn_ctx.created_at,
                    )
                    .values(
                        status=TransactionStatus.PROCESSED.value,
                        processed_at=now,
                    )
                )
                await session.execute(update_txn_stmt)

                # 7b. If Alert triggered, create Alert + OutboxEvent + update RiskProfile
                if final_decision.should_alert:
                    alert_id = uuid.uuid4()
                    rule_matches_json = [m.model_dump(mode="json") for m in final_decision.rule_matches]

                    alert = Alert(
                        id=alert_id,
                        transaction_id=txn_ctx.id,
                        user_id=txn_ctx.user_id,
                        status=AlertStatus.PENDING.value,
                        severity=final_decision.severity.value,
                        composite_risk_score=final_decision.composite_risk_score,
                        ml_anomaly_score=final_decision.ml_anomaly_score,
                        rule_matches=rule_matches_json,
                        risk_profile_snapshot=final_decision.risk_profile_snapshot,
                        is_demo=final_decision.is_demo,
                        correlation_id=corr_uuid,
                        created_at=now,
                    )
                    session.add(alert)

                    # Increment alerts metric (NFR-OBS-004)
                    alerts_created_total.inc(severity=final_decision.severity.value)

                    # Inject W3C trace context into outbox event payload
                    trace_carrier: dict = {}
                    inject_trace_context(trace_carrier)

                    # Insert alert.created OutboxEvent
                    outbox_payload = {
                        "alert_id": str(alert_id),
                        "transaction_id": str(txn_ctx.id),
                        "user_id": str(txn_ctx.user_id),
                        "status": AlertStatus.PENDING.value,
                        "severity": final_decision.severity.value,
                        "composite_risk_score": str(final_decision.composite_risk_score),
                        "ml_anomaly_score": str(final_decision.ml_anomaly_score),
                        "rule_matches": rule_matches_json,
                        "is_demo": final_decision.is_demo,
                        "explanation": final_decision.explanation,
                        "created_at": now.isoformat(),
                        "_trace_context": trace_carrier,
                    }

                    outbox_event = OutboxEvent(
                        id=uuid.uuid4(),
                        event_type=EVENT_ALERT_CREATED,
                        event_version=DEFAULT_EVENT_VERSION,
                        payload=outbox_payload,
                        correlation_id=corr_uuid,
                        producer_service="processor",
                        status=OutboxStatus.PENDING.value,
                        retry_count=0,
                        created_at=now,
                    )
                    session.add(outbox_event)

                    # Upsert RiskProfile
                    profile_stmt = select(RiskProfile).where(RiskProfile.user_id == txn_ctx.user_id)
                    profile_res = await session.execute(profile_stmt)
                    existing_profile = profile_res.scalar_one_or_none()

                    if existing_profile:
                        existing_profile.total_alerts += 1
                        existing_profile.last_recalculated_at = now
                    else:
                        new_profile = RiskProfile(
                            user_id=txn_ctx.user_id,
                            risk_score=Decimal("0.0000"),
                            total_alerts=1,
                            false_positive_count=0,
                            last_recalculated_at=now,
                        )
                        session.add(new_profile)

                # 7c. Record ProcessedEvent (Inbox Pattern)
                processed_event = ProcessedEvent(
                    event_id=event_uuid,
                    consumer_group=self.consumer_group,
                    processed_at=now,
                )
                session.add(processed_event)

                # Commit transaction atomically
                await session.commit()

        logger.info(
            "Transaction successfully processed by detection pipeline",
            extra={
                "transaction_id": str(txn_ctx.id),
                "should_alert": final_decision.should_alert,
                "severity": final_decision.severity.value,
                "composite_score": str(final_decision.composite_risk_score),
            },
        )

        return final_decision
