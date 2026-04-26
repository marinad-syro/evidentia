import asyncio
import os
from typing import Any

_HAVERSINE_SQL = """
  2 * 6371 * ASIN(SQRT(
    POWER(SIN(RADIANS(latitude  - ?) / 2), 2) +
    COS(RADIANS(?)) * COS(RADIANS(latitude)) *
    POWER(SIN(RADIANS(longitude - ?) / 2), 2)
  ))
"""


def _table() -> str:
    catalog = os.environ.get("DATABRICKS_CATALOG", "hive_metastore")
    schema = os.environ.get("DATABRICKS_SCHEMA", "default")
    table = os.environ.get("DATABRICKS_TABLE", "providers")
    return f"`{catalog}`.`{schema}`.`{table}`"


def _connect():
    from databricks import sql
    return sql.connect(
        server_hostname=os.environ["DATABRICKS_HOST"],
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
    )


def _sync_filter(
    provider_ids: list[str],
    specialty_id: str,
    user_lat: float,
    user_lon: float,
    radius_km: float,
    preference: str | None,
) -> tuple[list[tuple[dict, float]], dict]:
    """
    Run a parameterised Databricks SQL query.
    Returns (results, stats) where results = [(row_dict, distance_km), ...]
    and stats = {"sent": N, "matched": M}.
    """
    if not provider_ids:
        return [], {"sent": 0, "matched": 0}

    placeholders = ", ".join(["?"] * len(provider_ids))
    pref_clause = "AND LOWER(COALESCE(operatorTypeId, '')) LIKE ?" if preference else ""

    query = f"""
        SELECT *,
            ROUND({_HAVERSINE_SQL}, 2) AS _distance_km
        FROM {_table()}
        WHERE provider_id IN ({placeholders})
          AND LOWER(COALESCE(specialties, '')) LIKE ?
          AND ({_HAVERSINE_SQL}) <= ?
          AND latitude  IS NOT NULL AND latitude  != 0
          AND longitude IS NOT NULL AND longitude != 0
          {pref_clause}
        ORDER BY _distance_km
    """

    # Parameters: haversine args × 2  + ids + specialty LIKE + haversine args × 2 + radius + optional pref
    dist_args = [user_lat, user_lat, user_lon]
    params = (
        dist_args
        + list(provider_ids)
        + [f"%{specialty_id.lower()}%"]
        + dist_args
        + [radius_km]
        + ([f"%{preference.lower()}%"] if preference else [])
    )

    results: list[tuple[dict, float]] = []
    print(f"[Databricks] querying {len(provider_ids)} candidates, radius={radius_km}km")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            cols = [d[0] for d in cur.description]
            for row_tuple in cur.fetchall():
                row: dict[str, Any] = dict(zip(cols, row_tuple))
                dist = float(row.pop("_distance_km", 0))
                results.append((row, dist))

    return results, {"sent": len(provider_ids), "matched": len(results)}


async def filter_providers(
    provider_ids: list[str],
    specialty_id: str,
    user_lat: float,
    user_lon: float,
    radius_km: float,
    preference: str | None = None,
) -> tuple[list[tuple[dict, float]], dict]:
    """Async wrapper — runs the blocking SQL query in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _sync_filter,
        provider_ids, specialty_id, user_lat, user_lon, radius_km, preference,
    )
