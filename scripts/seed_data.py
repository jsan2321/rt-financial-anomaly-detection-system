"""
Manual data seeding script for RT-FADS.
Populates synthetic users, historical transactions, customer risk profiles,
and deterministic demo scenarios for surveillance demonstration.
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
import os
import random
import sys
from typing import Any, Dict, List, Optional, Tuple
import uuid

from faker import Faker
import httpx
from sqlalchemy import Column, DateTime, Integer, Table, MetaData, String, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

# Setup logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_data")

fake = Faker()

# High-risk and standard countries
COMMON_COUNTRIES = ["US", "GB", "CA", "DE", "FR", "AU", "JP", "SG", "NL", "CH"]
HIGH_RISK_COUNTRIES = ["RU", "KP", "IR", "SY", "MM"]

# Merchant categories
MERCHANT_CATEGORIES = [
    "groceries",
    "supermarket",
    "electronics",
    "restaurants",
    "clothing_retail",
    "gas_station",
    "digital_services",
    "airline_tickets",
    "hotel_lodging",
    "gambling",
    "cryptocurrency_exchange",
    "wire_transfer",
]

CURRENCIES = ["USD", "EUR", "GBP", "CAD"]

DEFAULT_FRAUD_RULES: List[Dict[str, Any]] = [
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111101"),
        "name": "OFAC Embargoed / High Risk Countries",
        "rule_type": "HIGH_RISK_COUNTRY",
        "severity": "CRITICAL",
        "enabled": True,
        "parameters": '{"countries": ["RU", "KP", "IR", "SY", "MM"]}',
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111102"),
        "name": "Extreme Value Wire Transfer",
        "rule_type": "AMOUNT_THRESHOLD",
        "severity": "CRITICAL",
        "enabled": True,
        "parameters": '{"threshold": 30000.00, "operator": ">="}',
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111103"),
        "name": "High Value Transfer Threshold",
        "rule_type": "AMOUNT_THRESHOLD",
        "severity": "HIGH",
        "enabled": True,
        "parameters": '{"threshold": 10000.00, "operator": ">="}',
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111104"),
        "name": "High-Risk Merchant Monitoring",
        "rule_type": "MERCHANT_CATEGORY",
        "severity": "HIGH",
        "enabled": True,
        "parameters": '{"categories": ["cryptocurrency_exchange", "wire_transfer", "gambling"]}',
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111105"),
        "name": "Rapid Burst Velocity Window",
        "rule_type": "VELOCITY",
        "severity": "HIGH",
        "enabled": True,
        "parameters": '{"count_threshold": 5, "window_minutes": 10}',
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111106"),
        "name": "Moderate Amount Surveillance",
        "rule_type": "AMOUNT_THRESHOLD",
        "severity": "MEDIUM",
        "enabled": True,
        "parameters": '{"threshold": 5000.00, "operator": ">="}',
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111107"),
        "name": "Digital Services / Electronics Burst",
        "rule_type": "MERCHANT_CATEGORY",
        "severity": "MEDIUM",
        "enabled": True,
        "parameters": '{"categories": ["digital_services", "electronics"]}',
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111108"),
        "name": "Elevated User Risk Profile Sentinel",
        "rule_type": "USER_RISK_LEVEL",
        "severity": "LOW",
        "enabled": True,
        "parameters": '{"min_risk_score": 0.35}',
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111109"),
        "name": "Minor Foreign Currency Transfer Notice",
        "rule_type": "AMOUNT_THRESHOLD",
        "severity": "LOW",
        "enabled": True,
        "parameters": '{"threshold": 1000.00, "operator": ">="}',
    },
]


def build_db_url(cli_url: Optional[str] = None) -> str:
    """Resolves asyncpg database connection URL from CLI or environment."""
    if cli_url:
        url = cli_url
    else:
        url = os.getenv("DATABASE_URL")
        if not url:
            db_user = os.getenv("POSTGRES_USER", "postgres")
            db_pass = os.getenv("POSTGRES_PASSWORD", "postgres")
            db_host = os.getenv("POSTGRES_HOST", "localhost")
            db_port = os.getenv("POSTGRES_PORT", "5432")
            db_name = os.getenv("POSTGRES_DB", "rt_fads")
            url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def generate_synthetic_users(count: int = 100) -> List[Dict[str, Any]]:
    """Generates synthetic User entities with realistic attributes."""
    users = []
    now = datetime.now(timezone.utc)
    for _ in range(count):
        user_id = uuid.uuid4()
        full_name = fake.name()
        email_prefix = full_name.lower().replace(" ", ".").replace("'", "")
        email = f"{email_prefix}.{uuid.uuid4().hex[:6]}@{fake.free_email_domain()}"
        country = random.choice(COMMON_COUNTRIES)
        days_ago = random.randint(30, 730)
        account_created_at = now - timedelta(days=days_ago)

        users.append({
            "id": user_id,
            "full_name": full_name,
            "email": email,
            "country": country,
            "account_created_at": account_created_at,
            "is_seed_data": True,
            "created_at": account_created_at,
            "updated_at": now,
        })
    return users


def generate_historical_transactions(
    users: List[Dict[str, Any]],
    count: int = 1000,
    days_back: int = 30,
) -> List[Dict[str, Any]]:
    """Generates historical processed transactions assigned to seeded users."""
    txns = []
    now = datetime.now(timezone.utc)

    for _ in range(count):
        user = random.choice(users)
        txn_id = uuid.uuid4()
        corr_id = uuid.uuid4()

        # Log-normal distribution for realistic transaction values
        raw_amount = random.lognormvariate(mu=3.8, sigma=1.1)
        amount = Decimal(str(round(max(2.50, min(raw_amount, 18500.0)), 2)))

        # 95% home country, 5% travel
        country = user["country"] if random.random() < 0.95 else random.choice(COMMON_COUNTRIES)
        currency = "USD" if country == "US" else ("EUR" if country in ["DE", "FR", "NL"] else "GBP" if country == "GB" else "CAD")
        category = random.choice(MERCHANT_CATEGORIES)

        seconds_offset = random.randint(60, days_back * 86400)
        created_at = now - timedelta(seconds=seconds_offset)
        processed_at = created_at + timedelta(milliseconds=random.randint(120, 950))

        txns.append({
            "id": txn_id,
            "user_id": user["id"],
            "amount": amount,
            "currency": currency,
            "country": country,
            "merchant_category": category,
            "status": "PROCESSED",
            "idempotency_key": f"seed-hist-{txn_id}",
            "metadata": {"seed_origin": "historical_batch"},
            "correlation_id": corr_id,
            "created_at": created_at,
            "processed_at": processed_at,
        })

    txns.sort(key=lambda t: t["created_at"])
    return txns


def generate_risk_profiles(
    users: List[Dict[str, Any]],
    transactions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Generates initial customer RiskProfile records based on transaction volume."""
    user_txn_counts: Dict[uuid.UUID, int] = {}
    for t in transactions:
        u_id = t["user_id"]
        user_txn_counts[u_id] = user_txn_counts.get(u_id, 0) + 1

    profiles = []
    now = datetime.now(timezone.utc)

    for user in users:
        u_id = user["id"]
        txn_count = user_txn_counts.get(u_id, 0)
        # Baseline low risk score for ordinary users
        base_score = Decimal(str(round(random.uniform(0.05, 0.35), 4)))
        profiles.append({
            "user_id": u_id,
            "risk_score": base_score,
            "total_alerts": 0,
            "false_positive_count": 0,
            "last_recalculated_at": now,
        })
    return profiles


