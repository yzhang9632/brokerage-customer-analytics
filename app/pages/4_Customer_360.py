# -*- coding: utf-8 -*-
"""Customer 360: Q2 customer profile + unrealized position P/L (Q12) + recent trade details."""
import streamlit as st

from db import query

st.set_page_config(page_title="Customer 360", layout="wide")
st.title("🔍 Customer 360")

cid = st.number_input("Customer ID (1–10000)", min_value=1, max_value=10000, value=42, step=1)

info = query("""
SELECT c.customer_id, c.name, b.branch_name, c.risk_level, c.open_date,
       s.cash, s.market_value, s.total_asset
FROM customer c
JOIN branch b ON b.branch_id=c.branch_id
JOIN account a ON a.customer_id=c.customer_id
JOIN asset_snapshot s ON s.account_id=a.account_id
      AND s.month=(SELECT MAX(month) FROM asset_snapshot)
WHERE c.customer_id=%s
""", (cid,))
if info.empty:
    st.warning("This customer does not exist or has no asset snapshot")
    st.stop()

r = info.iloc[0]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Customer", f"{r['name']} ({r.risk_level})")
c2.metric("Total Assets", f"¥{r.total_asset:,.0f}")
c3.metric("Cash", f"¥{r.cash:,.0f}")
c4.metric("Market Value of Holdings", f"¥{r.market_value:,.0f}")
st.caption(f"Branch: {r.branch_name} | Date Opened: {r.open_date}")

st.subheader("Current Positions & Unrealized P/L (Q12: latest actual closing price vs. weighted average cost)")
pos = query("""
WITH lc AS (SELECT stock_code, close FROM daily_quote
            WHERE trade_date=(SELECT MAX(trade_date) FROM daily_quote))
SELECT s.stock_name, p.shares, ROUND(p.avg_cost, 2) AS avg_cost, lc.close AS latest_close,
       ROUND((lc.close-p.avg_cost)*p.shares, 2) AS pnl,
       ROUND(100.0*(lc.close-p.avg_cost)/p.avg_cost, 2) AS pnl_pct
FROM position_snapshot p
JOIN lc ON lc.stock_code=p.stock_code
JOIN stock s ON s.stock_code=p.stock_code
WHERE p.account_id=%s AND p.month=(SELECT MAX(month) FROM position_snapshot)
ORDER BY pnl DESC
""", (cid,))
st.dataframe(pos, use_container_width=True, hide_index=True)

st.subheader("Last 50 Trades")
tr = query("""
SELECT t.trade_date, t.trade_time, s.stock_name, t.side, t.price, t.volume, t.amount
FROM trade t JOIN stock s ON s.stock_code=t.stock_code
WHERE t.account_id=%s ORDER BY t.trade_date DESC, t.trade_time DESC LIMIT 50
""", (cid,))
st.dataframe(tr, use_container_width=True, hide_index=True)
