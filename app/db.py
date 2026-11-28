# -*- coding: utf-8 -*-
"""Database connection and query helpers shared by all Streamlit pages."""
import os
import warnings
from pathlib import Path

import pandas as pd
import psycopg
import streamlit as st

# Automatically load .env (including PGPASSWORD) from the project root so both
# double-click and command-line launches can access the password; .env is not committed to Git.
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
    """Cache dashboard queries for 10 minutes to avoid rerunning large-table aggregations on every interaction."""
    with psycopg.connect(**get_dsn()) as conn:
        return pd.read_sql(sql, conn, params=params)


def query_fresh(sql: str, params: tuple | None = None) -> pd.DataFrame:
    """Use uncached queries where real-time data is required, such as the order entry page."""
    with psycopg.connect(**get_dsn()) as conn:
        return pd.read_sql(sql, conn, params=params)
