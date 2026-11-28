# -*- coding: utf-8 -*-
"""
W3 data generation script: Generate CSV files for seven business tables
(branch/customer/account/fund_flow/trade/two month-end snapshots).

Realism rules (material for the report's "Data Generation Methodology" section):
  1. Use only actual trading dates from quotes_all.csv for trade dates;
  2. Keep execution prices within the actual [low, high] range for the day, rounded to two decimal places;
  3. Use volumes in multiples of 100, with amount = price × volume; commissions are ignored
     (document this convention in the report);
  4. Fund accounts before trading: maintain cash and holdings ledgers for each account;
     buys cannot exceed available cash, and sells cannot exceed holdings;
  5. Five customer personas: dca (dollar-cost averaging) / active / trend / dormant / whale;
  6. Aggregate month-end snapshots from transactions and actual closing prices rather than
     inventing them independently.

Usage:
    python scripts/generate_data.py --customers 100 --months 1     # v1 small sample (M3)
    python scripts/generate_data.py --customers 5000 --months 12   # full dataset
Output: data/generated/*.csv. A fixed random seed ensures identical results when any team member reruns the script.
"""
import argparse
import random
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
OUT_DIR = BASE_DIR / "data" / "generated"

BRANCHES = [
    (1, "Shenzhen Futian Branch", "Shenzhen, China"), (2, "Shenzhen Nanshan Branch", "Shenzhen, China"),
    (3, "Guangzhou Tianhe Branch", "Guangzhou, China"), (4, "Shanghai Pudong Branch", "Shanghai, China"),
    (5, "Shanghai Jing'an Branch", "Shanghai, China"), (6, "Beijing Chaoyang Branch", "Beijing, China"),
    (7, "Beijing Haidian Branch", "Beijing, China"), (8, "Chengdu High-Tech Branch", "Chengdu, China"),
    (9, "Hangzhou West Lake Branch", "Hangzhou, China"), (10, "Hong Kong Central Branch", "Hong Kong, China"),
]

# Persona weights and parameters (editable by the team; include this table in the report)
PERSONA_WEIGHTS = {"dca": 0.20, "active": 0.15, "trend": 0.35, "dormant": 0.25, "whale": 0.05}
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
]
FIRST_NAMES = [
    "Alex", "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia", "Mason",
    "Isabella", "James", "Mia", "Benjamin", "Charlotte", "Lucas", "Amelia", "Henry",
    "Harper", "Daniel", "Evelyn", "Michael", "Abigail", "William", "Emily", "Alexander",
    "Elizabeth", "David", "Sofia", "Joseph", "Ella", "Grace", "Samuel", "Chloe", "Owen", "Nora",
]

RISK_LEVELS = ["C1", "C2", "C3", "C4", "C5"]


def random_name(rng: random.Random) -> str:
    last_name = rng.choice(LAST_NAMES)
    given_names = [rng.choice(FIRST_NAMES) for _ in range(rng.randint(1, 2))]
    return " ".join(given_names + [last_name])


def random_time(rng: random.Random) -> str:
    """A-share continuous auction sessions: 09:30-11:30 / 13:00-15:00."""
    if rng.random() < 0.55:
        minute = rng.randint(9 * 60 + 30, 11 * 60 + 30)
    else:
        minute = rng.randint(13 * 60, 15 * 60)
    return f"{minute // 60:02d}:{minute % 60:02d}:{rng.randint(0, 59):02d}"


