-- B1–B3 Index Optimization DDL (run for the "optimized" benchmark; schema_pg.sql intentionally excludes these indexes)
-- B1: Q2 point lookup of customer trade details (account_id equality + trade_date range/ordering)
-- B3: Q9 MAX(trade_date) aggregation by account for dormant customers; shares the same composite index as B1
CREATE INDEX idx_trade_account_date ON trade (account_id, trade_date);

-- B2: Q3 covering index for monthly turnover rankings: month filter + stock_code grouping + amount coverage, targeting an index-only scan
CREATE INDEX idx_trade_month_cover ON trade (month, stock_code) INCLUDE (amount);
