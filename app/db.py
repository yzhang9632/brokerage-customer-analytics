# -*- coding: utf-8 -*-
"""数据库连接与查询（Streamlit 各页面共用）。"""
import os
import warnings
from pathlib import Path

import pandas as pd
import psycopg
import streamlit as st

# 自动读取项目根目录 .env（含 PGPASSWORD），双击/命令行启动都能拿到密码；.env 不进 Git
_env_file = Path(__file__).resolve().parents[1] / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        if _line.strip() and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")


def get_dsn() -> dict:
    return {
        "host": os.getenv("PGHOST", "127.0.0.1"),
        "port": int(os.getenv("PGPORT", "5432")),
        "user": os.getenv("PGUSER", "postgres"),
        "password": os.getenv("PGPASSWORD", ""),
        "dbname": os.getenv("PGDATABASE", "brokerage"),
    }


@st.cache_data(ttl=600)
def query(sql: str, params: tuple | None = None) -> pd.DataFrame:
    """看板查询缓存 10 分钟，避免每次交互重跑大表聚合。"""
    with psycopg.connect(**get_dsn()) as conn:
        return pd.read_sql(sql, conn, params=params)


def query_fresh(sql: str, params: tuple | None = None) -> pd.DataFrame:
    """下单页等需要实时数据的地方使用，不走缓存。"""
    with psycopg.connect(**get_dsn()) as conn:
        return pd.read_sql(sql, conn, params=params)
