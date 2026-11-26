# -*- coding: utf-8 -*-
"""
W5 B1–B4 索引优化与可扩展性基准（PostgreSQL）。
方法论：每条查询热身 2 遍，计时 5 遍取中位数；EXPLAIN (ANALYZE, BUFFERS) 留证。

流程：优化前计时 → 建 scalability 测试表 → 加 indexes_pg.sql → 优化后计时。
产出：data/benchmark/benchmark_results.csv（B1-B3 前后对比）
      data/benchmark/scalability_results.csv（B4：10万/50万/100万行曲线）
      data/benchmark/explain_*.txt（执行计划原文，报告截图素材）
运行：export PGPASSWORD=... && python scripts/benchmark_pg.py
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
    "B1": "客户交易明细点查（Q2 类）",
    "B2": "月度成交额 TOP20（Q3，覆盖索引消除回表）",
    "B3": "单客户近 90 天成交聚合（Q10 RFM 的 F/M 计算，与 B1 共用索引）",
}


def time_query(cur, sql: str) -> float:
    """热身 2 遍 + 计时 5 遍取中位数，返回毫秒。"""
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
    # 优先抓主表 trade 的扫描行（子查询 daily_quote/month 的扫描不作为证据）
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
            print(f"trade 总行数：{total}")
            # 幂等：重跑时先回到"无优化索引"状态
            cur.execute("DROP INDEX IF EXISTS idx_trade_account_date")
            cur.execute("DROP INDEX IF EXISTS idx_trade_month_cover")
            cur.execute("VACUUM ANALYZE trade")

            results = []
            # ---------- 优化前 ----------
            for bid, sql in B_QUERIES.items():
                ms = time_query(cur, sql)
                plan = explain(cur, sql, OUT / f"explain_{bid}_before.txt")
                results.append({"benchmark": bid, "desc": B_DESCS[bid], "rows": total,
                                "before_ms": round(ms, 2), "plan_before": plan})
                print(f"{bid} 优化前：{ms:.1f} ms | {plan}")

            # ---------- B4 scalability：10万 / 50万 / 全量 ----------
            cur.execute("DROP TABLE IF EXISTS trade_100k; DROP TABLE IF EXISTS trade_500k;")
            cur.execute("CREATE TABLE trade_100k AS SELECT * FROM trade ORDER BY trade_id LIMIT 100000")
            cur.execute("CREATE TABLE trade_500k AS SELECT * FROM trade ORDER BY trade_id LIMIT 500000")
            scalability = []
            for table in ["trade_100k", "trade_500k", "trade"]:
                # 同一聚合结构，不带任何索引的全表扫描
                sql = f"SELECT stock_code, SUM(amount) FROM {table} GROUP BY stock_code"
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                n = cur.fetchone()[0]
                ms = time_query(cur, sql)
                scalability.append({"rows": n, "median_ms": round(ms, 2)})
                print(f"B4 {table}（{n} 行）：{ms:.1f} ms")
            cur.execute("DROP TABLE trade_100k; DROP TABLE trade_500k;")

            # ---------- 加索引，优化后 ----------
            cur.execute(INDEXES_SQL.read_text(encoding="utf-8"))
            cur.execute("VACUUM ANALYZE trade")  # 更新 visibility map，争取 index-only scan
            for bid, sql in B_QUERIES.items():
                ms = time_query(cur, sql)
                plan = explain(cur, sql, OUT / f"explain_{bid}_after.txt")
                r = next(x for x in results if x["benchmark"] == bid)
                r["after_ms"] = round(ms, 2)
                r["plan_after"] = plan
                print(f"{bid} 优化后：{ms:.1f} ms | {plan}")

            import pandas as pd
            df = pd.DataFrame(results)[["benchmark", "desc", "rows", "before_ms", "after_ms",
                                        "plan_before", "plan_after"]]
            df["speedup"] = (df["before_ms"] / df["after_ms"]).round(1)
            df.to_csv(OUT / "benchmark_results.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame(scalability).to_csv(OUT / "scalability_results.csv",
                                             index=False, encoding="utf-8-sig")
            print("\n" + df.to_string(index=False))
            print(f"\n结果已存：{OUT}")


if __name__ == "__main__":
    main()
