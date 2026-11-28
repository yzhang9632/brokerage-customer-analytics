# -*- coding: utf-8 -*-
"""Stock Explorer: Q3 monthly top 20 by turnover + industry distribution + real market quotes."""
import plotly.express as px
import streamlit as st

from db import query

st.set_page_config(page_title="Stock Explorer", layout="wide")
st.title("🔥 Stock Trends & Quotes")

months = query("SELECT DISTINCT month FROM trade ORDER BY month DESC").month.tolist()
month = st.selectbox("Reporting Month", months)

top = query("""
SELECT s.stock_code, s.stock_name, s.industry, COUNT(t.trade_id) AS trade_cnt,
       ROUND(SUM(t.amount)/1e4, 1) AS turnover_wan
FROM trade t JOIN stock s ON s.stock_code=t.stock_code
WHERE t.month=%s GROUP BY t.stock_code, s.stock_code, s.stock_name, s.industry
ORDER BY turnover_wan DESC LIMIT 20
""", (month,))
st.subheader(f"{month} Top 20 Stocks by Customer Turnover (Q3)")
st.plotly_chart(px.bar(top, x="stock_name", y="turnover_wan",
                       labels={"stock_name": "Stock", "turnover_wan": "Turnover (CNY 10K)"}),
                use_container_width=True)
st.dataframe(top, use_container_width=True, hide_index=True)

st.subheader("Turnover by Industry")
ind = query("""
SELECT s.industry, ROUND(SUM(t.amount)/1e8, 2) AS turnover_yi
FROM trade t JOIN stock s ON s.stock_code=t.stock_code
WHERE t.month=%s GROUP BY s.industry ORDER BY turnover_yi DESC LIMIT 15
""", (month,))
st.plotly_chart(px.pie(ind, names="industry", values="turnover_yi"), use_container_width=True)

st.subheader("Real Stock Quotes (daily_quote)")
stocks = query("SELECT stock_code, stock_name FROM stock ORDER BY stock_code")
choice = st.selectbox("Select Stock", stocks.stock_code + " " + stocks.stock_name)
code = choice.split()[0]
pxdf = query("SELECT trade_date, close FROM daily_quote WHERE stock_code=%s ORDER BY trade_date", (code,))
st.plotly_chart(px.line(pxdf, x="trade_date", y="close",
                        labels={"trade_date": "Date", "close": "Closing Price (CNY)"}, title=choice),
                use_container_width=True)
