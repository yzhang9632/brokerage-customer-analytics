# -*- coding: utf-8 -*-
"""股票热度：Q3 月度成交额 TOP20 + 行业分布 + 真实行情查询。"""
import plotly.express as px
import streamlit as st

from db import query

st.set_page_config(page_title="股票热度", layout="wide")
st.title("🔥 股票热度与行情")

months = query("SELECT DISTINCT month FROM trade ORDER BY month DESC").month.tolist()
month = st.selectbox("统计月份", months)

top = query("""
SELECT s.stock_code, s.stock_name, s.industry, COUNT(t.trade_id) AS trade_cnt,
       ROUND(SUM(t.amount)/1e4, 1) AS turnover_wan
FROM trade t JOIN stock s ON s.stock_code=t.stock_code
WHERE t.month=%s GROUP BY t.stock_code, s.stock_code, s.stock_name, s.industry
ORDER BY turnover_wan DESC LIMIT 20
""", (month,))
st.subheader(f"{month} 客户成交额 TOP 20（Q3）")
st.plotly_chart(px.bar(top, x="stock_name", y="turnover_wan",
                       labels={"stock_name": "股票", "turnover_wan": "成交额（万元）"}),
                use_container_width=True)
st.dataframe(top, use_container_width=True, hide_index=True)

st.subheader("行业成交分布")
ind = query("""
SELECT s.industry, ROUND(SUM(t.amount)/1e8, 2) AS turnover_yi
FROM trade t JOIN stock s ON s.stock_code=t.stock_code
WHERE t.month=%s GROUP BY s.industry ORDER BY turnover_yi DESC LIMIT 15
""", (month,))
st.plotly_chart(px.pie(ind, names="industry", values="turnover_yi"), use_container_width=True)

st.subheader("个股真实行情（daily_quote）")
stocks = query("SELECT stock_code, stock_name FROM stock ORDER BY stock_code")
choice = st.selectbox("选择股票", stocks.stock_code + " " + stocks.stock_name)
code = choice.split()[0]
pxdf = query("SELECT trade_date, close FROM daily_quote WHERE stock_code=%s ORDER BY trade_date", (code,))
st.plotly_chart(px.line(pxdf, x="trade_date", y="close",
                        labels={"trade_date": "日期", "close": "收盘价（元）"}, title=choice),
                use_container_width=True)
