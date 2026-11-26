-- B1–B3 索引优化 DDL（基准测试"优化后"执行；schema_pg.sql 刻意不含这些索引）
-- B1：Q2 客户交易明细点查（account_id 等值 + trade_date 范围/排序）
-- B3：Q9 沉睡客户 MAX(trade_date) 按账户聚合，与 B1 共用同一复合索引
CREATE INDEX idx_trade_account_date ON trade (account_id, trade_date);

-- B2：Q3 月度成交额 TOP 榜覆盖索引：month 过滤 + stock_code 分组 + amount 覆盖，目标 index-only scan
CREATE INDEX idx_trade_month_cover ON trade (month, stock_code) INCLUDE (amount);
