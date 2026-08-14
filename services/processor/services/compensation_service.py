"""
Risk profile compensation service for RT-FADS Processor.
Performs business-level compensating adjustments on user risk scores upon false-positive resolution.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.logging.json_logger import get_json_logger
from shared.models import RiskProfile

logger = get_json_logger(__name__)


class RiskCompensationService:
    """Service providing business-level risk profile recalculation upon analyst feedback."""

    async def recalculate_user_risk_profile(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        alert_id: Optional[uuid.UUID] = None,
    ) -> RiskProfile:
        """
        Recalculates a user's risk profile following a false-positive alert resolution.
        Increments false_positive_count and adjusts normalized risk_score downwards.
        """
        now = datetime.now(timezone.utc)
        stmt = select(RiskProfile).where(RiskProfile.user_id == user_id)
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()

        if profile is None:
            # Create initial profile with false_positive_count = 1 and 0.0 risk score
            profile = RiskProfile(
                user_id=user_id,
                risk_score=Decimal("0.0000"),
                total_alerts=0,
                false_positive_count=1,
                last_recalculated_at=now,
            )
            session.add(profile)
            logger.info(
                f"Created initial RiskProfile for user {user_id} during compensation",
                extra={"user_id": str(user_id), "alert_id": str(alert_id) if alert_id else None},
            )
        else:
            old_score = profile.risk_score
            old_fp = profile.false_positive_count

            # Increment false positive tally
            profile.false_positive_count += 1

            # Recalculate score based on net effective alerts
            effective_alerts = max(0, profile.total_alerts - profile.false_positive_count)
            if profile.total_alerts > 0:
                raw_score = Decimal(str(round(min(1.0, float(effective_alerts) * 0.25), 4)))
            else:
                raw_score = Decimal("0.0000")

            profile.risk_score = max(Decimal("0.0000"), min(Decimal("1.0000"), raw_score))
            profile.last_recalculated_at = now

            logger.info(
                f"Recalculated RiskProfile for user {user_id}",
                extra={
                    "user_id": str(user_id),
                    "alert_id": str(alert_id) if alert_id else None,
                    "old_risk_score": str(old_score),
                    "new_risk_score": str(profile.risk_score),
                    "old_false_positive_count": old_fp,
                    "new_false_positive_count": profile.false_positive_count,
                    "total_alerts": profile.total_alerts,
                },
            )

        return profile
