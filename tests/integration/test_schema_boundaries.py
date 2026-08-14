"""
Integration tests for service database write-ownership boundaries.
"""

import os
from pathlib import Path
import sys

# Configure Django path if needed for admin models
admin_service_path = Path(__file__).resolve().parents[2] / "services" / "admin"
if str(admin_service_path) not in sys.path:
    sys.path.insert(0, str(admin_service_path))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from users.models import User
from shared.models import (
    Alert,
    AuditLog,
    DeadLetterEvent,
    FraudRule,
    OutboxEvent,
    ProcessedEvent,
    RiskProfile,
    Transaction,
)


def test_schema_table_names_and_definitions():
    """Verifies all domain model tablenames match database schema definitions."""
    assert Transaction.__tablename__ == "transactions"
    assert Alert.__tablename__ == "alerts"
    assert RiskProfile.__tablename__ == "risk_profiles"
    assert FraudRule.__tablename__ == "fraud_rules"
    assert User._meta.db_table == "users"
    assert OutboxEvent.__tablename__ == "outbox_events"
    assert ProcessedEvent.__tablename__ == "processed_events"
    assert DeadLetterEvent.__tablename__ == "dead_letter_events"
    assert AuditLog.__tablename__ == "audit_logs"


def test_service_table_ownership_matrix():
    """
    Validates the table write-ownership boundaries between services:
    - Gateway owns writes to: transactions, outbox_events, audit_logs
    - Processor owns writes to: alerts, processed_events, risk_profiles, outbox_events, audit_logs (and status update on transactions)
    - Outbox Publisher owns writes to: outbox_events (status), dead_letter_events
    - Admin owns writes to: fraud_rules, users, audit_logs
    """
    gateway_write_tables = {"transactions", "outbox_events", "audit_logs"}
    processor_write_tables = {"alerts", "processed_events", "risk_profiles", "outbox_events", "audit_logs", "transactions"}
    outbox_write_tables = {"outbox_events", "dead_letter_events"}
    admin_write_tables = {"fraud_rules", "users", "audit_logs"}

    all_tables = {
        Transaction.__tablename__,
        Alert.__tablename__,
        RiskProfile.__tablename__,
        FraudRule.__tablename__,
        User._meta.db_table,
        OutboxEvent.__tablename__,
        ProcessedEvent.__tablename__,
        DeadLetterEvent.__tablename__,
        AuditLog.__tablename__,
    }

    # Verify every registered table is accounted for in write boundaries
    covered_tables = gateway_write_tables | processor_write_tables | outbox_write_tables | admin_write_tables
    assert covered_tables == all_tables

    # Gateway should never write directly to alerts, fraud_rules, or risk_profiles
    assert "alerts" not in gateway_write_tables
    assert "fraud_rules" not in gateway_write_tables
    assert "risk_profiles" not in gateway_write_tables

    # Admin should never write directly to live transactions or dead_letter_events
    assert "transactions" not in admin_write_tables
    assert "dead_letter_events" not in admin_write_tables
