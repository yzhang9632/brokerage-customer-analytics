# -*- coding: utf-8 -*-
"""
Account opening and order placement transactions (core rubric engineering practices demonstration).

Design highlights:
- Cash and holdings are not stored in separate tables. A ledger model calculates them in real time
  from fund_flow and trade records.
- Before placing an order, SELECT ... FOR UPDATE locks the account row to prevent concurrent overspending.
- Insufficient cash or holdings triggers an explicit ROLLBACK and returns the reason; COMMIT occurs only on success.
- The execution price is the stock's latest actual closing price, and the trade date is the latest quote date.
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
        return {"ok": False, "msg": "Side must be buy/sell"}
    if volume <= 0 or volume % 100 != 0:
        return {"ok": False, "msg": "Volume must be a positive multiple of 100 (A-share board-lot rule)"}

    with psycopg.connect(**get_dsn()) as conn, conn.cursor() as cur:
        try:
            cur.execute("SELECT account_id FROM account WHERE account_id=%s FOR UPDATE", (account_id,))
            if cur.fetchone() is None:
                conn.rollback()
                return {"ok": False, "msg": f"Account {account_id} does not exist; transaction rolled back"}

            cur.execute("""SELECT close, trade_date FROM daily_quote
                           WHERE stock_code=%s ORDER BY trade_date DESC LIMIT 1""", (stock_code,))
            price, trade_date = cur.fetchone()
            amount = round(float(price) * volume, 2)

            if side == "buy":
                cur.execute(CASH_SQL, (account_id, account_id))
                cash = float(cur.fetchone()[0])
                if amount > cash:
                    conn.rollback()  # Failure path: roll back on insufficient funds; always demonstrate this path.
                    return {"ok": False,
                            "msg": f"Insufficient funds; transaction rolled back: required ¥{amount:,.2f}, available ¥{cash:,.2f}"}
            else:
                cur.execute(HELD_SQL, (account_id, stock_code))
                held = int(cur.fetchone()[0])
                if volume > held:
                    conn.rollback()
                    return {"ok": False,
                            "msg": f"Insufficient holdings; transaction rolled back: attempted to sell {volume} shares, currently hold {held} shares"}

            cur.execute("""INSERT INTO trade
                           (account_id, stock_code, trade_date, trade_time, side, price, volume, amount, month)
                           VALUES (%s, %s, %s, CURRENT_TIME, %s, %s, %s, %s, to_char(%s, 'YYYY-MM'))
                           RETURNING trade_id""",
                        (account_id, stock_code, trade_date, side, price, volume, amount, trade_date))
            trade_id = cur.fetchone()[0]
            conn.commit()
            return {"ok": True, "trade_id": trade_id,
                    "msg": f"{'Buy' if side == 'buy' else 'Sell'} order executed (order ID {trade_id}): {stock_code} × {volume} shares, "
                           f"execution price ¥{float(price):.2f}, amount ¥{amount:,.2f} ({trade_date})"}
        except Exception as e:
            conn.rollback()
            return {"ok": False, "msg": f"Error; transaction rolled back: {e}"}


def open_account(name: str, gender: str, birth_year: int, branch_id: int,
                 risk_level: str, init_cash: float) -> dict:
    """Account opening transaction: atomically write customer, account, and the initial deposit; roll back everything on any failure."""
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
                    "msg": f"Account opened: customer ID/cash account {new_id}, "
                           f"initial deposit ¥{init_cash:,.2f}, opening date {open_date}"}
        except Exception as e:
            conn.rollback()
            return {"ok": False, "msg": f"Account opening failed; transaction rolled back (no residual customer/account records): {e}"}
