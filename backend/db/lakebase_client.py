import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

LAKEBASE_URL = os.getenv("LAKEBASE_URL")
LAKEBASE_HOST = os.getenv("LAKEBASE_HOST")
LAKEBASE_PORT = os.getenv("LAKEBASE_PORT", "5432")
LAKEBASE_DB = os.getenv("LAKEBASE_DB")
LAKEBASE_USER = os.getenv("LAKEBASE_USER")
LAKEBASE_PASSWORD = os.getenv("LAKEBASE_PASSWORD")


def get_connection():
    if LAKEBASE_URL:
        return psycopg2.connect(LAKEBASE_URL)
    return psycopg2.connect(
        host=LAKEBASE_HOST,
        port=LAKEBASE_PORT,
        dbname=LAKEBASE_DB,
        user=LAKEBASE_USER,
        password=LAKEBASE_PASSWORD,
        sslmode="require",
    )


def execute_query(query: str, params: tuple | None = None) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


def execute_write(query: str, params: tuple | None = None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
        conn.commit()


def init_schema():
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        sql = f.read()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def test_connection() -> dict:
    try:
        result = execute_query("SELECT 1 as ok")
        return {"status": "connected"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
