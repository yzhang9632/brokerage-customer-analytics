-- ============================================================
-- Q1–Q12 Business Queries + Metric Definition Dictionary · PostgreSQL Final Version
-- Business logic matches the SQLite version; only date/aggregation syntax has been adapted for PostgreSQL
-- ============================================================

-- Q1 [Basic] Customer Count and Total Assets by Branch
-- Definition: Use the latest month in asset_snapshot; total assets = cash + market value of holdings
SELECT b.branch_name,
       COUNT(c.customer_id)            AS customer_cnt,
       ROUND(SUM(s.total_asset), 2)    AS total_asset,
       ROUND(AVG(s.total_asset), 2)    AS avg_asset_per_customer
FROM branch b
JOIN customer c       ON c.branch_id = b.branch_id
JOIN account a        ON a.customer_id = c.customer_id
JOIN asset_snapshot s ON s.account_id = a.account_id
WHERE s.month = (SELECT MAX(month) FROM asset_snapshot)
GROUP BY b.branch_id, b.branch_name
ORDER BY total_asset DESC;

-- Q2 [Basic] Customer 360 View
-- Definition: Basic profile + current-month trade count/amount + latest monthly assets + current holdings list
SELECT c.customer_id, c.name, b.branch_name, c.risk_level, c.open_date,
       (SELECT COUNT(*) FROM trade t JOIN account a2 ON a2.account_id = t.account_id
         WHERE a2.customer_id = c.customer_id
           AND t.month = (SELECT MAX(month) FROM trade))      AS month_trade_cnt,
       (SELECT ROUND(SUM(t.amount), 2) FROM trade t JOIN account a2 ON a2.account_id = t.account_id
         WHERE a2.customer_id = c.customer_id
           AND t.month = (SELECT MAX(month) FROM trade))      AS month_trade_amount,
       s.total_asset, s.cash, s.market_value,
       (SELECT STRING_AGG(st.stock_name || '×' || p.shares::text, ', ')
          FROM position_snapshot p JOIN stock st ON st.stock_code = p.stock_code
         WHERE p.account_id = a.account_id
           AND p.month = (SELECT MAX(month) FROM position_snapshot)) AS holdings
FROM customer c
JOIN branch b         ON b.branch_id = c.branch_id
JOIN account a        ON a.customer_id = c.customer_id
JOIN asset_snapshot s ON s.account_id = a.account_id
                      AND s.month = (SELECT MAX(month) FROM asset_snapshot)
WHERE c.customer_id = 1;

-- Q3 [Basic] Top 20 Stocks by Monthly Turnover
-- Definition: Include both buy and sell turnover; the example uses the latest month
SELECT s.stock_code, s.stock_name, s.industry,
       COUNT(t.trade_id)             AS trade_cnt,
       ROUND(SUM(t.amount), 2)       AS turnover
FROM trade t
JOIN stock s ON s.stock_code = t.stock_code
WHERE t.month = (SELECT MAX(month) FROM trade)
GROUP BY t.stock_code, s.stock_code, s.stock_name, s.industry
ORDER BY turnover DESC
LIMIT 20;

-- Q4 [Basic] Monthly Net Bank-Securities Transfer Inflow by Branch
-- Definition: Net inflow = deposits (in) − withdrawals (out)
SELECT b.branch_name,
       to_char(f.trans_date, 'YYYY-MM') AS month,
       ROUND(SUM(CASE WHEN f.direction = 'in' THEN f.amount ELSE -f.amount END), 2) AS net_inflow
FROM fund_flow f
JOIN account a  ON a.account_id = f.account_id
JOIN customer c ON c.customer_id = a.customer_id
JOIN branch b   ON b.branch_id = c.branch_id
GROUP BY b.branch_id, b.branch_name, to_char(f.trans_date, 'YYYY-MM')
ORDER BY month, net_inflow DESC;

