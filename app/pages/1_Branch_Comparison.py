# -*- coding: utf-8 -*-
"""Branch Comparison: Q1 asset/customer rankings + Q4 monthly net bank-securities transfers."""
import plotly.express as px
import streamlit as st

from db import query

st.set_page_config(page_title="Branch Comparison", layout="wide")
st.title("🏢 Branch Performance Comparison")

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
st.subheader("Customers and Assets by Branch (Q1, Latest Month)")
fig = px.bar(df, x="branch_name", y="asset_wan", text="customer_cnt",
             labels={"branch_name": "Branch", "asset_wan": "Total Assets (CNY 10K)", "customer_cnt": "Customers"})
st.plotly_chart(fig, use_container_width=True)
st.dataframe(df, use_container_width=True, hide_index=True)

st.subheader("Monthly Net Bank-Securities Transfers (Q4, CNY 10K)")
flow = query("""
SELECT b.branch_name, to_char(f.trans_date, 'YYYY-MM') AS month,
       ROUND(SUM(CASE WHEN f.direction='in' THEN f.amount ELSE -f.amount END)/1e4, 1) AS net_inflow_wan
FROM fund_flow f
JOIN account a ON a.account_id=f.account_id
JOIN customer c ON c.customer_id=a.customer_id
JOIN branch b ON b.branch_id=c.branch_id
GROUP BY b.branch_id, b.branch_name, to_char(f.trans_date, 'YYYY-MM')
""")
month = st.selectbox("Select Month", sorted(flow.month.unique(), reverse=True))
sub = flow[flow.month == month].sort_values("net_inflow_wan", ascending=False)
fig2 = px.bar(sub, x="branch_name", y="net_inflow_wan",
              labels={"branch_name": "Branch", "net_inflow_wan": "Net Inflow (CNY 10K)"})
st.plotly_chart(fig2, use_container_width=True)
st.dataframe(sub, use_container_width=True, hide_index=True)
