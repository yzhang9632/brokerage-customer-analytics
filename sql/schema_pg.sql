-- 券商零售客户经营分析数据库 · PostgreSQL 正式版 DDL（9 表）
-- 课程要求 client-server DBMS，本文件为最终交付版本；schema.sql 仅保留 SQLite 迁移前备份。
-- 日期使用原生 DATE；month 统一 TEXT 'YYYY-MM'，由导入脚本从 trade_date 生成。

CREATE TABLE branch (
    branch_id   INTEGER PRIMARY KEY,
    branch_name TEXT NOT NULL,
    city        TEXT NOT NULL
);

CREATE TABLE customer (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    gender      TEXT CHECK (gender IN ('M', 'F')),
    birth_year  INTEGER CHECK (birth_year BETWEEN 1930 AND 2010),
    branch_id   INTEGER NOT NULL REFERENCES branch (branch_id),
    open_date   DATE NOT NULL,
    risk_level  TEXT CHECK (risk_level IN ('C1', 'C2', 'C3', 'C4', 'C5'))
);

CREATE TABLE account (
    account_id   INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customer (customer_id),
    account_type TEXT NOT NULL DEFAULT 'cash',
    open_date    DATE NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'frozen', 'closed'))
);

CREATE TABLE stock (
    stock_code TEXT PRIMARY KEY,
    stock_name TEXT NOT NULL,
    industry   TEXT,
    list_date  DATE
);

CREATE TABLE daily_quote (
    stock_code TEXT NOT NULL REFERENCES stock (stock_code),
    trade_date DATE NOT NULL,
    open       NUMERIC(12, 2) NOT NULL,
    high       NUMERIC(12, 2) NOT NULL,
    low        NUMERIC(12, 2) NOT NULL,
    close      NUMERIC(12, 2) NOT NULL,
    volume     BIGINT NOT NULL,
    amount     NUMERIC(20, 2),
    PRIMARY KEY (stock_code, trade_date)
);

CREATE TABLE trade (
    trade_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES account (account_id),
    stock_code TEXT NOT NULL REFERENCES stock (stock_code),
    trade_date DATE NOT NULL,
    trade_time TIME NOT NULL,
    side       TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    price      NUMERIC(12, 2) NOT NULL CHECK (price > 0),
    volume     INTEGER NOT NULL CHECK (volume > 0 AND volume % 100 = 0),
    amount     NUMERIC(16, 2) NOT NULL CHECK (amount > 0),
    month      TEXT NOT NULL
);

CREATE TABLE fund_flow (
    flow_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES account (account_id),
    trans_date DATE NOT NULL,
    direction  TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    amount     NUMERIC(16, 2) NOT NULL CHECK (amount > 0)
);

CREATE TABLE position_snapshot (
    account_id   INTEGER NOT NULL REFERENCES account (account_id),
    stock_code   TEXT NOT NULL REFERENCES stock (stock_code),
    month        TEXT NOT NULL,
    shares       INTEGER NOT NULL CHECK (shares > 0),
    avg_cost     NUMERIC(16, 4) NOT NULL,
    market_value NUMERIC(18, 2) NOT NULL,
    PRIMARY KEY (account_id, stock_code, month)
);

CREATE TABLE asset_snapshot (
    account_id   INTEGER NOT NULL REFERENCES account (account_id),
    month        TEXT NOT NULL,
    cash         NUMERIC(18, 2) NOT NULL CHECK (cash >= 0),
    market_value NUMERIC(18, 2) NOT NULL,
    total_asset  NUMERIC(18, 2) NOT NULL,
    PRIMARY KEY (account_id, month)
);

-- 仅保留基础索引；B1-B4 的优化索引另放 indexes_pg.sql，便于做优化前后对照
CREATE INDEX idx_trade_month ON trade (month);
