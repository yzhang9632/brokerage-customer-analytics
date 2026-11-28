# -*- coding: utf-8 -*-
"""
Fetch the remaining stock table fields: industry and list_date.
Data source: AKShare Eastmoney individual stock information API (stock_individual_info_em).

Usage: python scripts/fetch_stock_info.py
Output: data/raw/stock_info.csv (stock_code, stock_name, industry, list_date)
Each stock is saved immediately, so rerunning after an interruption resumes automatically.
"""
import time
from pathlib import Path

import akshare as ak
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
OUT = RAW_DIR / "stock_info.csv"


def fetch_one(code: str) -> tuple[str, str]:
    info = ak.stock_individual_info_em(symbol=code)
    kv = dict(zip(info["item"], info["value"]))
    industry = str(kv.get("行业", ""))
    list_raw = str(kv.get("上市时间", ""))  # Format: YYYYMMDD
    list_date = (
        f"{list_raw[:4]}-{list_raw[4:6]}-{list_raw[6:]}" if len(list_raw) == 8 else ""
    )
    return industry, list_date


def main() -> None:
    cons = pd.read_csv(RAW_DIR / "constituents.csv", dtype={"stock_code": str})
    rows = []
    if OUT.exists():
        rows = pd.read_csv(OUT, dtype={"stock_code": str}).to_dict("records")
    done_codes = {r["stock_code"] for r in rows}
    print(f"Already fetched: {len(done_codes)}; remaining: {len(cons) - len(done_codes)}", flush=True)

    for i, row in enumerate(cons.itertuples(index=False), 1):
        code = str(row.stock_code).zfill(6)
        if code in done_codes:
            continue
        try:
            industry, list_date = fetch_one(code)
            rows.append({
                "stock_code": code,
                "stock_name": row.stock_name,
                "industry": industry,
                "list_date": list_date,
            })
            print(f"[{i}/300] {code} {row.stock_name} | {industry} | {list_date}", flush=True)
        except Exception as e:
            print(f"[{i}/300] {code} failed: {e}", flush=True)
        pd.DataFrame(rows).to_csv(OUT, index=False, encoding="utf-8-sig")
        time.sleep(0.3)
    print(f"Completed: {len(rows)}/300 stocks; saved to stock_info.csv", flush=True)


if __name__ == "__main__":
    main()
