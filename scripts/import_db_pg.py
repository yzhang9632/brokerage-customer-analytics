# -*- coding: utf-8 -*-
"""
Production PostgreSQL one-step rebuild: clear the public schema in the brokerage database,
create 9 tables, then import CSV files with COPY.

First-time setup (only once):
    createdb -h 127.0.0.1 -U postgres brokerage
Set the connection environment variable before running (do not hard-code the password):
    Windows PowerShell: $env:PGPASSWORD="your_password"
    Git Bash:           export PGPASSWORD="your_password"
    python scripts/import_db_pg.py
Optional environment variables: PGHOST (default 127.0.0.1), PGPORT (5432), PGUSER (postgres),
PGDATABASE (brokerage).
"""
import argparse
import os
from pathlib import Path

import pandas as pd
import psycopg

BASE_DIR = Path(__file__).resolve().parents[1]
_env = BASE_DIR / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if _line.strip() and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
SCHEMA = BASE_DIR / "sql" / "schema_pg.sql"
RAW = BASE_DIR / "data" / "raw"
GEN = BASE_DIR / "data" / "generated"

TABLES = ["branch", "customer", "account", "stock", "daily_quote",
          "trade", "fund_flow", "position_snapshot", "asset_snapshot"]


def load_csv(cur: psycopg.Cursor, table: str, path: Path, dtype=None) -> None:
    if not path.exists():
        print(f"  [SKIP] {path.name} does not exist")
        return
    df = pd.read_csv(path, dtype=dtype)
    if table == "trade" and "month" not in df.columns:
        # PostgreSQL generated columns require immutable expressions; date-to-text conversion
        # does not qualify, so the import script generates the month instead.
        df["month"] = df["trade_date"].astype(str).str[:7]
    if df.empty:
        print(f"  [SKIP] {table}: 0 rows")
        return
    # PostgreSQL COPY is much faster than row-by-row INSERT and also scales to millions of rows.
    csv_text = df.to_csv(index=False, header=False)
    columns = ",".join(df.columns)
    with cur.copy(f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT CSV)") as copy:
        copy.write(csv_text)
    print(f"  {table}: {len(df)} rows")


def main() -> None:
    parser = argparse.ArgumentParser(description="PostgreSQL data import")
    parser.add_argument("--sample", action="store_true", help="Import the small demo dataset bundled in data/sample")
    args = parser.parse_args()
    raw_dir = BASE_DIR / "data" / "sample" if args.sample else RAW
    gen_dir = BASE_DIR / "data" / "sample" if args.sample else GEN

    dsn = {
        "host": os.getenv("PGHOST", "127.0.0.1"),
        "port": int(os.getenv("PGPORT", "5432")),
        "user": os.getenv("PGUSER", "postgres"),
        "password": os.getenv("PGPASSWORD", ""),
        "dbname": os.getenv("PGDATABASE", "brokerage"),
    }
    with psycopg.connect(**dsn) as conn:
        with conn.cursor() as cur:
            print("Rebuilding the public schema and creating tables:")
            cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            cur.execute(SCHEMA.read_text(encoding="utf-8"))

            print("Loading real market data:")
            load_csv(cur, "stock", raw_dir / "stock_info.csv", dtype={"stock_code": str})
            load_csv(cur, "daily_quote", raw_dir / "quotes_all.csv", dtype={"stock_code": str})

            print("Loading generated data:")
            for table in ["branch", "customer", "account", "fund_flow", "trade",
                          "position_snapshot", "asset_snapshot"]:
                load_csv(cur, table, gen_dir / f"{table}.csv",
                         dtype={"stock_code": str} if table in ("trade", "position_snapshot") else None)

        conn.commit()
        with conn.cursor() as cur:
            print("\nRow counts by table:")
            for table in TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                print(f"  {table}: {cur.fetchone()[0]}")
    print(f"\nPostgreSQL database rebuilt: {dsn['dbname']}")


if __name__ == "__main__":
    main()
