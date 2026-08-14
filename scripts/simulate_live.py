"""
Live transaction simulator for RT-FADS.
Submits continuous jittered transaction payloads to the Gateway ingestion API
as an independent process for real-time monitoring and anomaly detection.
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import logging
import os
import random
import signal
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from faker import Faker
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Setup logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("simulate_live")

fake = Faker()

COMMON_COUNTRIES = ["US", "GB", "CA", "DE", "FR", "AU", "JP", "SG", "NL", "CH"]
HIGH_RISK_COUNTRIES = ["RU", "KP", "IR", "SY", "MM"]

STANDARD_MERCHANT_CATEGORIES = [
    "groceries",
    "supermarket",
    "electronics",
    "restaurants",
    "clothing_retail",
    "gas_station",
    "digital_services",
    "hotel_lodging",
    "airline_tickets",
]

SUSPICIOUS_MERCHANT_CATEGORIES = [
    "cryptocurrency_exchange",
    "wire_transfer",
    "gambling",
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


def currency_for_country(country: str) -> str:
    """Maps country code to a standard 3-letter currency code."""
    if country == "US":
        return "USD"
    if country in ["DE", "FR", "NL"]:
        return "EUR"
    if country == "GB":
        return "GBP"
    if country == "CA":
        return "CAD"
    if country == "JP":
        return "JPY"
    if country == "AU":
        return "AUD"
    return "USD"


async def load_users_from_db(db_url: str) -> List[Dict[str, Any]]:
    """Attempts to fetch existing users from the PostgreSQL database."""
    engine = create_async_engine(db_url, echo=False)
    users: List[Dict[str, Any]] = []
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT id, country FROM users LIMIT 500;"))
            rows = result.fetchall()
            for row in rows:
                users.append({"id": row[0], "country": row[1]})
    except Exception as exc:
        logger.debug(f"Unable to load users from database: {exc}")
    finally:
        await engine.dispose()
    return users


def generate_fallback_users(count: int = 50) -> List[Dict[str, Any]]:
    """Generates an in-memory pool of synthetic users."""
    users = []
    for _ in range(count):
        users.append({
            "id": uuid.uuid4(),
            "country": random.choice(COMMON_COUNTRIES),
        })
    return users


async def resolve_user_pool(db_url: Optional[str] = None, fallback_count: int = 50) -> List[Dict[str, Any]]:
    """Resolves user pool from database or in-memory fallback."""
    resolved_url = build_db_url(db_url)
    users = await load_users_from_db(resolved_url)
    if users:
        logger.info(f"Loaded {len(users)} users from database for live simulation.")
        return users

    logger.info(f"Database users unavailable. Generated {fallback_count} synthetic users in memory.")
    return generate_fallback_users(fallback_count)


def generate_transaction_payload(
    users: List[Dict[str, Any]],
    anomalous_ratio: float = 0.10,
) -> Tuple[Dict[str, Any], bool]:
    """
    Generates a transaction payload conforming to Gateway ingestion schema.
    Returns (payload_dict, is_anomalous_flag).
    """
    user = random.choice(users) if users else {"id": uuid.uuid4(), "country": "US"}
    is_anomaly = random.random() < anomalous_ratio

    if is_anomaly:
        pattern = random.choice(["high_amount", "high_risk_country", "high_risk_merchant", "combined"])
        if pattern == "high_amount":
            amount = Decimal(str(round(random.uniform(10500.00, 48000.00), 2)))
            country = user["country"]
            currency = currency_for_country(country)
            category = random.choice(STANDARD_MERCHANT_CATEGORIES)
        elif pattern == "high_risk_country":
            raw_amount = random.lognormvariate(mu=4.0, sigma=1.0)
            amount = Decimal(str(round(max(25.0, min(raw_amount, 8000.0)), 2)))
            country = random.choice(HIGH_RISK_COUNTRIES)
            currency = "USD"
            category = random.choice(STANDARD_MERCHANT_CATEGORIES)
        elif pattern == "high_risk_merchant":
            raw_amount = random.lognormvariate(mu=4.5, sigma=1.0)
            amount = Decimal(str(round(max(50.0, min(raw_amount, 9500.0)), 2)))
            country = user["country"]
            currency = currency_for_country(country)
            category = random.choice(SUSPICIOUS_MERCHANT_CATEGORIES)
        else:  # combined
            amount = Decimal(str(round(random.uniform(12000.00, 35000.00), 2)))
            country = random.choice(HIGH_RISK_COUNTRIES)
            currency = "USD"
            category = random.choice(SUSPICIOUS_MERCHANT_CATEGORIES)

        payload = {
            "amount": str(amount),
            "currency": currency,
            "country": country,
            "merchant_category": category,
            "user_id": str(user["id"]),
            "idempotency_key": f"sim-live-{uuid.uuid4().hex}",
            "metadata": {
                "simulator": True,
                "pattern": pattern,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        return payload, True

    # Normal transaction
    raw_amount = random.lognormvariate(mu=3.5, sigma=0.9)
    amount = Decimal(str(round(max(2.50, min(raw_amount, 450.0)), 2)))
    # 95% home country, 5% foreign common country
    country = user["country"] if random.random() < 0.95 else random.choice(COMMON_COUNTRIES)
    currency = currency_for_country(country)
    category = random.choice(STANDARD_MERCHANT_CATEGORIES)

    payload = {
        "amount": str(amount),
        "currency": currency,
        "country": country,
        "merchant_category": category,
        "user_id": str(user["id"]),
        "idempotency_key": f"sim-live-{uuid.uuid4().hex}",
        "metadata": {
            "simulator": True,
            "pattern": "normal",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    return payload, False


@dataclass
class SimulationStats:
    """Tracks live simulation execution statistics."""
    start_time: float = field(default_factory=time.time)
    total_submitted: int = 0
    total_accepted: int = 0
    total_failed: int = 0
    anomalous_count: int = 0
    latencies: List[float] = field(default_factory=list)

    def record_submission(self, success: bool, latency_ms: float, is_anomalous: bool) -> None:
        self.total_submitted += 1
        if is_anomalous:
            self.anomalous_count += 1
        if success:
            self.total_accepted += 1
            self.latencies.append(latency_ms)
        else:
            self.total_failed += 1

    def print_summary(self) -> None:
        elapsed = time.time() - self.start_time
        avg_latency = (sum(self.latencies) / len(self.latencies)) if self.latencies else 0.0

        print("\n" + "=" * 70)
        print(" RT-FADS LIVE SIMULATION SUMMARY")
        print("=" * 70)
        print(f" Elapsed Time:                  {elapsed:.1f}s")
        print(f" Total Transactions Generated:  {self.total_submitted:,}")
        print(f" Successful (HTTP 202):         {self.total_accepted:,}")
        print(f" Failed Submissions:            {self.total_failed:,}")
        print(f" Anomalous Patterns Submitted:  {self.anomalous_count:,}")
        print(f" Average Gateway Latency:       {avg_latency:.2f} ms")
        print("=" * 70 + "\n")


async def submit_transaction_http(
    client: httpx.AsyncClient,
    gateway_url: str,
    payload: Dict[str, Any],
) -> Tuple[bool, int, float, Optional[str]]:
    """
    Submits a transaction payload to the Gateway REST API.
    Returns (success_bool, status_code, latency_ms, transaction_id_or_err).
    """
    url = f"{gateway_url.rstrip('/')}/api/v1/transactions"
    corr_id = str(uuid.uuid4())
    headers = {
        "X-Actor": "live_simulator",
        "X-Correlation-ID": corr_id,
    }

    start_t = time.perf_counter()
    try:
        response = await client.post(url, json=payload, headers=headers)
        latency_ms = (time.perf_counter() - start_t) * 1000.0

        if response.status_code in [200, 201, 202]:
            data = response.json()
            txn_id = data.get("transaction_id")
            return True, response.status_code, latency_ms, txn_id
        return False, response.status_code, latency_ms, response.text
    except Exception as exc:
        latency_ms = (time.perf_counter() - start_t) * 1000.0
        return False, 0, latency_ms, str(exc)


async def run_simulator(
    gateway_url: str = "http://localhost:8000",
    interval_min: float = 3.0,
    interval_max: float = 5.0,
    db_url: Optional[str] = None,
    count: Optional[int] = None,
    anomalous_ratio: float = 0.10,
    dry_run: bool = False,
    users_pool_override: Optional[List[Dict[str, Any]]] = None,
) -> SimulationStats:
    """Main simulation loop handling continuous submission with jittered intervals."""
    stats = SimulationStats()
    shutdown_event = asyncio.Event()

    # Register OS signal handlers for graceful shutdown where available
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, shutdown_event.set)
            except (NotImplementedError, RuntimeError):
                pass

    users = users_pool_override or await resolve_user_pool(db_url)

    logger.info("=" * 70)
    logger.info("RT-FADS Live Transaction Simulator Running")
    logger.info(f"Target Gateway:    {gateway_url}")
    logger.info(f"Interval Window:   [{interval_min:.1f}s - {interval_max:.1f}s] (jittered)")
    logger.info(f"Anomalous Ratio:   {anomalous_ratio * 100:.0f}%")
    logger.info(f"User Pool Size:    {len(users)}")
    if count:
        logger.info(f"Transaction Cap:   {count}")
    if dry_run:
        logger.info("Mode:              DRY RUN (no network requests)")
    logger.info("Press Ctrl+C to terminate cleanly.")
    logger.info("=" * 70)

    async with httpx.AsyncClient(timeout=10.0) as client:
        seq = 0
        try:
            while not shutdown_event.is_set():
                seq += 1
                payload, is_anom = generate_transaction_payload(users, anomalous_ratio)
                tag = "[ANOMALY]" if is_anom else "[NORMAL]"

                if dry_run:
                    stats.record_submission(success=True, latency_ms=0.0, is_anomalous=is_anom)
                    logger.info(
                        f"#{seq:04d} {tag} DRY-RUN Txn | User: {payload['user_id'][:8]}... | "
                        f"${payload['amount']} {payload['currency']} | {payload['country']} | {payload['merchant_category']}"
                    )
                else:
                    success, code, latency, result = await submit_transaction_http(client, gateway_url, payload)
                    stats.record_submission(success=success, latency_ms=latency, is_anomalous=is_anom)

                    if success:
                        logger.info(
                            f"#{seq:04d} {tag} HTTP {code} ({latency:5.1f}ms) | Txn: {result} | "
                            f"${payload['amount']} {payload['currency']} | {payload['country']} | {payload['merchant_category']}"
                        )
                    else:
                        logger.warning(
                            f"#{seq:04d} {tag} HTTP {code} ({latency:5.1f}ms) Failed: {result} | "
                            f"${payload['amount']} {payload['currency']} | {payload['country']}"
                        )

                if count and seq >= count:
                    logger.info(f"Reached specified limit of {count} transactions. Stopping simulation.")
                    break

                # Sleep with random jitter
                jitter_delay = random.uniform(interval_min, interval_max)
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=jitter_delay)
                except asyncio.TimeoutError:
                    pass

        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("Simulation interrupted by user signal.")
        finally:
            stats.print_summary()

    return stats


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parses command-line arguments for the simulator."""
    parser = argparse.ArgumentParser(
        description="RT-FADS Live Transaction Simulator — Emits continuous jittered traffic to Gateway API.",
    )
    parser.add_argument(
        "--gateway-url",
        type=str,
        default=os.getenv("GATEWAY_URL", "http://localhost:8000"),
        help="Gateway API endpoint (default: http://localhost:8000 or GATEWAY_URL env)",
    )
    parser.add_argument(
        "--interval-min",
        type=float,
        default=3.0,
        help="Minimum delay between transactions in seconds (default: 3.0)",
    )
    parser.add_argument(
        "--interval-max",
        type=float,
        default=5.0,
        help="Maximum delay between transactions in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="PostgreSQL connection URL to fetch seeded users (optional)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Total number of transactions to submit before exiting (default: infinite until Ctrl+C)",
    )
    parser.add_argument(
        "--anomalous-ratio",
        type=float,
        default=0.10,
        help="Ratio of generated transactions with anomalous characteristics (default: 0.10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate transactions in memory without submitting HTTP requests",
    )
    return parser.parse_args(args)


def main() -> None:
    opts = parse_args()
    if opts.interval_min < 0 or opts.interval_max < opts.interval_min:
        logger.error("Error: --interval-min must be >= 0 and --interval-max must be >= --interval-min.")
        sys.exit(1)

    try:
        asyncio.run(
            run_simulator(
                gateway_url=opts.gateway_url,
                interval_min=opts.interval_min,
                interval_max=opts.interval_max,
                db_url=opts.db_url,
                count=opts.count,
                anomalous_ratio=opts.anomalous_ratio,
                dry_run=opts.dry_run,
            )
        )
    except KeyboardInterrupt:
        logger.info("Simulator terminated cleanly.")
        sys.exit(0)


if __name__ == "__main__":
    main()
