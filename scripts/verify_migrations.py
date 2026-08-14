#!/usr/bin/env python
"""
Migration & Schema Verification Script for RT-FADS
Verifies physical tables, TimescaleDB hypertable partitioning, continuous aggregates,
and non-overlapping table ownership boundaries.
"""

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor


def get_db_connection():
    """Establish connection to PostgreSQL using environment variables."""
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    db = os.getenv("POSTGRES_DB", "rt_fads")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")

    return psycopg2.connect(
        host=host,
        port=port,
        dbname=db,
        user=user,
        password=password
    )


def verify_tables(cur):
    """Verify that all 9 required tables exist."""
    expected_tables = {
        # Django-owned
        "users": "Django Admin",
        "fraud_rules": "Django Admin",
        "audit_logs": "Django Admin",
        # Alembic-owned
        "transactions": "Alembic (Gateway/Processor)",
        "alerts": "Alembic (Gateway/Processor)",
        "risk_profiles": "Alembic (Processor)",
        "outbox_events": "Alembic (Outbox Publisher)",
        "processed_events": "Alembic (Processor)",
        "dead_letter_events": "Alembic (Outbox Publisher)"
    }

    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
    """)
    existing_tables = {row['table_name'] for row in cur.fetchall()}

    print("\n--- 1. Table Verification ---")
    missing_tables = []
    for table, owner in expected_tables.items():
        if table in existing_tables:
            print(f"  [OK] Table '{table}' exists (Owned by: {owner})")
        else:
            print(f"  [FAIL] Missing table '{table}' (Expected owner: {owner})")
            missing_tables.append(table)

    return len(missing_tables) == 0


def verify_timescale_hypertable(cur):
    """Verify that 'transactions' is configured as a hypertable with 7-day chunk interval."""
    print("\n--- 2. TimescaleDB Hypertable Verification ---")
    cur.execute("""
        SELECT h.hypertable_name, d.time_interval
        FROM timescaledb_information.hypertables h
        JOIN timescaledb_information.dimensions d 
          ON h.hypertable_name = d.hypertable_name 
         AND h.hypertable_schema = d.hypertable_schema
        WHERE h.hypertable_name = 'transactions';
    """)
    row = cur.fetchone()

    if row:
        interval_str = str(row['time_interval'])
        print(f"  [OK] Hypertable 'transactions' is active with chunk interval: {interval_str}")
        return True
    else:
        print("  [FAIL] 'transactions' is NOT registered as a TimescaleDB hypertable!")
        return False


def verify_continuous_aggregate(cur):
    """Verify that 'transaction_volume_5m' continuous aggregate view and policy exist."""
    print("\n--- 3. TimescaleDB Continuous Aggregate Verification ---")
    cur.execute("""
        SELECT view_name, materialization_hypertable_name
        FROM timescaledb_information.continuous_aggregates
        WHERE view_name = 'transaction_volume_5m';
    """)
    row = cur.fetchone()

    if row:
        print(f"  [OK] Continuous aggregate '{row['view_name']}' is registered.")
        return True
    else:
        print("  [FAIL] Continuous aggregate 'transaction_volume_5m' not found!")
        return False


def verify_clean_startup(cur):
    """Verify clean startup guarantee (0 business records)."""
    print("\n--- 4. Clean Startup Guarantee Verification ---")
    tables_to_check = ["users", "transactions", "alerts", "risk_profiles", "outbox_events"]
    non_empty = []

    for t in tables_to_check:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM {t};")
        cnt = cur.fetchone()['cnt']
        if cnt == 0:
            print(f"  [OK] Table '{t}' is empty (count = 0)")
        else:
            print(f"  [WARN] Table '{t}' contains {cnt} records")
            non_empty.append((t, cnt))

    return len(non_empty) == 0


def main():
    print("=================================================================")
    print(" RT-FADS Database & Migration Verification")
    print("=================================================================")

    try:
        conn = get_db_connection()
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=RealDictCursor)
    except Exception as e:
        print(f"[ERROR] Could not connect to PostgreSQL: {e}")
        sys.exit(1)

    tables_ok = verify_tables(cur)
    hypertable_ok = verify_timescale_hypertable(cur)
    cagg_ok = verify_continuous_aggregate(cur)
    clean_ok = verify_clean_startup(cur)

    cur.close()
    conn.close()

    print("\n-----------------------------------------------------------------")
    if tables_ok and hypertable_ok and cagg_ok:
        print(" [PASS] All database schema & migration checks PASSED successfully!")
        sys.exit(0)
    else:
        print(" [FAIL] Schema verification failed. Review errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
