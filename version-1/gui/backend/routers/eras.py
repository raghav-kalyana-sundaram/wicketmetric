"""
Eras router — /api/eras endpoint.

Provides:
- GET /api/eras  → Era baselines (par SR, boundary rate, dot%, multiplier) by year
"""

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, HTTPException
from db import safe_float, safe_int, safe_fmt
from schemas import EraBaseline, EraResponse

router = APIRouter(prefix="/api", tags=["eras"])


def _get_store():
    raise HTTPException(
        status_code=503,
        detail="Data store not initialised (dependency override missing).",
    )


_ERA_CACHE_SQL = "SELECT * FROM {fmt}.era_baselines_cache ORDER BY year"

_ERA_COMPUTE_SQL = """
WITH yearly AS (
    SELECT DATE_PART('year', TRY_CAST(date AS TIMESTAMP))::INTEGER AS year,
           MEDIAN(sr) AS par_sr,
           (SUM(COALESCE(fours,0)) + SUM(COALESCE(sixes,0)))
             / NULLIF(SUM(COALESCE(balls_faced,0)), 0) * 100.0 AS boundary_rate,
           SUM(COALESCE(dots,0))
             / NULLIF(SUM(COALESCE(balls_faced,0)), 0) * 100.0 AS dot_pct,
           COUNT(DISTINCT match_id) AS matches,
           COUNT(*) AS innings
    FROM {fmt}.bat_innings
    WHERE DATE_PART('year', TRY_CAST(date AS TIMESTAMP)) >= 2005
    GROUP BY year HAVING COUNT(*) >= 10
),
latest_par AS (
    SELECT par_sr AS latest_par_sr FROM yearly
    WHERE par_sr IS NOT NULL ORDER BY year DESC LIMIT 1
)
SELECT y.year, ROUND(y.par_sr, 2) AS par_sr,
       ROUND(y.boundary_rate, 2) AS boundary_rate,
       ROUND(y.dot_pct, 2) AS dot_pct,
       y.matches, y.innings,
       ROUND(l.latest_par_sr / NULLIF(y.par_sr, 0), 3) AS multiplier
FROM yearly y CROSS JOIN latest_par l ORDER BY y.year
"""


@router.get("/eras", response_model=EraResponse, summary="Era baselines by year")
async def get_eras(db=Depends(_get_store)):
    conn, fmt = db
    f = safe_fmt(fmt)

    try:
        result = conn.execute(_ERA_CACHE_SQL.format(fmt=f))
        cols = [d[0] for d in result.description]
        rows = result.fetchall()
    except duckdb.CatalogException:
        result = conn.execute(_ERA_COMPUTE_SQL.format(fmt=f))
        cols = [d[0] for d in result.description]
        rows = result.fetchall()

    baselines = []
    for row in rows:
        d = dict(zip(cols, row))
        baselines.append(EraBaseline(
            year=safe_int(d.get("year")) or 0,
            par_sr=safe_float(d.get("par_sr")),
            boundary_rate=safe_float(d.get("boundary_rate")),
            dot_pct=safe_float(d.get("dot_pct")),
            multiplier=safe_float(d.get("multiplier")),
        ))

    return EraResponse(baselines=baselines)
