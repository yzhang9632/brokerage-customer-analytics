# -*- coding: utf-8 -*-
"""Customer Analytics: Q5 activity rate, Q9 dormant-customer reactivation list, Q10 RFM, and Q11 status migration matrix."""
import plotly.express as px
import streamlit as st

from db import query

st.set_page_config(page_title="Customer Analytics", layout="wide")
st.title("👥 Customer Analytics")

st.subheader("Monthly Customer Activity Rate (Q5)")
act = query("""
WITH active AS (SELECT month, COUNT(DISTINCT account_id) AS cnt FROM trade GROUP BY month)
SELECT a.month, a.cnt AS active_cnt,
       (SELECT COUNT(*) FROM customer c
         WHERE c.open_date <= ((a.month||'-01')::date + interval '1 month - 1 day')) AS total,
       ROUND(100.0*a.cnt/(SELECT COUNT(*) FROM customer c
         WHERE c.open_date <= ((a.month||'-01')::date + interval '1 month - 1 day')), 2) AS rate_pct
FROM active a ORDER BY a.month
""")
st.plotly_chart(px.line(act, x="month", y="rate_pct", markers=True,
                        labels={"month": "Month", "rate_pct": "Activity Rate (%)"}),
                use_container_width=True)

left, right = st.columns(2)
with left:
    st.subheader("Dormant High-Net-Worth Customers for Reactivation (Q9)")
    st.caption("Criteria: No trades for 90 days and latest total assets > CNY 100K")
    dormant = query("""
WITH ref AS (SELECT MAX(trade_date) AS d FROM daily_quote),
lt AS (SELECT account_id, MAX(trade_date) AS last_d FROM trade GROUP BY account_id)
SELECT c.customer_id, c.name, b.branch_name,
       COALESCE(lt.last_d, c.open_date) AS last_active, ROUND(s.total_asset, 0) AS total_asset
FROM customer c
JOIN branch b ON b.branch_id=c.branch_id
JOIN account a ON a.customer_id=c.customer_id
JOIN asset_snapshot s ON s.account_id=a.account_id
      AND s.month=(SELECT MAX(month) FROM asset_snapshot)
LEFT JOIN lt ON lt.account_id=a.account_id
WHERE (SELECT d FROM ref) - COALESCE(lt.last_d, c.open_date) > 90 AND s.total_asset > 100000
ORDER BY s.total_asset DESC
""")
    st.dataframe(dormant, use_container_width=True, hide_index=True)

with right:
    st.subheader("RFM Customer Segmentation (Q10)")
    rfm = query("""
WITH ref AS (SELECT MAX(trade_date) AS d FROM daily_quote),
rfm AS (SELECT account_id, (SELECT d FROM ref)-MAX(trade_date) AS r,
        SUM(CASE WHEN trade_date >= (SELECT d FROM ref)-90 THEN 1 ELSE 0 END) AS f,
        SUM(CASE WHEN trade_date >= (SELECT d FROM ref)-90 THEN amount ELSE 0 END) AS m
        FROM trade GROUP BY account_id),
scored AS (SELECT *, NTILE(3) OVER (ORDER BY r DESC) AS rs, NTILE(3) OVER (ORDER BY m) AS ms FROM rfm),
seg AS (SELECT CASE WHEN rs=3 AND ms=3 THEN 'High-Value Active'
                    WHEN rs=1 AND ms=3 THEN 'High-Value Churn Risk'
                    WHEN rs=1 THEN 'Dormant' ELSE 'Standard' END AS segment FROM scored)
SELECT segment, COUNT(*) AS cnt FROM seg GROUP BY segment ORDER BY cnt DESC
""")
    st.plotly_chart(px.pie(rfm, names="segment", values="cnt"), use_container_width=True)

st.subheader("Monthly Customer Status Migration Matrix (Q11)")
st.caption("new = opened during the month; active = traded during the month; silent = traded within the last 90 days but not during the month; churned = churned")
mig = query("""
WITH months AS (SELECT DISTINCT month FROM asset_snapshot),
states AS (
  SELECT a.account_id, m.month,
         CASE WHEN to_char(c.open_date,'YYYY-MM')=m.month THEN 'new'
              WHEN EXISTS (SELECT 1 FROM trade t WHERE t.account_id=a.account_id AND t.month=m.month) THEN 'active'
              WHEN (SELECT MAX(t2.trade_date) FROM trade t2
                     WHERE t2.account_id=a.account_id AND t2.trade_date < (m.month||'-01')::date)
                   >= (m.month||'-01')::date-90 THEN 'silent' ELSE 'churned' END AS status
  FROM account a JOIN customer c ON c.customer_id=a.customer_id CROSS JOIN months m
  WHERE m.month >= to_char(c.open_date,'YYYY-MM')),
seq AS (SELECT *, LAG(status) OVER (PARTITION BY account_id ORDER BY month) AS prev FROM states)
SELECT prev AS from_status, status AS to_status, COUNT(*) AS cnt
FROM seq WHERE prev IS NOT NULL GROUP BY prev, status
""")
pivot = mig.pivot(index="from_status", columns="to_status", values="cnt").fillna(0).astype(int)
st.dataframe(pivot, use_container_width=True)
