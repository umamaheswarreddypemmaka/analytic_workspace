"""
SQL Server connection helper.

Requires sqlalchemy, pyodbc, and an ODBC driver on the machine running the app
("ODBC Driver 17 for SQL Server" or 18).

Anything typed into the query box runs against the connected database, so
run_query() refuses statements that are not plain SELECTs. Point the app at a
read-only login as well — the guard here is a seatbelt, not a permission model.
"""

import re
import urllib.parse

import pandas as pd

try:
    from sqlalchemy import create_engine, text
    SQLALCHEMY_AVAILABLE = True
except ImportError:                      # the app still runs on files and samples
    SQLALCHEMY_AVAILABLE = False

    def text(x):
        return x

    def create_engine(*a, **k):
        raise RuntimeError(
            "SQL Server support needs sqlalchemy and pyodbc. "
            "Install them with: pip install sqlalchemy pyodbc"
        )

DRIVERS = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server",
           "SQL Server"]

_BLOCKED = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|merge|"
    r"exec|execute|xp_cmdshell|sp_executesql|backup|restore|shutdown|openrowset)\b",
    re.IGNORECASE,
)


def get_sqlserver_engine(server, database, username=None, password=None,
                         trusted_connection=False,
                         driver="ODBC Driver 17 for SQL Server",
                         encrypt=True, trust_cert=True):
    """Build a SQLAlchemy engine. Set trusted_connection=True for Windows auth."""
    parts = [f"DRIVER={{{driver}}}", f"SERVER={server}", f"DATABASE={database}"]
    if trusted_connection:
        parts.append("Trusted_Connection=yes")
    else:
        parts += [f"UID={username}", f"PWD={password}"]
    if "18" in driver:
        parts.append(f"Encrypt={'yes' if encrypt else 'no'}")
        parts.append(f"TrustServerCertificate={'yes' if trust_cert else 'no'}")

    quoted = urllib.parse.quote_plus(";".join(parts) + ";")
    return create_engine(f"mssql+pyodbc:///?odbc_connect={quoted}",
                         pool_pre_ping=True)


def test_connection(engine):
    """Raises if the connection is not usable."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def list_tables(engine):
    query = """
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_SCHEMA, TABLE_NAME
    """
    return pd.read_sql(query, engine)


def is_read_only(sql: str) -> bool:
    body = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL).strip()
    if not body:
        return False
    if not re.match(r"^\s*(select|with)\b", body, re.IGNORECASE):
        return False
    if _BLOCKED.search(body):
        return False
    if ";" in body.rstrip().rstrip(";"):
        return False           # no stacked statements
    return True


def run_query(engine, sql, row_cap=50_000):
    """Run a SELECT and return a dataframe. Rejects anything that writes."""
    if not is_read_only(sql):
        raise ValueError(
            "Only single SELECT statements are allowed here. "
            "Remove any write or multi-statement SQL and try again."
        )
    df = pd.read_sql(text(sql), engine)
    if len(df) > row_cap:
        df = df.head(row_cap)
    return df


def quote_table(schema, table):
    """Bracket-quote an identifier so odd table names don't break the query."""
    def q(part):
        return "[" + str(part).replace("]", "]]") + "]"
    return f"{q(schema)}.{q(table)}"


def preview_table(engine, schema, table, limit=1000):
    return pd.read_sql(
        text(f"SELECT TOP {int(limit)} * FROM {quote_table(schema, table)}"), engine
    )


# Old name kept for compatibility with the first version of the app.
def fetch_data(engine, query):
    return run_query(engine, query)