-- Q5 [Advanced] Monthly Customer Activity Rate
-- Definition: Active = at least one trade in the month; denominator = customers who opened accounts by month-end
WITH active AS (
    SELECT month, COUNT(DISTINCT account_id) AS active_cnt
    FROM trade GROUP BY month
)
SELECT a.month,
       a.active_cnt,
       (SELECT COUNT(*) FROM customer c
         WHERE c.open_date <= ((a.month || '-01')::date + interval '1 month - 1 day')) AS total_customers,
       ROUND(100.0 * a.active_cnt /
             (SELECT COUNT(*) FROM customer c
               WHERE c.open_date <= ((a.month || '-01')::date + interval '1 month - 1 day')), 2) AS active_rate_pct
FROM active a
ORDER BY a.month;

-- Q6 [Advanced] Customer Asset Quintiles
-- Definition: NTILE(5) over latest-month total assets; tier 1 = top 20%
WITH latest AS (
    SELECT account_id, total_asset FROM asset_snapshot
    WHERE month = (SELECT MAX(month) FROM asset_snapshot)
),
ranked AS (
    SELECT *, NTILE(5) OVER (ORDER BY total_asset DESC) AS asset_tier FROM latest
)
SELECT r.asset_tier,
       COUNT(*)                       AS customer_cnt,
       ROUND(SUM(r.total_asset), 2)   AS asset_sum,
       ROUND(100.0 * SUM(r.total_asset) / (SELECT SUM(total_asset) FROM latest), 2) AS asset_pct
FROM ranked r
GROUP BY r.asset_tier
ORDER BY r.asset_tier;

-- Q7 [Advanced] Market-Wide Month-over-Month Turnover
-- Definition: MoM = (current month − previous month) / previous month; for YoY with 12 months of data, use LAG(turnover, 12)
WITH m AS (
    SELECT month, SUM(amount) AS turnover FROM trade GROUP BY month
)
SELECT month,
       ROUND(turnover, 2) AS turnover,
       ROUND(LAG(turnover) OVER (ORDER BY month), 2) AS prev_month,
       ROUND(100.0 * (turnover - LAG(turnover) OVER (ORDER BY month))
             / LAG(turnover) OVER (ORDER BY month), 2) AS mom_pct
FROM m
ORDER BY month;

-- Q8 [Advanced] Top 20 Customers by Monthly Turnover Rate
-- Simplified definition: monthly turnover rate = total buy-and-sell trade amount / month-end total assets
SELECT t.account_id, c.name, t.month,
       ROUND(SUM(t.amount), 2)        AS month_turnover,
       s.total_asset,
       ROUND(SUM(t.amount) / s.total_asset, 4) AS turnover_rate
FROM trade t
JOIN asset_snapshot s ON s.account_id = t.account_id AND s.month = t.month
JOIN customer c       ON c.customer_id = t.account_id
GROUP BY t.account_id, c.name, t.month, s.total_asset
ORDER BY turnover_rate DESC
LIMIT 20;

-- Q9 [Advanced] Dormant High-Net-Worth Customer Reactivation List
-- Definition: no trades for more than 90 days before the reference date and latest total assets above 100,000; use account-opening date for customers with no trades
WITH ref AS (SELECT MAX(trade_date) AS d FROM daily_quote),
last_trade AS (
    SELECT account_id, MAX(trade_date) AS last_d FROM trade GROUP BY account_id
)
SELECT c.customer_id, c.name, b.branch_name,
       COALESCE(lt.last_d, c.open_date) AS last_active_date,
       s.total_asset
FROM customer c
JOIN branch b   ON b.branch_id = c.branch_id
JOIN account a  ON a.customer_id = c.customer_id
JOIN asset_snapshot s ON s.account_id = a.account_id
                      AND s.month = (SELECT MAX(month) FROM asset_snapshot)
LEFT JOIN last_trade lt ON lt.account_id = a.account_id
WHERE (SELECT d FROM ref) - COALESCE(lt.last_d, c.open_date) > 90
  AND s.total_asset > 100000
ORDER BY s.total_asset DESC;

