"""
Deterministic fraud rules engine for RT-FADS.
Pure, side-effect-free evaluation of the five standard rule types.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from shared.models.enums import AlertSeverity, RuleType

from .schemas import (
    RiskProfileSnapshot,
    RuleDefinition,
    RuleMatch,
    TransactionContext,
    VelocityContext,
)


def _eval_amount_threshold(
    rule: RuleDefinition,
    transaction: TransactionContext,
) -> Optional[RuleMatch]:
    params = rule.parameters
    raw_threshold = params.get("threshold") or params.get("amount_threshold") or params.get("limit")
    if raw_threshold is None:
        return None

    try:
        threshold = Decimal(str(raw_threshold))
    except Exception:
        return None

    # Currency match if configured
    required_currency = params.get("currency")
    if required_currency and transaction.currency.upper() != str(required_currency).upper():
        return None

    operator = params.get("operator", ">=")
    is_match = (
        (transaction.amount >= threshold)
        if operator == ">="
        else (transaction.amount > threshold)
    )

    if is_match:
        return RuleMatch(
            rule_id=str(rule.id),
            rule_name=rule.name,
            rule_type=rule.rule_type.value,
            severity=rule.severity.value,
            explanation=(
                f"Transaction amount {transaction.amount:.2f} {transaction.currency} "
                f"exceeds threshold {threshold:.2f} {transaction.currency}"
            ),
            parameters_snapshot=dict(params),
            matched_at=datetime.now(timezone.utc),
        )
    return None


def _eval_high_risk_country(
    rule: RuleDefinition,
    transaction: TransactionContext,
) -> Optional[RuleMatch]:
    params = rule.parameters
    countries = (
        params.get("countries")
        or params.get("country_codes")
        or params.get("country_list")
        or []
    )
    if not isinstance(countries, (list, tuple, set)):
        return None

    normalized_countries = {str(c).strip().upper() for c in countries}
    txn_country = transaction.country.strip().upper()

    if txn_country in normalized_countries:
        return RuleMatch(
            rule_id=str(rule.id),
            rule_name=rule.name,
            rule_type=rule.rule_type.value,
            severity=rule.severity.value,
            explanation=(
                f"Transaction origin country '{transaction.country}' matches high-risk country list"
            ),
            parameters_snapshot=dict(params),
            matched_at=datetime.now(timezone.utc),
        )
    return None


def _eval_velocity(
    rule: RuleDefinition,
    velocity: Optional[VelocityContext],
) -> Optional[RuleMatch]:
    if velocity is None:
        return None

    params = rule.parameters
    max_count = params.get("max_count") or params.get("count_threshold")
    max_amount_raw = params.get("max_amount") or params.get("amount_threshold")
    window_minutes = params.get("window_minutes", velocity.window_minutes)

    matched_reasons = []

    if max_count is not None:
        try:
            limit_count = int(max_count)
            if velocity.transaction_count >= limit_count:
                matched_reasons.append(
                    f"count {velocity.transaction_count} >= limit {limit_count}"
                )
        except (ValueError, TypeError):
            pass

    if max_amount_raw is not None:
        try:
            limit_amount = Decimal(str(max_amount_raw))
            if velocity.total_amount >= limit_amount:
                matched_reasons.append(
                    f"total amount {velocity.total_amount:.2f} >= limit {limit_amount:.2f}"
                )
        except Exception:
            pass

    if matched_reasons:
        explanation = (
            f"User transaction velocity exceeded in {window_minutes}m window: "
            + ", ".join(matched_reasons)
        )
        return RuleMatch(
            rule_id=str(rule.id),
            rule_name=rule.name,
            rule_type=rule.rule_type.value,
            severity=rule.severity.value,
            explanation=explanation,
            parameters_snapshot=dict(params),
            matched_at=datetime.now(timezone.utc),
        )
    return None


def _eval_user_risk_level(
    rule: RuleDefinition,
    risk_profile: Optional[RiskProfileSnapshot],
) -> Optional[RuleMatch]:
    if risk_profile is None:
        return None

    params = rule.parameters
    raw_min_score = (
        params.get("min_risk_score")
        or params.get("risk_threshold")
        or params.get("threshold")
    )
    if raw_min_score is None:
        return None

    try:
        min_risk_score = Decimal(str(raw_min_score))
    except Exception:
        return None

    if risk_profile.risk_score >= min_risk_score:
        return RuleMatch(
            rule_id=str(rule.id),
            rule_name=rule.name,
            rule_type=rule.rule_type.value,
            severity=rule.severity.value,
            explanation=(
                f"User risk score {risk_profile.risk_score:.4f} meets or exceeds "
                f"risk threshold {min_risk_score:.4f}"
            ),
            parameters_snapshot=dict(params),
            matched_at=datetime.now(timezone.utc),
        )
    return None


def _eval_merchant_category(
    rule: RuleDefinition,
    transaction: TransactionContext,
) -> Optional[RuleMatch]:
    params = rule.parameters
    categories = (
        params.get("categories")
        or params.get("category_list")
        or params.get("blocked_categories")
        or []
    )
    if not isinstance(categories, (list, tuple, set)):
        return None

    normalized_categories = {str(c).strip().lower() for c in categories}
    txn_category = transaction.merchant_category.strip().lower()

    if txn_category in normalized_categories:
        return RuleMatch(
            rule_id=str(rule.id),
            rule_name=rule.name,
            rule_type=rule.rule_type.value,
            severity=rule.severity.value,
            explanation=(
                f"Merchant category '{transaction.merchant_category}' matches "
                f"monitored high-risk merchant categories"
            ),
            parameters_snapshot=dict(params),
            matched_at=datetime.now(timezone.utc),
        )
    return None


def evaluate_rule(
    rule: RuleDefinition,
    transaction: TransactionContext,
    velocity: Optional[VelocityContext] = None,
    risk_profile: Optional[RiskProfileSnapshot] = None,
) -> Optional[RuleMatch]:
    """
    Evaluates a single fraud rule against transaction and context.
    Returns RuleMatch if rule triggers, else None.
    """
    if not rule.enabled:
        return None

    if rule.rule_type == RuleType.AMOUNT_THRESHOLD:
        return _eval_amount_threshold(rule, transaction)
    elif rule.rule_type == RuleType.HIGH_RISK_COUNTRY:
        return _eval_high_risk_country(rule, transaction)
    elif rule.rule_type == RuleType.VELOCITY:
        return _eval_velocity(rule, velocity)
    elif rule.rule_type == RuleType.USER_RISK_LEVEL:
        return _eval_user_risk_level(rule, risk_profile)
    elif rule.rule_type == RuleType.MERCHANT_CATEGORY:
        return _eval_merchant_category(rule, transaction)

    return None


def evaluate_rules(
    rules: Sequence[RuleDefinition],
    transaction: TransactionContext,
    velocity: Optional[VelocityContext] = None,
    risk_profile: Optional[RiskProfileSnapshot] = None,
) -> List[RuleMatch]:
    """
    Evaluates a collection of rules in deterministic sequence.
    Returns list of all triggered RuleMatch objects.
    """
    matches: List[RuleMatch] = []
    for rule in rules:
        match = evaluate_rule(
            rule=rule,
            transaction=transaction,
            velocity=velocity,
            risk_profile=risk_profile,
        )
        if match is not None:
            matches.append(match)
    return matches
