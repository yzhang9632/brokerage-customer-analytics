# -*- coding: utf-8 -*-
"""
W5 B1-B4 index optimization and scalability benchmarks (PostgreSQL).
Methodology: warm up each query twice, time five runs, and take the median;
retain EXPLAIN (ANALYZE, BUFFERS) output as evidence.

Workflow: time queries before optimization -> create scalability test tables ->
apply indexes_pg.sql -> time queries after optimization.
Outputs: data/benchmark/benchmark_results.csv (before/after comparison for B1-B3)
         data/benchmark/scalability_results.csv (B4 curves for 100k/500k/1M rows)
         data/benchmark/explain_*.txt (raw execution plans for report screenshots)
Run: export PGPASSWORD=... && python scripts/benchmark_pg.py
"""
import os
import re
import statistics
import time
from pathlib import Path

import psycopg

BASE_DIR = Path(__file__).resolve().parents[1]
_env = BASE_DIR / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if _line.strip() and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
OUT = BASE_DIR / "data" / "benchmark"
INDEXES_SQL = BASE_DIR / "sql" / "indexes_pg.sql"

B_QUERIES = {
    "B1": "SELECT * FROM trade WHERE account_id = 42 ORDER BY trade_date",
    "B2": """SELECT stock_code, SUM(amount) AS turnover FROM trade
             WHERE month = (SELECT MAX(month) FROM trade)
             GROUP BY stock_code ORDER BY turnover DESC LIMIT 20""",
    "B3": """SELECT COUNT(*), SUM(amount) FROM trade
             WHERE account_id = 42
               AND trade_date >= (SELECT MAX(trade_date) FROM daily_quote) - 90""",
}

B_DESCS = {
    "B1": "Customer trade detail lookup (Q2 type)",
    "B2": "Top 20 stocks by monthly turnover (Q3; covering index avoids table lookups)",
    "B3": "90-day trade aggregation for one customer (F/M calculation for Q10 RFM; shares an index with B1)",
}


def time_query(cur, sql: str) -> float:
    """Warm up twice, time five runs, and return the median in milliseconds."""
    for _ in range(2):
        cur.execute(sql)
        cur.fetchall()
    samples = []
    for _ in range(5):
        t0 = time.perf_counter()
        cur.execute(sql)
        cur.fetchall()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples)


def explain(cur, sql: str, path: Path) -> str:
    cur.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}")
    lines = [r[0] for r in cur.fetchall()]
    path.write_text("\n".join(lines), encoding="utf-8")
    # Prefer the scan of the main trade table; scans in daily_quote/month subqueries are not used as evidence.
    scans = [l for l in lines if "Scan" in l]
    if not scans:
        return lines[0]
    pool = [l for l in scans if "on trade" in l] or scans
    top = min(pool, key=lambda l: len(l) - len(l.lstrip()))
    return top.strip()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(
        host=os.getenv("PGHOST", "127.0.0.1"), port=int(os.getenv("PGPORT", "5432")),
        user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD", ""),
        dbname=os.getenv("PGDATABASE", "brokerage"),
    ) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trade")
            total = cur.fetchone()[0]
            print(f"Total rows in trade: {total}")
            # Idempotency: restore the unoptimized index state before each rerun.
            cur.execute("DROP INDEX IF EXISTS idx_trade_account_date")
            cur.execute("DROP INDEX IF EXISTS idx_trade_month_cover")
            cur.execute("VACUUM ANALYZE trade")

            results = []
            # ---------- Before optimization ----------
            for bid, sql in B_QUERIES.items():
                ms = time_query(cur, sql)
                plan = explain(cur, sql, OUT / f"explain_{bid}_before.txt")
                results.append({"benchmark": bid, "desc": B_DESCS[bid], "rows": total,
                                "before_ms": round(ms, 2), "plan_before": plan})
                print(f"{bid} before optimization: {ms:.1f} ms | {plan}")

            # ---------- B4 scalability: 100k / 500k / full dataset ----------
            cur.execute("DROP TABLE IF EXISTS trade_100k; DROP TABLE IF EXISTS trade_500k;")
            cur.execute("CREATE TABLE trade_100k AS SELECT * FROM trade ORDER BY trade_id LIMIT 100000")
            cur.execute("CREATE TABLE trade_500k AS SELECT * FROM trade ORDER BY trade_id LIMIT 500000")
            scalability = []
            for table in ["trade_100k", "trade_500k", "trade"]:
                # Same aggregation structure, with a full table scan and no indexes.
                sql = f"SELECT stock_code, SUM(amount) FROM {table} GROUP BY stock_code"
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                n = cur.fetchone()[0]
                ms = time_query(cur, sql)
                scalability.append({"rows": n, "median_ms": round(ms, 2)})
                print(f"B4 {table} ({n} rows): {ms:.1f} ms")
            cur.execute("DROP TABLE trade_100k; DROP TABLE trade_500k;")

            # ---------- Add indexes, then measure after optimization ----------
            cur.execute(INDEXES_SQL.read_text(encoding="utf-8"))
            cur.execute("VACUUM ANALYZE trade")  # Update the visibility map to enable index-only scans.
            for bid, sql in B_QUERIES.items():
                ms = time_query(cur, sql)
                plan = explain(cur, sql, OUT / f"explain_{bid}_after.txt")
                r = next(x for x in results if x["benchmark"] == bid)
                r["after_ms"] = round(ms, 2)
                r["plan_after"] = plan
                print(f"{bid} after optimization: {ms:.1f} ms | {plan}")

            import pandas as pd
            df = pd.DataFrame(results)[["benchmark", "desc", "rows", "before_ms", "after_ms",
                                        "plan_before", "plan_after"]]
            df["speedup"] = (df["before_ms"] / df["after_ms"]).round(1)
            df.to_csv(OUT / "benchmark_results.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame(scalability).to_csv(OUT / "scalability_results.csv",
                                             index=False, encoding="utf-8-sig")
            print("\n" + df.to_string(index=False))
            print(f"\nResults saved to: {OUT}")


if __name__ == "__main__":
    main()
