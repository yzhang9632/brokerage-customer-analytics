-- ============================================================
-- Q1–Q12 业务查询 + 指标口径字典 · PostgreSQL 正式版
-- 业务逻辑与 SQLite 版一致，仅改为 PostgreSQL 日期/聚合语法
-- ============================================================

-- Q1【基础】各营业部客户数、资产总额汇总
-- 口径：取 asset_snapshot 最新月份；总资产=现金+持仓市值
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

-- Q2【基础】客户 360 视图
-- 口径：基本信息 + 本月成交笔数/金额 + 最新月资产 + 当前持仓清单
SELECT c.customer_id, c.name, b.branch_name, c.risk_level, c.open_date,
       (SELECT COUNT(*) FROM trade t JOIN account a2 ON a2.account_id = t.account_id
         WHERE a2.customer_id = c.customer_id
           AND t.month = (SELECT MAX(month) FROM trade))      AS month_trade_cnt,
       (SELECT ROUND(SUM(t.amount), 2) FROM trade t JOIN account a2 ON a2.account_id = t.account_id
         WHERE a2.customer_id = c.customer_id
           AND t.month = (SELECT MAX(month) FROM trade))      AS month_trade_amount,
       s.total_asset, s.cash, s.market_value,
       (SELECT STRING_AGG(st.stock_name || '×' || p.shares::text, '、')
          FROM position_snapshot p JOIN stock st ON st.stock_code = p.stock_code
         WHERE p.account_id = a.account_id
           AND p.month = (SELECT MAX(month) FROM position_snapshot)) AS holdings
FROM customer c
JOIN branch b         ON b.branch_id = c.branch_id
JOIN account a        ON a.customer_id = c.customer_id
JOIN asset_snapshot s ON s.account_id = a.account_id
                      AND s.month = (SELECT MAX(month) FROM asset_snapshot)
WHERE c.customer_id = 1;

-- Q3【基础】月度成交额 TOP 20 股票
-- 口径：买卖双边成交额均计入；示例取最新月
SELECT s.stock_code, s.stock_name, s.industry,
       COUNT(t.trade_id)             AS trade_cnt,
       ROUND(SUM(t.amount), 2)       AS turnover
FROM trade t
JOIN stock s ON s.stock_code = t.stock_code
WHERE t.month = (SELECT MAX(month) FROM trade)
GROUP BY t.stock_code, s.stock_code, s.stock_name, s.industry
ORDER BY turnover DESC
LIMIT 20;

-- Q4【基础】各营业部月度银证转账净流入
-- 口径：净流入 = 入金(in) − 出金(out)
SELECT b.branch_name,
       to_char(f.trans_date, 'YYYY-MM') AS month,
       ROUND(SUM(CASE WHEN f.direction = 'in' THEN f.amount ELSE -f.amount END), 2) AS net_inflow
FROM fund_flow f
JOIN account a  ON a.account_id = f.account_id
JOIN customer c ON c.customer_id = a.customer_id
JOIN branch b   ON b.branch_id = c.branch_id
GROUP BY b.branch_id, b.branch_name, to_char(f.trans_date, 'YYYY-MM')
ORDER BY month, net_inflow DESC;

-- Q5【进阶】客户月活跃率
-- 口径：活跃 = 当月 ≥1 笔成交；分母 = 截至当月末已开户客户数
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

-- Q6【进阶】客户资产五分层
-- 口径：最新月总资产 NTILE(5)，第 1 层 = 头部 20%
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

-- Q7【进阶】全市场成交额环比
-- 口径：环比 = (本月−上月)/上月；同比在 12 个月数据上使用 LAG(turnover, 12)
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

-- Q8【进阶】客户月均换手率 TOP 20
-- 口径（简化）：月换手率 = 当月买卖成交总额 / 当月末总资产
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

-- Q9【进阶】沉睡高净值唤醒名单
-- 口径：距基准日 >90 天无成交 且 最新月总资产 >10 万；从未成交者用开户日替代
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

-- Q10【挑战】客户 RFM 分层画像
-- 口径：R=最近成交距基准日天数；F/M=近 90 天笔数/金额；三维 NTILE(3)
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
       CASE WHEN r_score = 3 AND f_score = 3 AND m_score = 3 THEN '重要价值客户'
            WHEN r_score = 3 AND m_score = 3 THEN '高价值活跃客户'
            WHEN r_score = 1 AND m_score = 3 THEN '高价值流失风险客户'
            WHEN r_score = 1 THEN '沉睡客户'
            ELSE '一般客户' END AS segment_label
FROM scored
ORDER BY M DESC;

-- Q11【挑战】客户状态月度迁徙矩阵
-- 口径：new=开户当月；active=当月有成交；silent=当月无成交但此前 90 天内有成交；churned=其余
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

-- Q12【挑战】持仓浮盈 TOP 20
-- 口径：浮动盈亏 = (最新真实收盘价 − 加权平均成本) × 持股数
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
