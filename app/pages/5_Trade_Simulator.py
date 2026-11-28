# -*- coding: utf-8 -*-
"""Simulated order placement + account opening transaction demo (both success and failure/rollback paths)."""
import streamlit as st

from db import query_fresh
from transactions import open_account, place_order

st.set_page_config(page_title="Trade Simulator", layout="wide")
st.title("💸 Trade Simulator (Transaction Demo)")
st.caption("Ledger model: cash and holdings are calculated in real time from fund_flow and trade records; "
           "SELECT ... FOR UPDATE locks the account; insufficient cash or holdings triggers an explicit ROLLBACK")

account_id = st.number_input("Cash Account ID", min_value=1, value=42, step=1)
cash_df = query_fresh("""
SELECT COALESCE((SELECT SUM(CASE WHEN direction='in' THEN amount ELSE -amount END)
                 FROM fund_flow WHERE account_id=%s),0)
     - COALESCE((SELECT SUM(CASE WHEN side='buy' THEN amount ELSE -amount END)
                 FROM trade WHERE account_id=%s),0) AS cash
""", (account_id, account_id))
st.metric("Available Cash (Real-Time)", f"¥{float(cash_df.iloc[0].cash):,.2f}")

stocks = query_fresh("SELECT stock_code, stock_name FROM stock ORDER BY stock_code")
col1, col2, col3 = st.columns(3)
with col1:
    choice = st.selectbox("Stock", stocks.stock_code + " " + stocks.stock_name)
with col2:
    side = st.radio("Side", ["buy", "sell"], format_func=lambda x: "Buy" if x == "buy" else "Sell")
with col3:
    volume = st.number_input("Volume (Multiple of 100)", min_value=100, value=100, step=100)

code = choice.split()[0]
price = query_fresh("SELECT close FROM daily_quote WHERE stock_code=%s ORDER BY trade_date DESC LIMIT 1",
                    (code,))
st.info(f"Latest actual closing price: ¥{float(price.iloc[0].close):.2f} | Estimated amount: "
        f"¥{float(price.iloc[0].close)*volume:,.2f} | To demonstrate a rollback, increase the volume until it exceeds the available cash or holdings")

if st.button("Submit Order", type="primary"):
    result = place_order(int(account_id), code, side, int(volume))
    if result["ok"]:
        st.success(result["msg"])
    else:
        st.error(result["msg"])

st.divider()
st.subheader("Account Opening Transaction (Atomic Writes: customer + account + Initial Deposit)")
with st.form("open_account"):
    name = st.text_input("Name", "Test Customer")
    c1, c2, c3 = st.columns(3)
    with c1:
        gender = st.selectbox("Gender", ["M", "F"], format_func=lambda x: "Male" if x == "M" else "Female")
        birth_year = st.number_input("Year of Birth", 1930, 2010, 1995)
    with c2:
        branches = query_fresh("SELECT branch_id, branch_name FROM branch ORDER BY branch_id")
        branch = st.selectbox("Branch", branches.branch_id.astype(str) + " " + branches.branch_name)
        risk = st.selectbox("Risk Level", ["C1", "C2", "C3", "C4", "C5"], index=2)
    with c3:
        init_cash = st.number_input("Initial Deposit (CNY)", min_value=0.0, value=100000.0, step=10000.0)
    if st.form_submit_button("Open Account"):
        result = open_account(name, gender, int(birth_year), int(branch.split()[0]), risk, float(init_cash))
        (st.success if result["ok"] else st.error)(result["msg"])
