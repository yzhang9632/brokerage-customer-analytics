# -*- coding: utf-8 -*-
"""
W3 造数脚本：生成 7 张业务表 CSV（branch/customer/account/fund_flow/trade/两张月末快照）。

真实性规则（报告"数据生成方法论"素材）：
  1. 交易日期只取 quotes_all.csv 中的真实交易日；
  2. 成交价落在当日真实 [low, high] 区间，保留两位小数；
  3. 数量为 100 整数倍，amount = price × volume，忽略佣金（口径写入报告）；
  4. 先入金后交易：维护每账户现金账本与持仓账本，买入不超现金、卖出不超持仓；
  5. 5 种客户画像：dca 定投 / active 活跃 / trend 趋势 / dormant 沉睡 / whale 大户；
  6. 月末快照由流水 + 真实收盘价聚合，非独立编造。

用法：
    python scripts/generate_data.py --customers 100 --months 1     # v1 小样本（M3）
    python scripts/generate_data.py --customers 5000 --months 12   # 全量
输出：data/generated/*.csv，随机种子固定，全组重跑结果一致。
"""
import argparse
import random
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
OUT_DIR = BASE_DIR / "data" / "generated"

BRANCHES = [
    (1, "深圳福田营业部", "深圳"), (2, "深圳南山营业部", "深圳"),
    (3, "广州天河营业部", "广州"), (4, "上海浦东营业部", "上海"),
    (5, "上海静安营业部", "上海"), (6, "北京朝阳营业部", "北京"),
    (7, "北京海淀营业部", "北京"), (8, "成都高新营业部", "成都"),
    (9, "杭州西湖营业部", "杭州"), (10, "香港中环营业部", "香港"),
]

# 画像比例与参数（全组可改，报告里写这张表）
PERSONA_WEIGHTS = {"dca": 0.20, "active": 0.15, "trend": 0.35, "dormant": 0.25, "whale": 0.05}
SURNAMES = "张王李赵刘陈杨黄周吴徐孙马朱胡郭何罗高林郑梁谢宋唐许韩冯邓曹彭"
GIVEN = "伟芳娜敏静丽强磊军洋勇艳杰涛明超秀英霞平刚桂英雨欣子轩宇辰思远一诺浩然"

RISK_LEVELS = ["C1", "C2", "C3", "C4", "C5"]


def random_name(rng: random.Random) -> str:
    return rng.choice(SURNAMES) + "".join(rng.choice(GIVEN) for _ in range(rng.randint(1, 2)))


def random_time(rng: random.Random) -> str:
    """A 股连续竞价时段 09:30-11:30 / 13:00-15:00。"""
    if rng.random() < 0.55:
        minute = rng.randint(9 * 60 + 30, 11 * 60 + 30)
    else:
        minute = rng.randint(13 * 60, 15 * 60)
    return f"{minute // 60:02d}:{minute % 60:02d}:{rng.randint(0, 59):02d}"


def lot(amount_cash: float, price: float, rng: random.Random, max_lots: int = 50) -> int:
    """把预算金额换成整手股数，不足一手返回 0。"""
    affordable = int(amount_cash / price / 100)
    if affordable <= 0:
        return 0
    return rng.randint(1, min(affordable, max_lots)) * 100


