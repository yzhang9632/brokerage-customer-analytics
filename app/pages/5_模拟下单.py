# -*- coding: utf-8 -*-
"""模拟下单 + 开户事务演示（成功路径与失败回滚路径都可现场演示）。"""
import streamlit as st

from db import query_fresh
from transactions import open_account, place_order

st.set_page_config(page_title="模拟下单", layout="wide")
st.title("💸 模拟下单（事务演示）")
st.caption("账本模型：现金/持仓由 fund_flow 与 trade 流水实时计算；"
           "SELECT ... FOR UPDATE 锁账户；余额或持仓不足时显式 ROLLBACK")

account_id = st.number_input("资金账号", min_value=1, value=42, step=1)
cash_df = query_fresh("""
SELECT COALESCE((SELECT SUM(CASE WHEN direction='in' THEN amount ELSE -amount END)
                 FROM fund_flow WHERE account_id=%s),0)
     - COALESCE((SELECT SUM(CASE WHEN side='buy' THEN amount ELSE -amount END)
                 FROM trade WHERE account_id=%s),0) AS cash
""", (account_id, account_id))
st.metric("当前可用现金（实时计算）", f"¥{float(cash_df.iloc[0].cash):,.2f}")

stocks = query_fresh("SELECT stock_code, stock_name FROM stock ORDER BY stock_code")
col1, col2, col3 = st.columns(3)
with col1:
    choice = st.selectbox("股票", stocks.stock_code + " " + stocks.stock_name)
with col2:
    side = st.radio("方向", ["buy", "sell"], format_func=lambda x: "买入" if x == "buy" else "卖出")
with col3:
    volume = st.number_input("数量（100 的整数倍）", min_value=100, value=100, step=100)

code = choice.split()[0]
price = query_fresh("SELECT close FROM daily_quote WHERE stock_code=%s ORDER BY trade_date DESC LIMIT 1",
                    (code,))
st.info(f"最新真实收盘价：¥{float(price.iloc[0].close):.2f} ｜ 预计金额："
        f"¥{float(price.iloc[0].close)*volume:,.2f} ｜ 想演示回滚？把数量调大到超过可用现金即可")

if st.button("提交订单", type="primary"):
    result = place_order(int(account_id), code, side, int(volume))
    if result["ok"]:
        st.success(result["msg"])
    else:
        st.error(result["msg"])

st.divider()
st.subheader("开户事务（customer + account + 初始入金原子写入）")
with st.form("open_account"):
    name = st.text_input("姓名", "测试客户")
    c1, c2, c3 = st.columns(3)
    with c1:
        gender = st.selectbox("性别", ["M", "F"], format_func=lambda x: "男" if x == "M" else "女")
        birth_year = st.number_input("出生年份", 1930, 2010, 1995)
    with c2:
        branches = query_fresh("SELECT branch_id, branch_name FROM branch ORDER BY branch_id")
        branch = st.selectbox("营业部", branches.branch_id.astype(str) + " " + branches.branch_name)
        risk = st.selectbox("风险等级", ["C1", "C2", "C3", "C4", "C5"], index=2)
    with c3:
        init_cash = st.number_input("初始入金（元）", min_value=0.0, value=100000.0, step=10000.0)
    if st.form_submit_button("提交开户"):
        result = open_account(name, gender, int(birth_year), int(branch.split()[0]), risk, float(init_cash))
        (st.success if result["ok"] else st.error)(result["msg"])
