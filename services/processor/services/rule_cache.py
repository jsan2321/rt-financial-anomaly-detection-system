"""
In-memory cache for active FraudRule definitions with TTL refresh.
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.logging.json_logger import get_json_logger
from shared.models.enums import AlertSeverity, RuleType
from shared.models.fraud_rule import FraudRule

from ..domain.schemas import RuleDefinition

logger = get_json_logger(__name__)


class RuleCache:
    """Thread-safe in-memory cache for enabled fraud rules."""

    def __init__(self, refresh_ttl_seconds: float = 30.0) -> None:
        self.refresh_ttl_seconds = refresh_ttl_seconds
        self._rules: List[RuleDefinition] = []
        self._last_refreshed_at: Optional[datetime] = None
        self._lock = asyncio.Lock()

    @property
    def last_refreshed_at(self) -> Optional[datetime]:
        """Returns the UTC timestamp when the cache was last refreshed."""
        return self._last_refreshed_at

    @property
    def cached_rule_count(self) -> int:
        """Returns the number of rules currently loaded in memory."""
        return len(self._rules)

    async def get_active_rules(
        self,
        session: AsyncSession,
        force_refresh: bool = False,
    ) -> List[RuleDefinition]:
        """
        Retrieves active rules from cache, refreshing from the database if TTL expired.
        """
        now = datetime.now(timezone.utc)
        needs_refresh = (
            force_refresh
            or self._last_refreshed_at is None
            or (now - self._last_refreshed_at).total_seconds() >= self.refresh_ttl_seconds
        )

        if not needs_refresh:
            return list(self._rules)

        async with self._lock:
            # Re-check under lock in case another coroutine refreshed
            now = datetime.now(timezone.utc)
            if not force_refresh and self._last_refreshed_at is not None:
                if (now - self._last_refreshed_at).total_seconds() < self.refresh_ttl_seconds:
                    return list(self._rules)

            logger.debug("Refreshing FraudRule cache from database")
            stmt = select(FraudRule).where(FraudRule.enabled == True)
            result = await session.execute(stmt)
            db_rules = result.scalars().all()

            loaded_rules: List[RuleDefinition] = []
            for r in db_rules:
                try:
                    rule_def = RuleDefinition(
                        id=r.id,
                        name=r.name,
                        rule_type=RuleType(r.rule_type),
                        parameters=r.parameters or {},
                        severity=AlertSeverity(r.severity),
                        enabled=r.enabled,
                    )
                    loaded_rules.append(rule_def)
                except Exception as ex:
                    logger.warning(
                        "Skipping invalid fraud rule from database",
                        extra={"rule_id": str(r.id), "error": str(ex)},
                    )

            self._rules = loaded_rules
            self._last_refreshed_at = now
            logger.info(
                "FraudRule cache refreshed",
                extra={"active_rules_count": len(self._rules)},
            )
            return list(self._rules)

    def set_rules_for_testing(self, rules: List[RuleDefinition]) -> None:
        """Helper to inject rule definitions for unit testing."""
        self._rules = list(rules)
        self._last_refreshed_at = datetime.now(timezone.utc)