def generate_deterministic_demo_payloads(
    users: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Creates deterministic demo payloads tagged for DEMO_MODE rule triggers."""
    target_user = users[0] if users else {"id": uuid.uuid4()}
    
    return [
        {
            "amount": "48500.00",
            "currency": "USD",
            "country": "RU",
            "merchant_category": "cryptocurrency_exchange",
            "user_id": str(target_user["id"]),
            "idempotency_key": f"seed-demo-jurisdiction-{uuid.uuid4().hex[:8]}",
            "metadata": {
                "demo_scenario": "high_risk_jurisdiction",
                "notes": "Triggers High Risk Jurisdiction rule & Critical alert",
            },
        },
        {
            "amount": "9200.00",
            "currency": "USD",
            "country": "US",
            "merchant_category": "wire_transfer",
            "user_id": str(target_user["id"]),
            "idempotency_key": f"seed-demo-velocity-{uuid.uuid4().hex[:8]}",
            "metadata": {
                "demo_scenario": "velocity_burst",
                "notes": "Triggers Rapid Velocity Spike & Critical alert",
            },
        },
    ]


async def check_and_create_seed_table(conn: Any) -> bool:
    """
    Creates seed_runs marker table if needed and checks if seed data already exists.
    Returns True if previous seed run exists.
    """
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS seed_runs (
            id SERIAL PRIMARY KEY,
            run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            users_seeded INT NOT NULL,
            txns_seeded INT NOT NULL,
            demo_txns_submitted INT NOT NULL,
            notes TEXT
        );
    """))

    result = await conn.execute(text("SELECT COUNT(*) FROM seed_runs;"))
    count = result.scalar() or 0
    return count > 0