-- Q10 [Challenge] Customer RFM Segmentation
-- Definition: R = days since latest trade; F/M = trade count/amount in the last 90 days; each dimension uses NTILE(3)
WITH ref AS (SELECT MAX(trade_date) AS d FROM daily_quote),
rfm AS (
    SELECT account_id,
           (SELECT d FROM ref) - MAX(trade_date) AS R,
           SUM(CASE WHEN trade_date >= (SELECT d FROM ref) - 90 THEN 1 ELSE 0 END) AS F,
           SUM(CASE WHEN trade_date >= (SELECT d FROM ref) - 90 THEN amount ELSE 0 END) AS M
    FROM trade GROUP BY account_id
),
scored AS (
    SELECT *,
           NTILE(3) OVER (ORDER BY R DESC) AS r_score,
           NTILE(3) OVER (ORDER BY F)      AS f_score,
           NTILE(3) OVER (ORDER BY M)      AS m_score
    FROM rfm
)
SELECT account_id, R AS recency_days, F AS freq_90d, ROUND(M, 2) AS monetary_90d,
       r_score || '-' || f_score || '-' || m_score AS rfm_segment,
       CASE WHEN r_score = 3 AND f_score = 3 AND m_score = 3 THEN 'Key Value'
            WHEN r_score = 3 AND m_score = 3 THEN 'High Value Active'
            WHEN r_score = 1 AND m_score = 3 THEN 'High Value Churn Risk'
            WHEN r_score = 1 THEN 'Dormant'
            ELSE 'General' END AS segment_label
FROM scored
ORDER BY M DESC;

-- Q11 [Challenge] Monthly Customer-State Transition Matrix
-- Definition: new = account-opening month; active = traded this month; silent = no trades this month but traded within the prior 90 days; churned = all others
WITH months AS (SELECT DISTINCT month FROM asset_snapshot),
states AS (
    SELECT a.account_id, m.month,
           CASE
             WHEN to_char(c.open_date, 'YYYY-MM') = m.month THEN 'new'
             WHEN EXISTS (SELECT 1 FROM trade t
                           WHERE t.account_id = a.account_id AND t.month = m.month) THEN 'active'
             WHEN (SELECT MAX(t2.trade_date) FROM trade t2
                    WHERE t2.account_id = a.account_id AND t2.trade_date < (m.month || '-01')::date)
                  >= (m.month || '-01')::date - 90 THEN 'silent'
             ELSE 'churned'
           END AS status
    FROM account a
    JOIN customer c ON c.customer_id = a.customer_id
    CROSS JOIN months m
    WHERE m.month >= to_char(c.open_date, 'YYYY-MM')
),
seq AS (
    SELECT *, LAG(status) OVER (PARTITION BY account_id ORDER BY month) AS prev_status
    FROM states
)
SELECT prev_status AS from_status, status AS to_status, COUNT(*) AS customer_cnt
FROM seq
WHERE prev_status IS NOT NULL
GROUP BY prev_status, status
ORDER BY prev_status, customer_cnt DESC;

-- Q12 [Challenge] Top 20 Positions by Unrealized Profit
-- Definition: unrealized P&L = (latest real closing price - weighted average cost) × shares held
WITH latest_close AS (
    SELECT stock_code, close FROM daily_quote
    WHERE trade_date = (SELECT MAX(trade_date) FROM daily_quote)
),
pos AS (
    SELECT * FROM position_snapshot
    WHERE month = (SELECT MAX(month) FROM position_snapshot)
)
SELECT p.account_id, c.name, s.stock_name,
       p.shares, ROUND(p.avg_cost, 2) AS avg_cost, lc.close AS latest_close,
       ROUND((lc.close - p.avg_cost) * p.shares, 2)      AS unrealized_pnl,
       ROUND(100.0 * (lc.close - p.avg_cost) / p.avg_cost, 2) AS pnl_pct
FROM pos p
JOIN latest_close lc ON lc.stock_code = p.stock_code
JOIN stock s         ON s.stock_code = p.stock_code
JOIN customer c      ON c.customer_id = p.account_id
ORDER BY unrealized_pnl DESC
LIMIT 20;
