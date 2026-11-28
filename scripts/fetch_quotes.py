# -*- coding: utf-8 -*-
"""
W2 market data ETL: fetch one year of daily quotes for CSI 300 constituents and cache them as CSV files.

Usage:
    python scripts/fetch_quotes.py --limit 5   # Test with 5 stocks to verify the API and network
    python scripts/fetch_quotes.py             # Full run of about 300 stocks (throttled; takes about 5-10 minutes)
    python scripts/fetch_quotes.py --force     # Ignore the cache and fetch everything again

Outputs (data/raw/):
    constituents.csv        Constituent list
    quotes/<code>.csv       One year of daily quotes per stock (existing files are skipped to support resuming)
    quotes_all.csv          Merged quotes for all stocks (for subsequent import into SQLite)

Notes:
    - Prices are unadjusted by default (ADJUST = "") because later data generation must use actual traded prices;
      for forward-adjusted analysis, change this to "qfq" and rerun with --force.
    - Days missing due to trading suspensions are skipped. Data generation uses only trading days with quotes,
      keeping the data internally consistent.
    - Stocks that fail to fetch are listed at the end. Rerun this script to retry only those stocks;
      successfully fetched stocks are skipped automatically through the cache.
"""
import argparse
import time
from datetime import date, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
QUOTES_DIR = RAW_DIR / "quotes"

INDEX_CODE = "000300"  # CSI 300
ADJUST = ""            # Unadjusted; "qfq" = forward-adjusted
SLEEP_SECONDS = 0.4    # Throttle between stocks to avoid API rate limiting

COLUMN_MAP = {
    "日期": "trade_date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
}
KEEP_COLUMNS = ["trade_date", "open", "high", "low", "close", "volume", "amount"]


def fetch_constituents() -> pd.DataFrame:
    """Fetch the CSI 300 constituent list, with fallback between two AKShare APIs that vary by version."""
    try:
        df = ak.index_stock_cons_csindex(INDEX_CODE)
        out = df[["成分券代码", "成分券名称"]].copy()
        out.columns = ["stock_code", "stock_name"]
        return out
    except Exception as e:
        print(f"[warn] CSI Index API failed ({e}); falling back to the Sina API")
    df = ak.index_stock_cons_sina(INDEX_CODE)
    out = df[["品种代码", "品种名称"]].copy()
    out.columns = ["stock_code", "stock_name"]
    return out


def fetch_one(code: str, start: str, end: str) -> pd.DataFrame:
    """Fetch daily quotes for one stock and standardize English column names and ISO date strings."""
    df = ak.stock_zh_a_hist(
        symbol=code, period="daily", start_date=start, end_date=end, adjust=ADJUST
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns=COLUMN_MAP)[KEEP_COLUMNS]
    df.insert(0, "stock_code", code)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="CSI 300 one-year daily quote ETL")
    parser.add_argument("--limit", type=int, default=0, help="Fetch only the first N stocks (for debugging)")
    parser.add_argument("--force", action="store_true", help="Ignore the local cache and fetch everything again")
    args = parser.parse_args()

    start = (date.today() - timedelta(days=365)).strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")
    print(f"Quote range: {start} to {end} (unadjusted)")

    QUOTES_DIR.mkdir(parents=True, exist_ok=True)

    cons = fetch_constituents()
    cons.to_csv(RAW_DIR / "constituents.csv", index=False, encoding="utf-8-sig")
    print(f"Constituents: {len(cons)} stocks; saved to constituents.csv")
    if args.limit:
        cons = cons.head(args.limit)

    frames, failed = [], []
    total = len(cons)
    for i, row in enumerate(cons.itertuples(index=False), 1):
        code = str(row.stock_code).zfill(6)
        cache = QUOTES_DIR / f"{code}.csv"

        if cache.exists() and not args.force:
            cached = pd.read_csv(cache, dtype={"stock_code": str})
            frames.append(cached)
            print(f"[{i}/{total}] {code} cache hit ({len(cached)} rows); skipped")
            continue

        try:
            df = fetch_one(code, start, end)
            if df.empty:
                print(f"[{i}/{total}] {code} {row.stock_name} has no data (possibly suspended); skipped")
            else:
                df.to_csv(cache, index=False, encoding="utf-8-sig")
                frames.append(df)
                print(f"[{i}/{total}] {code} {row.stock_name}: {len(df)} rows")
        except Exception as e:
            failed.append(code)
            print(f"[{i}/{total}] {code} fetch failed: {e}")
        time.sleep(SLEEP_SECONDS)

    if frames:
        all_df = pd.concat(frames, ignore_index=True)
        # Cached dates are read as str while newly fetched dates are datetime.date;
        # standardize them as ISO strings before merging and writing.
        all_df["trade_date"] = all_df["trade_date"].astype(str)
        all_df.to_csv(RAW_DIR / "quotes_all.csv", index=False, encoding="utf-8-sig")
        print(
            f"\nquotes_all.csv generated: {len(all_df)} rows, "
            f"{all_df['stock_code'].nunique()} stocks, "
            f"trading dates {all_df['trade_date'].min()} to {all_df['trade_date'].max()}"
        )
    if failed:
        print(f"Failed: {len(failed)} stocks: {','.join(failed)}\nRerun this script to retry them (successful stocks use the cache).")


if __name__ == "__main__":
    main()