async def record_seed_run(
    conn: Any,
    users_count: int,
    txns_count: int,
    demo_count: int,
    notes: str = "Manual seed via make seed",
) -> None:
    """Inserts an execution record into seed_runs marker table."""
    await conn.execute(
        text("""
            INSERT INTO seed_runs (run_at, users_seeded, txns_seeded, demo_txns_submitted, notes)
            VALUES (NOW(), :users, :txns, :demos, :notes);
        """),
        {"users": users_count, "txns": txns_count, "demos": demo_count, "notes": notes},
    )


async def submit_demo_transactions(
    gateway_url: str,
    demo_payloads: List[Dict[str, Any]],
) -> Tuple[int, int]:
    """
    Submits demo transactions to Gateway REST API if running.
    Returns tuple of (successful_submissions, failed_submissions).
    """
    success = 0
    failed = 0

    async with httpx.AsyncClient(timeout=5.0) as client:
        for payload in demo_payloads:
            try:
                url = f"{gateway_url.rstrip('/')}/api/v1/transactions"
                res = await client.post(
                    url,
                    json=payload,
                    headers={"X-Actor": "seed_data_script", "X-Correlation-ID": str(uuid.uuid4())},
                )
                if res.status_code in [200, 201, 202]:
                    success += 1
                    logger.info(f"Demo transaction submitted successfully: {payload['metadata']['demo_scenario']}")
                else:
                    failed += 1
                    logger.warning(f"Gateway returned HTTP {res.status_code} for demo transaction: {res.text}")
            except Exception as e:
                failed += 1
                logger.info(f"Gateway not reachable at {gateway_url} ({e}); demo transaction skipped from HTTP queue.")

    return success, failed


