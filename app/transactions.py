# -*- coding: utf-8 -*-
"""
开户与下单事务（rubric engineering practices 核心演示）。

设计要点：
- 现金与持仓不单独存表，采用账本模型：由 fund_flow / trade 流水实时计算；
- 下单先 SELECT ... FOR UPDATE 锁定账户行，防止并发下超额支出；
- 资金/持仓不足 → 显式 ROLLBACK 并返回失败原因；成功才 COMMIT；
- 成交价取该股票最新真实收盘价，交易日取行情最新日期。
"""
import psycopg

from db import get_dsn

CASH_SQL = """
SELECT COALESCE((SELECT SUM(CASE WHEN direction='in' THEN amount ELSE -amount END)
                 FROM fund_flow WHERE account_id=%s), 0)
     - COALESCE((SELECT SUM(CASE WHEN side='buy' THEN amount ELSE -amount END)
                 FROM trade WHERE account_id=%s), 0)
"""

HELD_SQL = """
SELECT COALESCE(SUM(CASE WHEN side='buy' THEN volume ELSE -volume END), 0)
FROM trade WHERE account_id=%s AND stock_code=%s
"""


def current_cash(account_id: int) -> float:
    with psycopg.connect(**get_dsn()) as conn, conn.cursor() as cur:
        cur.execute(CASH_SQL, (account_id, account_id))
        return float(cur.fetchone()[0])


def place_order(account_id: int, stock_code: str, side: str, volume: int) -> dict:
    if side not in ("buy", "sell"):
        return {"ok": False, "msg": "方向必须为 buy/sell"}
    if volume <= 0 or volume % 100 != 0:
        return {"ok": False, "msg": "数量必须为 100 的整数倍（A 股整手规则）"}

    with psycopg.connect(**get_dsn()) as conn, conn.cursor() as cur:
        try:
            cur.execute("SELECT account_id FROM account WHERE account_id=%s FOR UPDATE", (account_id,))
            if cur.fetchone() is None:
                conn.rollback()
                return {"ok": False, "msg": f"账户 {account_id} 不存在，事务已回滚"}

            cur.execute("""SELECT close, trade_date FROM daily_quote
                           WHERE stock_code=%s ORDER BY trade_date DESC LIMIT 1""", (stock_code,))
            price, trade_date = cur.fetchone()
            amount = round(float(price) * volume, 2)

            if side == "buy":
                cur.execute(CASH_SQL, (account_id, account_id))
                cash = float(cur.fetchone()[0])
                if amount > cash:
                    conn.rollback()  # 失败路径：余额不足回滚，演示时必讲
                    return {"ok": False,
                            "msg": f"余额不足，事务已回滚：需 ¥{amount:,.2f}，可用 ¥{cash:,.2f}"}
            else:
                cur.execute(HELD_SQL, (account_id, stock_code))
                held = int(cur.fetchone()[0])
                if volume > held:
                    conn.rollback()
                    return {"ok": False,
                            "msg": f"持仓不足，事务已回滚：拟卖 {volume} 股，当前持有 {held} 股"}

            cur.execute("""INSERT INTO trade
                           (account_id, stock_code, trade_date, trade_time, side, price, volume, amount, month)
                           VALUES (%s, %s, %s, CURRENT_TIME, %s, %s, %s, %s, to_char(%s, 'YYYY-MM'))
                           RETURNING trade_id""",
                        (account_id, stock_code, trade_date, side, price, volume, amount, trade_date))
            trade_id = cur.fetchone()[0]
            conn.commit()
            return {"ok": True, "trade_id": trade_id,
                    "msg": f"{'买入' if side == 'buy' else '卖出'}成功（订单号 {trade_id}）：{stock_code} × {volume} 股，"
                           f"成交价 ¥{float(price):.2f}，金额 ¥{amount:,.2f}（{trade_date}）"}
        except Exception as e:
            conn.rollback()
            return {"ok": False, "msg": f"异常，事务已回滚：{e}"}


def open_account(name: str, gender: str, birth_year: int, branch_id: int,
                 risk_level: str, init_cash: float) -> dict:
    """开户事务：customer + account + 初始入金三张表原子写入，任一步失败全部回滚。"""
    with psycopg.connect(**get_dsn()) as conn, conn.cursor() as cur:
        try:
            cur.execute("SELECT MAX(trade_date) FROM daily_quote")
            open_date = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(MAX(customer_id), 0) + 1 FROM customer")
            new_id = cur.fetchone()[0]

            cur.execute("""INSERT INTO customer
                           (customer_id, name, gender, birth_year, branch_id, open_date, risk_level)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (new_id, name, gender, birth_year, branch_id, open_date, risk_level))
            cur.execute("""INSERT INTO account (account_id, customer_id, account_type, open_date, status)
                           VALUES (%s, %s, 'cash', %s, 'active')""", (new_id, new_id, open_date))
            if init_cash > 0:
                cur.execute("""INSERT INTO fund_flow (account_id, trans_date, direction, amount)
                               VALUES (%s, %s, 'in', %s)""", (new_id, open_date, round(init_cash, 2)))
            conn.commit()
            return {"ok": True, "customer_id": new_id,
                    "msg": f"开户成功：客户号/资金账号 {new_id}，"
                           f"初始入金 ¥{init_cash:,.2f}，开户日期 {open_date}"}
        except Exception as e:
            conn.rollback()
            return {"ok": False, "msg": f"开户失败，事务已回滚（customer/account 均不残留）：{e}"}
