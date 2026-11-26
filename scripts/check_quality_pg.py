# -*- coding: utf-8 -*-
"""PostgreSQL 正式版数据质量校验。运行前设置 PGPASSWORD，连接参数同 import_db_pg.py。"""
import os
from collections import defaultdict
from pathlib import Path

import psycopg

BASE_DIR = Path(__file__).resolve().parents[1]
_env = BASE_DIR / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if _line.strip() and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
REPORT = BASE_DIR / "data" / "quality_report_pg.txt"

CHECKS_SQL = {
    "1. 非交易日成交": """
        SELECT COUNT(*) FROM trade t
        LEFT JOIN daily_quote q ON q.stock_code = t.stock_code AND q.trade_date = t.trade_date
        WHERE q.stock_code IS NULL""",
    "2. 成交价越界": """
        SELECT COUNT(*) FROM trade t
        JOIN daily_quote q ON q.stock_code = t.stock_code AND q.trade_date = t.trade_date
        WHERE t.price < q.low OR t.price > q.high""",
    "3. 非整手交易": "SELECT COUNT(*) FROM trade WHERE volume % 100 != 0",
    "4. 金额不一致": "SELECT COUNT(*) FROM trade WHERE ABS(amount - price * volume) > 0.01",
    "5a. 孤儿外键：trade.account_id": """
        SELECT COUNT(*) FROM trade t LEFT JOIN account a ON a.account_id = t.account_id
        WHERE a.account_id IS NULL""",
    "5b. 孤儿外键：customer.branch_id": """
        SELECT COUNT(*) FROM customer c LEFT JOIN branch b ON b.branch_id = c.branch_id
        WHERE b.branch_id IS NULL""",
    "5c. 孤儿外键：asset_snapshot.account_id": """
        SELECT COUNT(*) FROM asset_snapshot s LEFT JOIN account a ON a.account_id = s.account_id
        WHERE a.account_id IS NULL""",
}


def ledger_check(cur):
    events = defaultdict(list)
    cur.execute("SELECT flow_id, account_id, trans_date, direction, amount FROM fund_flow")
    for fid, acc, d, direction, amt in cur.fetchall():
        events[acc].append((d, 0, fid, "ff", direction, amt))
    cur.execute("SELECT trade_id, account_id, trade_date, side, stock_code, volume, amount FROM trade")
    for tid, acc, d, side, code, vol, amt in cur.fetchall():
        events[acc].append((d, 1, tid, side, code, vol, amt))

    negative, oversell = set(), 0
    for acc, evs in events.items():
        cash, holdings = 0.0, defaultdict(int)
        # 同日入金先于交易（生成语义：当日入金当日可用）；
        # 交易之间必须按 trade_id 保持生成顺序，否则"先卖后买"会被重排成"先买后卖"造成假负余额
        for e in sorted(evs, key=lambda e: (e[0], e[1], e[2])):
            if e[3] == "ff":
                cash += float(e[5]) if e[4] == "in" else -float(e[5])
            elif e[3] == "buy":
                cash -= float(e[6])
                holdings[e[4]] += e[5]
            else:
                cash += float(e[6])
                holdings[e[4]] -= e[5]
                if holdings[e[4]] < 0:
                    oversell += 1
            if cash < -0.01:
                negative.add(acc)
                break
    return len(negative), oversell


def main():
    with psycopg.connect(
        host=os.getenv("PGHOST", "127.0.0.1"), port=int(os.getenv("PGPORT", "5432")),
        user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD", ""),
        dbname=os.getenv("PGDATABASE", "brokerage"),
    ) as conn:
        with conn.cursor() as cur:
            lines = ["PostgreSQL 数据质量报告", "=" * 50]
            all_pass = True
            for name, sql in CHECKS_SQL.items():
                cur.execute(sql)
                n = cur.fetchone()[0]
                all_pass &= n == 0
                lines.append(f"[{'PASS' if n == 0 else 'FAIL'}] {name}：{n} 条异常")
            neg, over = ledger_check(cur)
            lines.append(f"[{'PASS' if neg == 0 else 'FAIL'}] 6. 现金负余额账户：{neg} 个")
            lines.append(f"[{'PASS' if over == 0 else 'FAIL'}] 7. 卖出超持仓：{over} 笔")
            all_pass &= neg == 0 and over == 0
            lines += ["=" * 50, "总体结论：" + ("全部通过 ✅" if all_pass else "存在异常 ❌")]
            text = "\n".join(lines)
            print(text)
            REPORT.write_text(text, encoding="utf-8")
            print(f"\n报告已存：{REPORT}")


if __name__ == "__main__":
    main()
