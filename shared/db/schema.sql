-- ==============================================================================
-- RT-FADS Authoritative PostgreSQL & TimescaleDB Physical Schema
-- Real-Time Financial Anomaly Detection System
-- Reference DDL conforming to SRS §3.3, §6.2, §6.4 and ADR-006
-- ==============================================================================

-- 1. Required Extensions
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ------------------------------------------------------------------------------
-- 2. Django-Owned Tables (Admin Control Plane Domain)
-- ------------------------------------------------------------------------------

-- Users (Simulated bank customers)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    country VARCHAR(2) NOT NULL,
    account_created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_seed_data BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_country ON users (country);

-- Fraud Rules (Deterministic detection rules managed via Django Admin)
CREATE TABLE IF NOT EXISTS fraud_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    rule_type VARCHAR(64) NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    severity VARCHAR(32) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fraud_rules_enabled ON fraud_rules (enabled) WHERE enabled = TRUE;

-- Audit Logs (Append-only record of system mutations)
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor VARCHAR(255) NOT NULL,
    action VARCHAR(64) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    entity_id VARCHAR(255) NOT NULL,
    before JSONB,
    after JSONB,
    correlation_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs (created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_correlation_id ON audit_logs (correlation_id);

-- ------------------------------------------------------------------------------
-- 3. Alembic-Owned Tables (FastAPI Microservices Domain)
-- ------------------------------------------------------------------------------

-- Transactions (High-volume financial transactions; TimescaleDB Hypertable)
CREATE TABLE IF NOT EXISTS transactions (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    amount NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    country VARCHAR(2) NOT NULL,
    merchant_category VARCHAR(100) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'SUBMITTED' 
        CHECK (status IN ('SUBMITTED', 'PROCESSING', 'PROCESSED', 'PROCESSING_FAILED')),
    idempotency_key VARCHAR(255) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    correlation_id UUID NOT NULL,
    processed_at TIMESTAMPTZ,
    PRIMARY KEY (id, created_at)
);

-- Unique index on idempotency_key for transaction deduplication
CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_idempotency_key ON transactions (idempotency_key, created_at);
-- Fast velocity lookups (user transactions within time-windows)
CREATE INDEX IF NOT EXISTS idx_transactions_user_created_at ON transactions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_correlation_id ON transactions (correlation_id);

-- Convert transactions into a TimescaleDB hypertable with 7-day chunk intervals
SELECT create_hypertable(
    'transactions', 
    'created_at', 
    chunk_time_interval => INTERVAL '7 days', 
    if_not_exists => TRUE
);

-- Continuous Aggregate View for Dashboard Real-Time Statistics
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

-- Continuous Aggregate Refresh Policy (Refreshes every 1 minute)
SELECT add_continuous_aggregate_policy(
    'transaction_volume_5m',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE
);

-- Alerts (Suspicious transaction detection cases with state lifecycle)
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID UNIQUE NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING' 
        CHECK (status IN ('PENDING', 'ESCALATED_EMAIL', 'ESCALATED_SLACK', 'APPROVED', 'BLOCKED', 'FALSE_POSITIVE')),
    severity VARCHAR(32) NOT NULL 
        CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    composite_risk_score NUMERIC(5, 4) NOT NULL 
        CHECK (composite_risk_score >= 0.0 AND composite_risk_score <= 1.0),
    ml_anomaly_score NUMERIC(5, 4) NOT NULL 
        CHECK (ml_anomaly_score >= 0.0 AND ml_anomaly_score <= 1.0),
    rule_matches JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_profile_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_by VARCHAR(255),
    resolved_at TIMESTAMPTZ,
    resolution_reason TEXT,
    escalated_email_at TIMESTAMPTZ,
    escalated_slack_at TIMESTAMPTZ,
    correlation_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts (status);
CREATE INDEX IF NOT EXISTS idx_alerts_status_created_at ON alerts (status, created_at);
CREATE INDEX IF NOT EXISTS idx_alerts_user_id ON alerts (user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_correlation_id ON alerts (correlation_id);

-- Risk Profiles (Per-user aggregate fraud signals)
CREATE TABLE IF NOT EXISTS risk_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    risk_score NUMERIC(5, 4) NOT NULL DEFAULT 0.0000 
        CHECK (risk_score >= 0.0 AND risk_score <= 1.0),
    total_alerts INTEGER NOT NULL DEFAULT 0 
        CHECK (total_alerts >= 0),
    false_positive_count INTEGER NOT NULL DEFAULT 0 
        CHECK (false_positive_count >= 0),
    last_recalculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Transactional Outbox (Reliable event dispatch ledger to prevent dual writes)
CREATE TABLE IF NOT EXISTS outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(128) NOT NULL,
    event_version VARCHAR(16) NOT NULL DEFAULT 'v1',
    payload JSONB NOT NULL,
    correlation_id UUID NOT NULL,
    producer_service VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING' 
        CHECK (status IN ('PENDING', 'PUBLISHED', 'DEAD_LETTERED')),
    retry_count INTEGER NOT NULL DEFAULT 0 
        CHECK (retry_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox_events (created_at) WHERE status = 'PENDING';
CREATE INDEX IF NOT EXISTS idx_outbox_correlation_id ON outbox_events (correlation_id);

-- Processed Events (Inbox idempotency ledger for consumer groups)
CREATE TABLE IF NOT EXISTS processed_events (
    event_id UUID NOT NULL,
    consumer_group VARCHAR(64) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (event_id, consumer_group)
);

-- Dead Letter Events (Operator review table for exhausted retries)
CREATE TABLE IF NOT EXISTS dead_letter_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_event_id UUID NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    payload JSONB NOT NULL,
    last_error TEXT NOT NULL,
    failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retry_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_dlq_original_event_id ON dead_letter_events (original_event_id);
CREATE INDEX IF NOT EXISTS idx_dlq_failed_at ON dead_letter_events (failed_at);