async def run_seed(
    user_count: int = 100,
    txn_count: int = 1000,
    db_url: Optional[str] = None,
    gateway_url: str = "http://localhost:8000",
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Primary seeding execution orchestrator."""
    resolved_db_url = build_db_url(db_url)
    logger.info(f"Initializing RT-FADS data seeding (Users: {user_count}, Transactions: {txn_count})...")

    # 1. Generate in-memory dataset
    users = generate_synthetic_users(user_count)
    txns = generate_historical_transactions(users, txn_count)
    profiles = generate_risk_profiles(users, txns)
    demo_payloads = generate_deterministic_demo_payloads(users)

    if dry_run:
        logger.info("[DRY RUN] Generated data structures in memory without writing to database:")
        logger.info(f"  - Users: {len(users)}")
        logger.info(f"  - Historical Transactions: {len(txns)}")
        logger.info(f"  - Risk Profiles: {len(profiles)}")
        logger.info(f"  - Demo Transactions: {len(demo_payloads)}")
        return {
            "status": "dry_run",
            "users": len(users),
            "transactions": len(txns),
            "risk_profiles": len(profiles),
            "demo_payloads": len(demo_payloads),
        }

    engine = create_async_engine(resolved_db_url, echo=False)

    try:
        async with engine.begin() as conn:
            # 2. Check seed idempotency
            already_seeded = await check_and_create_seed_table(conn)
            if already_seeded and not force:
                logger.warning(
                    "[SKIP] Database contains prior seed records. "
                    "Use --force (or 'make seed' with FORCE=1) to override."
                )
                return {"status": "skipped", "reason": "already_seeded"}

            # 3. Insert Users
            logger.info(f"Inserting {len(users)} users into 'users' table...")
            for u in users:
                await conn.execute(
                    text("""
                        INSERT INTO users (id, full_name, email, country, account_created_at, is_seed_data, created_at, updated_at)
                        VALUES (:id, :full_name, :email, :country, :account_created_at, :is_seed_data, :created_at, :updated_at)
                        ON CONFLICT (id) DO NOTHING;
                    """),
                    u,
                )

            # 4. Insert Risk Profiles
            logger.info(f"Inserting {len(profiles)} risk profiles into 'risk_profiles' table...")
            for p in profiles:
                await conn.execute(
                    text("""
                        INSERT INTO risk_profiles (user_id, risk_score, total_alerts, false_positive_count, last_recalculated_at)
                        VALUES (:user_id, :risk_score, :total_alerts, :false_positive_count, :last_recalculated_at)
                        ON CONFLICT (user_id) DO UPDATE SET risk_score = EXCLUDED.risk_score;
                    """),
                    p,
                )

            # 5. Insert Historical Transactions
            logger.info(f"Inserting {len(txns)} transactions into 'transactions' hypertable...")
            for t in txns:
                await conn.execute(
                    text("""
                        INSERT INTO transactions (id, user_id, amount, currency, country, merchant_category, status, idempotency_key, metadata, correlation_id, created_at, processed_at)
                        VALUES (:id, :user_id, :amount, :currency, :country, :merchant_category, :status, :idempotency_key, CAST(:metadata AS jsonb), :correlation_id, :created_at, :processed_at)
                        ON CONFLICT (id, created_at) DO NOTHING;
                    """),
                    {**t, "metadata": '{"seed_origin": "historical_batch"}'},
                )

            # 6. Insert Default Fraud Rules across all severity tiers
            logger.info(f"Inserting {len(DEFAULT_FRAUD_RULES)} default fraud rules into 'fraud_rules' table...")
            for r in DEFAULT_FRAUD_RULES:
                await conn.execute(
                    text("""
                        INSERT INTO fraud_rules (id, name, rule_type, severity, enabled, parameters, created_at, updated_at)
                        VALUES (:id, :name, :rule_type, :severity, :enabled, CAST(:parameters AS jsonb), NOW(), NOW())
                        ON CONFLICT (id) DO NOTHING;
                    """),
                    r,
                )

            # 7. Record seed run marker
            await record_seed_run(conn, len(users), len(txns), len(demo_payloads))

        # 7. Submit Demo Transactions to Gateway
        logger.info(f"Submitting {len(demo_payloads)} deterministic demo transactions to Gateway ({gateway_url})...")
        demo_success, demo_failed = await submit_demo_transactions(gateway_url, demo_payloads)

        print("\n" + "=" * 70)
        print(" RT-FADS SEEDING COMPLETE")
        print("=" * 70)
        print(f" Users Inserted:                 {len(users):,}")
        print(f" Historical Transactions:        {len(txns):,}")
        print(f" Risk Profiles Initialized:      {len(profiles):,}")
        print(f" Demo Transactions Submitted:    {demo_success} succeeded, {demo_failed} offline")
        print("=" * 70 + "\n")

        return {
            "status": "success",
            "users": len(users),
            "transactions": len(txns),
            "risk_profiles": len(profiles),
            "demo_success": demo_success,
            "demo_failed": demo_failed,
        }

    finally:
        await engine.dispose()


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RT-FADS Data Seeding CLI — Inserts synthetic users and transactions.",
    )
    parser.add_argument(
        "--users",
        type=int,
        default=100,
        help="Number of synthetic users to generate (default: 100)",
    )
    parser.add_argument(
        "--transactions",
        type=int,
        default=1000,
        help="Number of historical transactions to generate (default: 1000)",
    )
    parser.add_argument(
        "--gateway-url",
        type=str,
        default="http://localhost:8000",
        help="Gateway API endpoint for submitting demo transactions (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="PostgreSQL connection string (defaults to env or localhost:5432/rt_fads)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass seed_runs check and re-seed database",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate generation in memory without writing to database",
    )
    return parser.parse_args(args)


def main() -> None:
    opts = parse_args()
    try:
        asyncio.run(
            run_seed(
                user_count=opts.users,
                txn_count=opts.transactions,
                db_url=opts.db_url,
                gateway_url=opts.gateway_url,
                force=opts.force,
                dry_run=opts.dry_run,
            )
        )
    except KeyboardInterrupt:
        logger.info("Seeding cancelled by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()
