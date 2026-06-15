import os
from databricks import sql as databricks_sql
from dotenv import load_dotenv

load_dotenv()

DATABRICKS_HOST = os.getenv("DATABRICKS_HOST")
DATABRICKS_HTTP_PATH = os.getenv("DATABRICKS_HTTP_PATH")
DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN")

CATALOG = "databricks_virtue_foundation_dataset"
SCHEMA = "virtue_foundation_dataset"


def get_connection():
    return databricks_sql.connect(
        server_hostname=DATABRICKS_HOST,
        http_path=DATABRICKS_HTTP_PATH,
        access_token=DATABRICKS_TOKEN,
    )


def execute_query(query: str, params: dict | None = None) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def test_connection() -> dict:
    try:
        result = execute_query(
            f"SELECT COUNT(*) as cnt FROM {CATALOG}.{SCHEMA}.facilities"
        )
        return {"status": "connected", "facilities_count": result[0]["cnt"]}
    except Exception as e:
        return {"status": "error", "error": str(e)}
