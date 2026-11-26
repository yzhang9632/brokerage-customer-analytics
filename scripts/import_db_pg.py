# -*- coding: utf-8 -*-
"""
PostgreSQL 正式版一键重建：清空 brokerage 库的 public schema → 建 9 表 → COPY 导入 CSV。

首次准备（只需一次）：
    createdb -h 127.0.0.1 -U postgres brokerage
运行前设置连接环境变量（密码不写进代码）：
    Windows PowerShell: $env:PGPASSWORD="你的密码"
    Git Bash:           export PGPASSWORD="你的密码"
    python scripts/import_db_pg.py
可选环境变量：PGHOST（默认 127.0.0.1）、PGPORT（5432）、PGUSER（postgres）、PGDATABASE（brokerage）。
"""
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
        print(f"  [跳过] {path.name} 不存在")
        return
    df = pd.read_csv(path, dtype=dtype)
    if table == "trade" and "month" not in df.columns:
        # PostgreSQL 生成列要求表达式不可变，日期转文本不满足；改由导入脚本生成月份
        df["month"] = df["trade_date"].astype(str).str[:7]
    if df.empty:
        print(f"  [跳过] {table} 0 行")
        return
    # PostgreSQL COPY：比逐行 INSERT 快得多，百万行扩量也适用
    csv_text = df.to_csv(index=False, header=False)
    columns = ",".join(df.columns)
    with cur.copy(f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT CSV)") as copy:
        copy.write(csv_text)
    print(f"  {table}: {len(df)} 行")


def main() -> None:
    dsn = {
        "host": os.getenv("PGHOST", "127.0.0.1"),
        "port": int(os.getenv("PGPORT", "5432")),
        "user": os.getenv("PGUSER", "postgres"),
        "password": os.getenv("PGPASSWORD", ""),
        "dbname": os.getenv("PGDATABASE", "brokerage"),
    }
    with psycopg.connect(**dsn) as conn:
        with conn.cursor() as cur:
            print("重建 public schema 并建表：")
            cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            cur.execute(SCHEMA.read_text(encoding="utf-8"))

            print("灌入真实层：")
            load_csv(cur, "stock", RAW / "stock_info.csv", dtype={"stock_code": str})
            load_csv(cur, "daily_quote", RAW / "quotes_all.csv", dtype={"stock_code": str})

            print("灌入生成层：")
            for table in ["branch", "customer", "account", "fund_flow", "trade",
                          "position_snapshot", "asset_snapshot"]:
                load_csv(cur, table, GEN / f"{table}.csv",
                         dtype={"stock_code": str} if table in ("trade", "position_snapshot") else None)

        conn.commit()
        with conn.cursor() as cur:
            print("\n各表行数：")
            for table in TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                print(f"  {table}: {cur.fetchone()[0]}")
    print("\nPostgreSQL 数据库已重建：brokerage")


if __name__ == "__main__":
    main()
