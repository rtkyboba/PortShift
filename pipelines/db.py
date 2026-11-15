"""Databricks SQL connection. Only used when DATABRICKS_HOST/TOKEN/WAREHOUSE_ID are set."""
import json
import os

COMPLEX = ("array", "map", "struct")


def configured() -> bool:
    return all(os.environ.get(k) for k in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID"))


def connect():
    from databricks import sql  # databricks-sql-connector
    return sql.connect(
        server_hostname=os.environ["DATABRICKS_HOST"].replace("https://", "").rstrip("/"),
        http_path=f"/sql/1.0/warehouses/{os.environ['DATABRICKS_WAREHOUSE_ID']}",
        access_token=os.environ["DATABRICKS_TOKEN"],
    )


def plain(v, type_code=None):
    """Without pyarrow the connector returns ARRAY/MAP/STRUCT columns as JSON text; decode them by column
    type so live rows have the same shape as demo/fixtures (e.g. legs.geometry is a list of [lat, lon])."""
    if type_code in COMPLEX and isinstance(v, str):
        return json.loads(v)
    if hasattr(v, "tolist"):
        v = v.tolist()
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    return v


def fetch(cursor, query: str) -> list[dict]:
    cursor.execute(query)
    cols = [(d[0], d[1] if len(d) > 1 else None) for d in cursor.description]
    return [{k: plain(v, t) for (k, t), v in zip(cols, row)} for row in cursor.fetchall()]
