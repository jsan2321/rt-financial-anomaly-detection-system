"""Initial schema for FastAPI microservices & TimescaleDB hypertable

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-08-13 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Ensure required extensions exist
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    # 2. Risk Profiles
    op.create_table(
        'risk_profiles',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('risk_score', sa.Numeric(precision=5, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('total_alerts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('false_positive_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_recalculated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint('risk_score >= 0.0 AND risk_score <= 1.0', name='chk_risk_profiles_score_range'),
        sa.CheckConstraint('total_alerts >= 0', name='chk_risk_profiles_total_alerts_positive'),
        sa.CheckConstraint('false_positive_count >= 0', name='chk_risk_profiles_fp_positive'),
    )

    # 3. Transactions (Hypertable)
    op.create_table(
        'transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='USD'),
        sa.Column('country', sa.String(length=2), nullable=False),
        sa.Column('merchant_category', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='SUBMITTED'),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('correlation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', 'created_at', name='pk_transactions'),
        sa.CheckConstraint('amount > 0', name='chk_transactions_amount_positive'),
        sa.CheckConstraint(
            "status IN ('SUBMITTED', 'PROCESSING', 'PROCESSED', 'PROCESSING_FAILED')",
            name='chk_transactions_status'
        ),
    )

    op.create_index(
        'idx_transactions_idempotency_key',
        'transactions',
        ['idempotency_key', 'created_at'],
        unique=True
    )
    op.create_index(
        'idx_transactions_user_created_at',
        'transactions',
        ['user_id', sa.text('created_at DESC')]
    )
    op.create_index(
        'idx_transactions_correlation_id',
        'transactions',
        ['correlation_id']
    )

    # Convert transactions table to TimescaleDB hypertable
    op.execute(
        "SELECT create_hypertable('transactions', 'created_at', "
        "chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);"
    )

    # Continuous Aggregate Materialized View for 5-minute volume aggregation
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS transaction_volume_5m
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('5 minutes', created_at) AS bucket,
            count(*) AS transaction_count,
            sum(amount) AS total_amount,
            count(DISTINCT user_id) AS active_users
        FROM transactions
        GROUP BY bucket
        WITH NO DATA;
    """)

    # Add refresh policy to continuous aggregate view
    op.execute("""
        SELECT add_continuous_aggregate_policy(
            'transaction_volume_5m',
            start_offset => INTERVAL '1 day',
            end_offset => INTERVAL '1 minute',
            schedule_interval => INTERVAL '1 minute',
            if_not_exists => TRUE
        );
    """)

    # 4. Alerts
    op.create_table(
        'alerts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('transaction_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='PENDING'),
        sa.Column('severity', sa.String(length=32), nullable=False),
        sa.Column('composite_risk_score', sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column('ml_anomaly_score', sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column('rule_matches', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('risk_profile_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('is_demo', sa.Boolean(), nullable=False, server_default=sa.text('FALSE')),
        sa.Column('resolved_by', sa.String(length=255), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_reason', sa.Text(), nullable=True),
        sa.Column('escalated_email_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('escalated_slack_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('correlation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint(
            "status IN ('PENDING', 'ESCALATED_EMAIL', 'ESCALATED_SLACK', 'APPROVED', 'BLOCKED', 'FALSE_POSITIVE')",
            name='chk_alerts_status'
        ),
        sa.CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name='chk_alerts_severity'
        ),
        sa.CheckConstraint(
            'composite_risk_score >= 0.0 AND composite_risk_score <= 1.0',
            name='chk_alerts_composite_score'
        ),
        sa.CheckConstraint(
            'ml_anomaly_score >= 0.0 AND ml_anomaly_score <= 1.0',
            name='chk_alerts_ml_score'
        ),
    )

    op.create_index('idx_alerts_status', 'alerts', ['status'])
    op.create_index('idx_alerts_status_created_at', 'alerts', ['status', 'created_at'])
    op.create_index('idx_alerts_user_id', 'alerts', ['user_id'])
    op.create_index('idx_alerts_correlation_id', 'alerts', ['correlation_id'])

    # 5. Outbox Events
    op.create_table(
        'outbox_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('event_type', sa.String(length=128), nullable=False),
        sa.Column('event_version', sa.String(length=16), nullable=False, server_default='v1'),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('correlation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('producer_service', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='PENDING'),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PUBLISHED', 'DEAD_LETTERED')",
            name='chk_outbox_status'
        ),
        sa.CheckConstraint('retry_count >= 0', name='chk_outbox_retry_count'),
    )

    op.create_index(
        'idx_outbox_pending',
        'outbox_events',
        ['created_at'],
        postgresql_where=sa.text("status = 'PENDING'")
    )
    op.create_index('idx_outbox_correlation_id', 'outbox_events', ['correlation_id'])

    # 6. Processed Events (Inbox)
    op.create_table(
        'processed_events',
        sa.Column('event_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('consumer_group', sa.String(length=64), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('event_id', 'consumer_group', name='pk_processed_events')
    )

    # 7. Dead Letter Events
    op.create_table(
        'dead_letter_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('original_event_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(length=128), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=False),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
    )

    op.create_index('idx_dlq_original_event_id', 'dead_letter_events', ['original_event_id'])
    op.create_index('idx_dlq_failed_at', 'dead_letter_events', ['failed_at'])


def downgrade() -> None:
    # 1. Drop Continuous Aggregate and Policy
    op.execute("DROP MATERIALIZED VIEW IF EXISTS transaction_volume_5m CASCADE;")

    # 2. Drop Tables
    op.drop_table('dead_letter_events')
    op.drop_table('processed_events')
    op.drop_table('outbox_events')
    op.drop_table('alerts')
    op.drop_table('transactions')
    op.drop_table('risk_profiles')
