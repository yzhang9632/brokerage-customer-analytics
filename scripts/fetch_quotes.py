# -*- coding: utf-8 -*-
"""
W2 行情 ETL：拉取沪深300成分股近一年日线，落地 CSV 缓存。

用法：
    python scripts/fetch_quotes.py --limit 5   # 试跑 5 只，验证接口与网络
    python scripts/fetch_quotes.py             # 全量约 300 只（限速约 5-10 分钟）
    python scripts/fetch_quotes.py --force     # 忽略缓存全部重拉

产出（data/raw/）：
    constituents.csv        成分股名单
    quotes/<code>.csv       每只股票一年日线（已存在则跳过，支持断点续跑）
    quotes_all.csv          合并后的全量行情（后续导入 SQLite 用）

注意：
    - 价格默认不复权（ADJUST = ""），因为后续造数要锚定当日真实成交价；
      如需前复权分析可改为 "qfq" 后加 --force 重拉。
    - 停牌缺失日直接跳过，造数只使用有行情的交易日，天然自洽。
    - 接口失败的个股会列入末尾清单，重跑本脚本即可只补拉失败的（缓存自动跳过已成功的）。
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

INDEX_CODE = "000300"  # 沪深300
ADJUST = ""            # 不复权；"qfq" = 前复权
SLEEP_SECONDS = 0.4    # 每只之间的限速，防接口封禁

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
    """获取沪深300成分股名单。AKShare 接口随版本变动，做主备两个接口回退。"""
    try:
        df = ak.index_stock_cons_csindex(INDEX_CODE)
        out = df[["成分券代码", "成分券名称"]].copy()
        out.columns = ["stock_code", "stock_name"]
        return out
    except Exception as e:
        print(f"[warn] 中证指数接口失败（{e}），改用新浪接口")
    df = ak.index_stock_cons_sina(INDEX_CODE)
    out = df[["品种代码", "品种名称"]].copy()
    out.columns = ["stock_code", "stock_name"]
    return out


def fetch_one(code: str, start: str, end: str) -> pd.DataFrame:
    """拉单只股票日线，统一为英文列名 + ISO 日期字符串。"""
    df = ak.stock_zh_a_hist(
        symbol=code, period="daily", start_date=start, end_date=end, adjust=ADJUST
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns=COLUMN_MAP)[KEEP_COLUMNS]
    df.insert(0, "stock_code", code)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="沪深300近一年日线 ETL")
    parser.add_argument("--limit", type=int, default=0, help="只拉前 N 只（调试用）")
    parser.add_argument("--force", action="store_true", help="忽略本地缓存全部重拉")
    args = parser.parse_args()

    start = (date.today() - timedelta(days=365)).strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")
    print(f"行情区间：{start} ~ {end}（不复权）")

    QUOTES_DIR.mkdir(parents=True, exist_ok=True)

    cons = fetch_constituents()
    cons.to_csv(RAW_DIR / "constituents.csv", index=False, encoding="utf-8-sig")
    print(f"成分股名单：{len(cons)} 只，已存 constituents.csv")
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
            print(f"[{i}/{total}] {code} 缓存命中（{len(cached)} 行），跳过")
            continue

        try:
            df = fetch_one(code, start, end)
            if df.empty:
                print(f"[{i}/{total}] {code} {row.stock_name} 无数据（可能长期停牌），跳过")
            else:
                df.to_csv(cache, index=False, encoding="utf-8-sig")
                frames.append(df)
                print(f"[{i}/{total}] {code} {row.stock_name} {len(df)} 行")
        except Exception as e:
            failed.append(code)
            print(f"[{i}/{total}] {code} 拉取失败：{e}")
        time.sleep(SLEEP_SECONDS)

    if frames:
        all_df = pd.concat(frames, ignore_index=True)
        # 缓存读出的是 str、新拉的是 datetime.date，统一成 ISO 字符串再合并输出
        all_df["trade_date"] = all_df["trade_date"].astype(str)
        all_df.to_csv(RAW_DIR / "quotes_all.csv", index=False, encoding="utf-8-sig")
        print(
            f"\nquotes_all.csv 已生成：{len(all_df)} 行，"
            f"{all_df['stock_code'].nunique()} 只股票，"
            f"交易日 {all_df['trade_date'].min()} ~ {all_df['trade_date'].max()}"
        )
    if failed:
        print(f"失败 {len(failed)} 只：{','.join(failed)}\n重跑本脚本即可补拉（已成功的走缓存）。")


if __name__ == "__main__":
    main()