def main() -> None:
    parser = argparse.ArgumentParser(description="券商零售客户造数脚本")
    parser.add_argument("--customers", type=int, default=100)
    parser.add_argument("--months", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    # ---------- 真实行情与交易日历 ----------
    quotes = pd.read_csv(RAW_DIR / "quotes_all.csv", dtype={"stock_code": str})
    quotes["trade_date"] = quotes["trade_date"].astype(str)
    end = quotes["trade_date"].max()
    start = str((pd.Timestamp(end) - pd.DateOffset(months=args.months) + pd.Timedelta(days=1)).date())
    win = quotes[(quotes["trade_date"] >= start) & (quotes["trade_date"] <= end)]
    trading_days = sorted(win["trade_date"].unique())
    price_map = {(r.stock_code, r.trade_date): (r.low, r.high, r.close > r.open)
                 for r in win.itertuples(index=False)}
    stock_codes = sorted(win["stock_code"].unique())
    months = sorted({d[:7] for d in trading_days})
    # 每月每股的月末收盘价（快照估值用）
    month_last_close = {}
    for (code, month), grp in win.groupby(["stock_code", win["trade_date"].str[:7]]):
        month_last_close[(code, month)] = float(grp.sort_values("trade_date")["close"].iloc[-1])
    print(f"交易窗口：{trading_days[0]} ~ {trading_days[-1]}，{len(trading_days)} 个交易日，{len(months)} 个月")

    # ---------- 静态表 ----------
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(BRANCHES, columns=["branch_id", "branch_name", "city"]).to_csv(
        OUT_DIR / "branch.csv", index=False, encoding="utf-8-sig")

    personas = list(PERSONA_WEIGHTS)
    weights = list(PERSONA_WEIGHTS.values())
    customers, accounts, fund_flows, trades = [], [], [], []
    first_day = trading_days[0]

    for cid in range(1, args.customers + 1):
        persona = rng.choices(personas, weights)[0]
        branch_id = rng.randint(1, len(BRANCHES))
        # 沉睡型开户在窗口附近（只交易前 2 个月），其余开户在 1-3 年前
        if persona == "dormant":
            open_date = str((pd.Timestamp(first_day) - pd.Timedelta(days=rng.randint(0, 45))).date())
        else:
            open_date = str((pd.Timestamp(first_day) - pd.Timedelta(days=rng.randint(365, 365 * 3))).date())
        customers.append((cid, random_name(rng), rng.choice("MF"), rng.randint(1955, 2005),
                          branch_id, open_date, rng.choices(RISK_LEVELS, [1, 2, 4, 3, 1])[0]))
        accounts.append((cid, cid, "cash", open_date, "active"))  # 每客户 1 个账户，id 一致

        # 初始入金：普通 5-50 万，大户 300-1000 万；沉睡高净值也入金（Q9 素材）
        init_cash = rng.uniform(3e6, 1e7) if persona == "whale" else rng.uniform(5e4, 5e5)
        fund_flows.append((cid, first_day, "in", round(init_cash, 2)))

        cash = init_cash
        holdings = {}  # stock_code -> [shares, avg_cost]
        trade_days_used = []
        if persona == "dormant":
            active_end = str((pd.Timestamp(open_date) + pd.Timedelta(days=60)).date())
            trade_days_used = [d for d in trading_days if open_date <= d <= active_end]
        else:
            trade_days_used = trading_days

        # 按月组织交易日
        days_by_month = {}
        for d in trade_days_used:
            days_by_month.setdefault(d[:7], []).append(d)

        dca_stock = rng.choice(stock_codes)
        dca_amount = rng.uniform(2000, 10000)
        dca_day = rng.randint(1, 28)

        for month, days in sorted(days_by_month.items()):
            if persona == "active":
                # 高频活跃客户一天可有 1-2 笔（每月交易日仅约 22 天）
                base = rng.sample(days, min(len(days), rng.randint(18, 25)))
                plan_days = base + [rng.choice(days) for _ in range(rng.randint(8, 15))]
            elif persona == "trend":
                plan_days = rng.sample(days, min(len(days), rng.randint(6, 12)))
            elif persona == "whale":
                plan_days = rng.sample(days, min(len(days), rng.randint(0, 2)))
            elif persona == "dca":
                plan_days = [next((d for d in days if int(d[8:10]) >= dca_day), days[-1])]
            else:  # dormant
                plan_days = rng.sample(days, min(len(days), rng.randint(3, 8)))

            for d in sorted(plan_days):
                # 定投：每月固定日先转入再买入同一只股
                if persona == "dca":
                    fund_flows.append((cid, d, "in", round(dca_amount, 2)))
                    cash += dca_amount
                    code = dca_stock
                    side = "buy"
                else:
                    code = rng.choice(stock_codes)
                    # 无持仓只能买；有持仓时趋势/活跃 30% 概率卖，大户基本只买
                    can_sell = bool(holdings) and persona in ("active", "trend")
                    side = "sell" if can_sell and rng.random() < 0.3 else "buy"
                    if side == "sell":
                        code = rng.choice(list(holdings))
                    elif persona == "trend":
                        # 趋势型：优先选当日上涨股（close>open），字典查询避免全表扫描
                        for _ in range(5):
                            q = price_map.get((code, d))
                            if q and q[2]:
                                break
                            code = rng.choice(stock_codes)

                if (code, d) not in price_map:
                    continue
                low, high, _ = price_map[(code, d)]
                price = round(rng.uniform(low, high), 2)

                if side == "buy":
                    budget = cash if persona == "dca" else cash * rng.uniform(0.1, 0.5)
                    max_lots = 200 if persona == "whale" else 30
                    volume = lot(budget, price, rng, max_lots)
                    amount = round(price * volume, 2) if volume else 0.0
                    if (volume == 0 or amount > cash) and persona in ("active", "trend", "whale") \
                            and rng.random() < 0.6:
                        # 现金不足一手：活跃/趋势/大户 60% 概率追加银证入金后再买（真实补仓行为）
                        topup = round(init_cash * rng.uniform(0.2, 0.5), 2)
                        fund_flows.append((cid, d, "in", topup))
                        cash += topup
                        volume = lot(cash * rng.uniform(0.1, 0.5), price, rng, max_lots)
                        amount = round(price * volume, 2) if volume else 0.0
                    if volume == 0 or amount > cash:
                        continue
                    cash -= amount
                    shares, avg_cost = holdings.get(code, [0, 0.0])
                    holdings[code] = [shares + volume,
                                      (shares * avg_cost + amount) / (shares + volume)]
                else:
                    shares, avg_cost = holdings[code]
                    volume = min(shares, rng.randint(1, max(1, shares // 100)) * 100)
                    amount = round(price * volume, 2)
                    cash += amount
                    left = shares - volume
                    if left:
                        holdings[code] = [left, avg_cost]
                    else:
                        del holdings[code]

                trades.append((cid, code, d, random_time(rng), side, price, volume, amount))

    # ---------- 统一重放流水，生成月末快照 ----------
    pos_rows, asset_rows = [], []
    ff_by_acc = {}
    for acc, d, direction, amt in fund_flows:
        ff_by_acc.setdefault(acc, []).append((d, direction, amt))
    tr_by_acc = {}
    for t in trades:
        tr_by_acc.setdefault(t[0], []).append(t)

    for cid in range(1, args.customers + 1):
        cash = 0.0
        holdings = {}
        events = [(d, "ff", direction, amt) for d, direction, amt in ff_by_acc.get(cid, [])]
        events += [(t[2], "tr", t) for t in tr_by_acc.get(cid, [])]
        events.sort(key=lambda e: e[0])
        month_state = {}
        for month in months:
            month_state[month] = None
        current_month = None
        for d, kind, *rest in events:
            m = d[:7]
            if current_month and m != current_month:
                month_state[current_month] = (cash, {k: v[:] for k, v in holdings.items()})
            current_month = m
            if kind == "ff":
                direction, amt = rest
                cash += amt if direction == "in" else -amt
            else:
                t = rest[0]
                _, code, _, _, side, price, volume, amount = t
                if side == "buy":
                    cash -= amount
                    shares, avg_cost = holdings.get(code, [0, 0.0])
                    holdings[code] = [shares + volume, (shares * avg_cost + amount) / (shares + volume)]
                else:
                    cash += amount
                    shares, avg_cost = holdings[code]
                    left = shares - volume
                    if left:
                        holdings[code] = [left, avg_cost]
                    else:
                        del holdings[code]
        if current_month:
            month_state[current_month] = (cash, holdings)

        for month in months:
            state = month_state[month]
            if state is None:
                continue
            cash_m, hold_m = state
            mv_total = 0.0
            for code, (shares, avg_cost) in hold_m.items():
                close = month_last_close.get((code, month))
                if close is None or shares <= 0:
                    continue
                mv = round(shares * close, 2)
                mv_total += mv
                pos_rows.append((cid, code, month, shares, round(avg_cost, 4), mv))
            asset_rows.append((cid, month, round(cash_m, 2), round(mv_total, 2),
                               round(cash_m + mv_total, 2)))

    # ---------- 输出 ----------
    def save(name, rows, cols):
        pd.DataFrame(rows, columns=cols).to_csv(OUT_DIR / f"{name}.csv", index=False, encoding="utf-8-sig")
        print(f"{name}.csv：{len(rows)} 行")

    save("customer", customers, ["customer_id", "name", "gender", "birth_year", "branch_id", "open_date", "risk_level"])
    save("account", accounts, ["account_id", "customer_id", "account_type", "open_date", "status"])
    save("fund_flow", fund_flows, ["account_id", "trans_date", "direction", "amount"])
    save("trade", trades, ["account_id", "stock_code", "trade_date", "trade_time", "side", "price", "volume", "amount"])
    save("position_snapshot", pos_rows, ["account_id", "stock_code", "month", "shares", "avg_cost", "market_value"])
    save("asset_snapshot", asset_rows, ["account_id", "month", "cash", "market_value", "total_asset"])


if __name__ == "__main__":
    main()
