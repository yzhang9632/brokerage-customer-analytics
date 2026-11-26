# -*- coding: utf-8 -*-
"""营业部对比：Q1 资产/客户数排名 + Q4 月度银证转账净流入。"""
import plotly.express as px
import streamlit as st

from db import query

st.set_page_config(page_title="营业部对比", layout="wide")
st.title("🏢 营业部经营对比")

df = query("""
SELECT b.branch_name, COUNT(c.customer_id) AS customer_cnt,
       ROUND(SUM(s.total_asset)/1e4, 1) AS asset_wan,
       ROUND(AVG(s.total_asset)/1e4, 2) AS avg_asset_wan
FROM branch b
JOIN customer c ON c.branch_id=b.branch_id
JOIN account a ON a.customer_id=c.customer_id
JOIN asset_snapshot s ON s.account_id=a.account_id
WHERE s.month=(SELECT MAX(month) FROM asset_snapshot)
GROUP BY b.branch_id, b.branch_name ORDER BY asset_wan DESC
""")
st.subheader("各营业部客户数与资产（Q1，最新月）")
fig = px.bar(df, x="branch_name", y="asset_wan", text="customer_cnt",
             labels={"branch_name": "营业部", "asset_wan": "总资产（万元）", "customer_cnt": "客户数"})
st.plotly_chart(fig, use_container_width=True)
st.dataframe(df, use_container_width=True, hide_index=True)

st.subheader("月度银证转账净流入（Q4，单位：万元）")
flow = query("""
SELECT b.branch_name, to_char(f.trans_date, 'YYYY-MM') AS month,
       ROUND(SUM(CASE WHEN f.direction='in' THEN f.amount ELSE -f.amount END)/1e4, 1) AS net_inflow_wan
FROM fund_flow f
JOIN account a ON a.account_id=f.account_id
JOIN customer c ON c.customer_id=a.customer_id
JOIN branch b ON b.branch_id=c.branch_id
GROUP BY b.branch_id, b.branch_name, to_char(f.trans_date, 'YYYY-MM')
""")
month = st.selectbox("选择月份", sorted(flow.month.unique(), reverse=True))
sub = flow[flow.month == month].sort_values("net_inflow_wan", ascending=False)
fig2 = px.bar(sub, x="branch_name", y="net_inflow_wan",
              labels={"branch_name": "营业部", "net_inflow_wan": "净流入（万元）"})
st.plotly_chart(fig2, use_container_width=True)
st.dataframe(sub, use_container_width=True, hide_index=True)