def lot(amount_cash: float, price: float, rng: random.Random, max_lots: int = 50) -> int:
    """Convert a cash budget to a round-lot share volume; return 0 if less than one lot is affordable."""
    affordable = int(amount_cash / price / 100)
    if affordable <= 0:
        return 0
    return rng.randint(1, min(affordable, max_lots)) * 100


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic data generator for a retail brokerage")
    parser.add_argument("--customers", type=int, default=100)
    parser.add_argument("--months", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="", help="Output directory (default: data/generated; use data/sample for a demo package)")
    args = parser.parse_args()
    out_dir = Path(args.out) if args.out else OUT_DIR
    rng = random.Random(args.seed)

    # ---------- Actual market data and trading calendar ----------
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
    # Month-end closing price for each stock in each month (used for snapshot valuation)
    month_last_close = {}
    for (code, month), grp in win.groupby(["stock_code", win["trade_date"].str[:7]]):
        month_last_close[(code, month)] = float(grp.sort_values("trade_date")["close"].iloc[-1])
    print(f"Trading window: {trading_days[0]} to {trading_days[-1]}, {len(trading_days)} trading days, {len(months)} months")

    # ---------- Static tables ----------
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(BRANCHES, columns=["branch_id", "branch_name", "city"]).to_csv(
        out_dir / "branch.csv", index=False, encoding="utf-8-sig")

    personas = list(PERSONA_WEIGHTS)
    weights = list(PERSONA_WEIGHTS.values())
    customers, accounts, fund_flows, trades = [], [], [], []
    first_day = trading_days[0]

    for cid in range(1, args.customers + 1):
        persona = rng.choices(personas, weights)[0]
        branch_id = rng.randint(1, len(BRANCHES))
        # Dormant customers open accounts near the window (and trade only for the first 2 months);
        # others open accounts 1-3 years earlier
        if persona == "dormant":
            open_date = str((pd.Timestamp(first_day) - pd.Timedelta(days=rng.randint(0, 45))).date())
        else:
            open_date = str((pd.Timestamp(first_day) - pd.Timedelta(days=rng.randint(365, 365 * 3))).date())
        customers.append((cid, random_name(rng), rng.choice("MF"), rng.randint(1955, 2005),
                          branch_id, open_date, rng.choices(RISK_LEVELS, [1, 2, 4, 3, 1])[0]))
        accounts.append((cid, cid, "cash", open_date, "active"))  # One account per customer, with matching IDs

        # Initial funding: CNY 50k-500k for regular customers and CNY 3m-10m for whales;
        # dormant high-net-worth customers also fund their accounts (material for Q9)
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

        # Organize trading days by month
        days_by_month = {}
        for d in trade_days_used:
            days_by_month.setdefault(d[:7], []).append(d)

        dca_stock = rng.choice(stock_codes)
        dca_amount = rng.uniform(2000, 10000)
        dca_day = rng.randint(1, 28)

        for month, days in sorted(days_by_month.items()):
            if persona == "active":
                # Highly active customers may place 1-2 trades per day (only about 22 trading days per month)
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
                # DCA: transfer funds on a fixed day each month, then buy the same stock
                if persona == "dca":
                    fund_flows.append((cid, d, "in", round(dca_amount, 2)))
                    cash += dca_amount
                    code = dca_stock
                    side = "buy"
                else:
                    code = rng.choice(stock_codes)
                    # Customers without holdings can only buy; trend/active customers with holdings
                    # have a 30% chance of selling, while whales almost always buy
                    can_sell = bool(holdings) and persona in ("active", "trend")
                    side = "sell" if can_sell and rng.random() < 0.3 else "buy"
                    if side == "sell":
                        code = rng.choice(list(holdings))
                    elif persona == "trend":
                        # Trend customers: prefer stocks rising that day (close>open);
                        # use dictionary lookups to avoid full-table scans
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
                        # Insufficient cash for one lot: active/trend/whale customers have a 60% chance
                        # of making an additional bank-to-brokerage transfer before buying (realistic top-up behavior)
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

    # ---------- Replay all transactions uniformly to generate month-end snapshots ----------
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

    # ---------- Output ----------
    def save(name, rows, cols):
        pd.DataFrame(rows, columns=cols).to_csv(out_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
        print(f"{name}.csv: {len(rows)} rows")

    save("customer", customers, ["customer_id", "name", "gender", "birth_year", "branch_id", "open_date", "risk_level"])
    save("account", accounts, ["account_id", "customer_id", "account_type", "open_date", "status"])
    save("fund_flow", fund_flows, ["account_id", "trans_date", "direction", "amount"])
    save("trade", trades, ["account_id", "stock_code", "trade_date", "trade_time", "side", "price", "volume", "amount"])
    save("position_snapshot", pos_rows, ["account_id", "stock_code", "month", "shares", "avg_cost", "market_value"])
    save("asset_snapshot", asset_rows, ["account_id", "month", "cash", "market_value", "total_asset"])


if __name__ == "__main__":
    main()
