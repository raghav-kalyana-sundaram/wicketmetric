"""
Rankings router — /api/rankings/{role} with sorting, filtering, pagination.

Provides sortable, filterable leaderboards for batting and bowling metrics.
Supports sorting by any numeric column, filtering by country/archetype/
provisional status/minimum innings, and cursor-based pagination.

Endpoints:
- GET /api/rankings/bat          → Batting leaderboard
- GET /api/rankings/bowl         → Bowling leaderboard
- GET /api/rankings/bat/distribution   → Quartiles + histogram for one metric (filtered pool)
- GET /api/rankings/bowl/distribution  → Same for bowling
- GET /api/rankings/bat/heatmap / bowl/heatmap → Correlation + intensity matrix (filtered pool)
- GET /api/rankings/columns/bat  → Valid batting sort columns
- GET /api/rankings/columns/bowl → Valid bowling sort columns
- GET /api/rankings/top          → Top-N players for a metric (dashboard cards)
"""

from __future__ import annotations

import math
from typing import Any

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query
from db import (
    DEFAULT_FORMAT,
    VALID_FORMATS,
    activity_cutoff_date,
    query_all,
    safe_float,
    safe_fmt,
    safe_int,
    safe_str,
)
from schemas import (
    LeaderboardDistributionBin,
    LeaderboardDistributionOutlier,
    LeaderboardDistributionResponse,
    LeaderboardHeatmapResponse,
    LeaderboardResponse,
    PlayerSummary,
)

router = APIRouter(prefix="/api", tags=["rankings"])

_FORMAT_PATTERN = "^(" + "|".join(VALID_FORMATS) + ")$"


# ── Dependency placeholder (overridden in app.py) ─────────────────


def _get_store():
    raise HTTPException(
        status_code=503,
        detail="Data store not initialised (dependency override missing).",
    )


# ── Valid sort columns per role ───────────────────────────────────

BATTING_SORT_COLUMNS = {
    "score_acceleration",
    "score_power",
    "score_control",
    "rating_current",
    "rating_overall",
    "overall_score",
    "career_sr",
    "career_avg",
    "innings_count",
    "total_runs",
    "total_balls",
    "total_fours",
    "total_sixes",
    "war_batting",
    "war_batting_rate",
    "clutch_index",
    "clutch_sr_delta",
    "chase_master_index",
    "chase_master_full",
    "flat_track_index",
    "venue_adjusted_composite",
    "selfless_index",
    "anchor_cost_ratio",
    "avg_balls_to_par",
    "avg_dominance",
    "pct_dominant",
    "matchup_consistency",
    "peak_composite_batting",
    "peak_window_composite",
}

BOWLING_SORT_COLUMNS = {
    "score_accuracy",
    "score_control",
    "score_threat",
    "rating_current",
    "rating_overall",
    "overall_score",
    "career_economy",
    "career_sr_bowl",
    "career_dot_pct",
    "matches",
    "total_wickets",
    "total_overs",
    "total_runs_conceded",
    "war_bowling",
    "war_bowling_rate",
    "clutch_index_bowl",
    "flat_track_index_bowl",
    "avg_dominance_bowl",
    "pct_dominant_bowl",
    "bowled_lbw_pct",
    "peak_composite_bowling",
    "peak_window_composite",
}

# SQL-safe allowlists (rating_current/rating_overall are computed aliases)
_BAT_SQL_SORT_ALLOW = (BATTING_SORT_COLUMNS - {"rating_current", "rating_overall"}) | {
    "rating_current",
    "rating_overall",
}
_BOWL_SQL_SORT_ALLOW = (BOWLING_SORT_COLUMNS - {"rating_current", "rating_overall"}) | {
    "rating_current",
    "rating_overall",
}


# ── SQL fragments ─────────────────────────────────────────────────

_BAT_RATING_SQL = """
    CASE WHEN overall_score IS NULL THEN NULL
         WHEN COALESCE(form_composite_max, peak_window_composite) IS NULL THEN overall_score
         ELSE LEAST(overall_score, COALESCE(form_composite_max, peak_window_composite))
    END AS rating_overall,
    CASE WHEN innings_count >= 10 AND form_composite_latest IS NOT NULL THEN
         CASE WHEN COALESCE(form_composite_max, peak_window_composite) IS NOT NULL
              THEN LEAST(form_composite_latest, COALESCE(form_composite_max, peak_window_composite))
              ELSE form_composite_latest END
         ELSE
         CASE WHEN overall_score IS NULL THEN NULL
              WHEN COALESCE(form_composite_max, peak_window_composite) IS NULL THEN overall_score
              ELSE LEAST(overall_score, COALESCE(form_composite_max, peak_window_composite))
         END
    END AS rating_current
"""

_BOWL_RATING_SQL = """
    CASE WHEN overall_score IS NULL THEN NULL
         WHEN COALESCE(form_composite_max, peak_window_composite) IS NULL THEN overall_score
         ELSE LEAST(overall_score, COALESCE(form_composite_max, peak_window_composite))
    END AS rating_overall,
    CASE WHEN matches >= 10 AND form_composite_latest IS NOT NULL THEN
         CASE WHEN COALESCE(form_composite_max, peak_window_composite) IS NOT NULL
              THEN LEAST(form_composite_latest, COALESCE(form_composite_max, peak_window_composite))
              ELSE form_composite_latest END
         ELSE
         CASE WHEN overall_score IS NULL THEN NULL
              WHEN COALESCE(form_composite_max, peak_window_composite) IS NULL THEN overall_score
              ELSE LEAST(overall_score, COALESCE(form_composite_max, peak_window_composite))
         END
    END AS rating_current
"""


def _bat_table(fmt: str, ctx_entry_phase: str) -> str:
    """Resolve the batting career table based on context entry phase."""
    phase = (ctx_entry_phase or "none").strip().lower()
    if phase == "early":
        return f"{fmt}.bat_careers_ctx_entry_early"
    if phase == "death":
        return f"{fmt}.bat_careers_ctx_entry_death"
    return f"{fmt}.bat_careers"


def _validate_sort(sort: str, allowlist: set[str], fallback: str) -> str:
    col = sort.strip()
    if col in allowlist:
        return col
    return fallback


def _build_where(
    *,
    country: str | None = None,
    archetype: str | None = None,
    provisional: bool | None = None,
    min_innings: int | None = None,
    position_group: str | None = None,
    phase_group: str | None = None,
    modal_slot: int | None = None,
    activity: str = "all",
    cutoff: str | None = None,
    provisional_col: str = "is_provisional_bat",
    innings_col: str = "innings_count",
) -> tuple[str, list]:
    """Build a WHERE clause and parameter list from filter values."""
    clauses: list[str] = ["1=1"]
    params: list[Any] = []

    if country:
        clauses.append("LOWER(country) = LOWER(?)")
        params.append(country.strip())

    if archetype:
        clauses.append("LOWER(archetype) = LOWER(?)")
        params.append(archetype.strip())

    if provisional is not None:
        if provisional:
            clauses.append(f"{provisional_col} = TRUE")
        else:
            clauses.append(f"({provisional_col} IS NULL OR {provisional_col} = FALSE)")

    if min_innings is not None and min_innings > 0:
        clauses.append(f"{innings_col} >= ?")
        params.append(min_innings)

    if position_group:
        clauses.append("LOWER(position_group) = LOWER(?)")
        params.append(position_group.strip())

    if phase_group:
        clauses.append("LOWER(phase_group) = LOWER(?)")
        params.append(phase_group.strip())

    if modal_slot is not None:
        try:
            slot_i = int(modal_slot)
        except (TypeError, ValueError):
            slot_i = None
        if slot_i is not None and 1 <= slot_i <= 11:
            clauses.append("TRY_CAST(modal_position AS INTEGER) = ?")
            params.append(slot_i)

    act = (activity or "all").lower().strip()
    if act == "active" and cutoff:
        clauses.append("last_match_date IS NOT NULL AND last_match_date >= ?")
        params.append(cutoff)
    elif act == "retired" and cutoff:
        clauses.append("(last_match_date IS NULL OR last_match_date < ?)")
        params.append(cutoff)

    return " AND ".join(clauses), params


# ── Row → PlayerSummary converters ────────────────────────────────


def _metric_map(row: dict, metric_keys: set[str]) -> dict[str, float | None]:
    metrics: dict[str, float | None] = {}
    for key in metric_keys:
        v = row.get(key)
        if v is not None:
            metrics[key] = safe_float(v)
    return metrics


def _bat_row_to_summary(row: dict, cutoff: str | None) -> PlayerSummary:
    last_md = None
    active_flag = False
    lm = row.get("last_match_date")
    if lm is not None:
        try:
            last_md = str(lm)[:10]
            active_flag = cutoff is not None and last_md >= cutoff
        except Exception:
            pass

    mp = safe_int(row.get("modal_position"))
    modal_position = mp if 1 <= mp <= 11 else None

    return PlayerSummary(
        id=safe_str(row.get("batter_id"), ""),
        name=safe_str(row.get("batter"), ""),
        country=safe_str(row.get("country"), ""),
        role="bat",
        archetype=safe_str(row.get("archetype"), ""),
        grade_overall=safe_str(row.get("overall_grade"), "D"),
        innings_count=safe_int(row.get("innings_count")),
        total_runs=safe_int(row.get("total_runs")),
        career_sr=safe_float(row.get("career_sr")),
        career_avg=safe_float(row.get("career_avg")),
        score_1=safe_float(row.get("score_acceleration")),
        score_2=safe_float(row.get("score_power")),
        score_3=safe_float(row.get("score_control")),
        score_1_label="acceleration",
        score_2_label="power",
        score_3_label="control",
        is_provisional=bool(row.get("is_provisional_bat", True)),
        overall_score=safe_float(row.get("overall_score")),
        metrics=_metric_map(row, BATTING_SORT_COLUMNS),
        last_match_date=last_md,
        is_active=active_flag,
        rating_current=safe_float(row.get("rating_current")),
        rating_overall=safe_float(row.get("rating_overall")),
        modal_position=modal_position,
        recent_team=safe_str(row.get("recent_team"), "") or None,
    )


def _bowl_row_to_summary(row: dict, cutoff: str | None) -> PlayerSummary:
    last_md = None
    active_flag = False
    lm = row.get("last_match_date")
    if lm is not None:
        try:
            last_md = str(lm)[:10]
            active_flag = cutoff is not None and last_md >= cutoff
        except Exception:
            pass

    return PlayerSummary(
        id=safe_str(row.get("bowler_id"), ""),
        name=safe_str(row.get("bowler"), ""),
        country=safe_str(row.get("country"), ""),
        role="bowl",
        archetype=safe_str(row.get("archetype"), ""),
        grade_overall=safe_str(row.get("overall_grade"), "D"),
        innings_count=safe_int(row.get("matches")),
        total_runs=safe_int(row.get("total_wickets")),
        career_sr=safe_float(row.get("career_economy")),
        career_avg=safe_float(row.get("career_sr_bowl")),
        score_1=safe_float(row.get("score_accuracy")),
        score_2=safe_float(row.get("score_control")),
        score_3=safe_float(row.get("score_threat")),
        score_1_label="accuracy",
        score_2_label="control",
        score_3_label="threat",
        is_provisional=bool(row.get("is_provisional_bowl", True)),
        overall_score=safe_float(row.get("overall_score")),
        metrics=_metric_map(row, BOWLING_SORT_COLUMNS),
        last_match_date=last_md,
        is_active=active_flag,
        rating_current=safe_float(row.get("rating_current")),
        rating_overall=safe_float(row.get("rating_overall")),
        modal_position=None,
        recent_team=safe_str(row.get("recent_team"), "") or None,
        phase_group=safe_str(row.get("phase_group"), "") or None,
    )


# ── Distribution (box / violin) ───────────────────────────────────

_DIST_HIST_BINS = 48
_DIST_MAX_OUTLIERS = 50


def _quantile_sorted(sorted_vals: list[float], q: float) -> float | None:
    """Linear-interpolated quantile for q in [0, 1]."""
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = (n - 1) * q
    lo_i = int(math.floor(pos))
    hi_i = int(math.ceil(pos))
    lo_i = max(0, min(n - 1, lo_i))
    hi_i = max(0, min(n - 1, hi_i))
    if lo_i == hi_i:
        return sorted_vals[lo_i]
    return sorted_vals[lo_i] + (sorted_vals[hi_i] - sorted_vals[lo_i]) * (pos - lo_i)


def _histogram_bins(vals: list[float], n_bins: int = _DIST_HIST_BINS) -> list[LeaderboardDistributionBin]:
    if not vals:
        return []
    lo = min(vals)
    hi = max(vals)
    if hi == lo:
        return [LeaderboardDistributionBin(bin_start=lo, bin_end=hi, count=len(vals))]
    width = (hi - lo) / n_bins
    buckets = [0] * n_bins
    for v in vals:
        i = int((v - lo) / width)
        if i < 0:
            i = 0
        elif i >= n_bins:
            i = n_bins - 1
        buckets[i] += 1
    bins: list[LeaderboardDistributionBin] = []
    for i, c in enumerate(buckets):
        b0 = lo + i * width
        b1 = lo + (i + 1) * width
        bins.append(LeaderboardDistributionBin(bin_start=b0, bin_end=b1, count=c))
    return bins


def _build_distribution_response(
    *,
    metric: str,
    role: str,
    points: list[tuple[float, str, str]],
) -> LeaderboardDistributionResponse:
    """points: (value, player_id, player_name)."""
    if not points:
        return LeaderboardDistributionResponse(metric=metric, role=role, n=0)

    vals = sorted(p[0] for p in points)
    n = len(vals)
    vmin = vals[0]
    vmax = vals[-1]
    q1 = _quantile_sorted(vals, 0.25)
    med = _quantile_sorted(vals, 0.5)
    q3 = _quantile_sorted(vals, 0.75)
    mean_v = sum(vals) / n
    iqr = None
    whisker_low = vmin
    whisker_high = vmax
    outliers: list[LeaderboardDistributionOutlier] = []

    if q1 is not None and q3 is not None:
        iqr = q3 - q1
        if iqr is not None and iqr > 0:
            low_f = q1 - 1.5 * iqr
            high_f = q3 + 1.5 * iqr
            inside = [x for x in vals if low_f <= x <= high_f]
            if inside:
                whisker_low = min(inside)
                whisker_high = max(inside)
            out_pts = [(v, pid, name) for v, pid, name in points if v < low_f or v > high_f]
            out_pts.sort(key=lambda t: abs(t[0] - (med or t[0])), reverse=True)
            for v, pid, name in out_pts[:_DIST_MAX_OUTLIERS]:
                outliers.append(
                    LeaderboardDistributionOutlier(
                        player_id=pid,
                        player_name=name,
                        value=float(v),
                    )
                )

    return LeaderboardDistributionResponse(
        metric=metric,
        role=role,
        n=n,
        min=float(vmin),
        max=float(vmax),
        q1=float(q1) if q1 is not None else None,
        median=float(med) if med is not None else None,
        q3=float(q3) if q3 is not None else None,
        mean=float(mean_v),
        whisker_low=float(whisker_low),
        whisker_high=float(whisker_high),
        iqr=float(iqr) if iqr is not None else None,
        outliers=outliers,
        histogram_bins=_histogram_bins(vals),
    )


# ── Heatmap (correlation + intensity) ─────────────────────────────

_HEATMAP_MAX_SAMPLE = 500
_HEATMAP_DEFAULT_SAMPLE = 400
_HEATMAP_MIN_PAIR_OBS = 12
_INTENSITY_MAX_PLAYERS = 35
_INTENSITY_MAX_METRICS = 10

_BAT_INTENSITY_DEFAULT_METRICS = [
    "rating_current",
    "career_sr",
    "career_avg",
    "overall_score",
    "total_runs",
]
_BOWL_INTENSITY_DEFAULT_METRICS = [
    "rating_current",
    "career_economy",
    "total_wickets",
    "matches",
    "overall_score",
]


def _heatmap_columns_present(rows: list[dict], allow: set[str]) -> list[str]:
    if not rows:
        return []
    have = set(rows[0].keys())
    return sorted(c for c in allow if c in have)


def _pearson_paired(rows: list[dict], ca: str, cb: str, min_n: int) -> float | None:
    pairs: list[tuple[float, float]] = []
    for r in rows:
        va, vb = r.get(ca), r.get(cb)
        if va is None or vb is None:
            continue
        fa, fb = safe_float(va), safe_float(vb)
        if fa is None or fb is None:
            continue
        pairs.append((float(fa), float(fb)))
    n = len(pairs)
    if n < min_n:
        return None
    mx = sum(a for a, _ in pairs) / n
    my = sum(b for _, b in pairs) / n
    varx = sum((a - mx) ** 2 for a, _ in pairs)
    vary = sum((b - my) ** 2 for _, b in pairs)
    if varx <= 0.0 or vary <= 0.0:
        return None
    cov = sum((a - mx) * (b - my) for a, b in pairs)
    r = cov / math.sqrt(varx * vary)
    if math.isnan(r):
        return None
    return max(-1.0, min(1.0, float(r)))


def _correlation_matrix(
    rows: list[dict], cols: list[str], min_n: int
) -> list[list[float | None]]:
    n = len(cols)
    mat: list[list[float | None]] = [[None] * n for _ in range(n)]
    for i, ai in enumerate(cols):
        for j, bj in enumerate(cols):
            if j < i:
                mat[i][j] = mat[j][i]
            elif i == j:
                mat[i][j] = 1.0
            else:
                mat[i][j] = _pearson_paired(rows, ai, bj, min_n)
    return mat


def _normalize_01_column(vals: list[float | None]) -> list[float | None]:
    xs = [v for v in vals if v is not None]
    if not xs:
        return [None] * len(vals)
    lo, hi = min(xs), max(xs)
    span = (hi - lo) if hi != lo else 1.0
    out: list[float | None] = []
    for v in vals:
        if v is None:
            out.append(None)
        else:
            out.append(float((v - lo) / span))
    return out


def _parse_intensity_metrics(
    raw: str | None, allow: set[str], defaults: list[str], max_n: int
) -> list[str]:
    if raw and raw.strip():
        keys = [x.strip() for x in raw.split(",") if x.strip()]
    else:
        keys = list(defaults)
    out: list[str] = []
    for k in keys:
        if k in allow and k not in out:
            out.append(k)
    return out[:max_n]


def _intensity_matrix(
    rows_all: list[dict],
    *,
    allow: set[str],
    id_key: str,
    name_key: str,
    top: int,
    sort_metric: str,
    metrics_csv: str | None,
    defaults: list[str],
) -> tuple[list[str], list[str], list[str], list[list[float | None]]]:
    sort_col = _validate_sort(sort_metric, allow, defaults[0])
    metrics = _parse_intensity_metrics(metrics_csv, allow, defaults, _INTENSITY_MAX_METRICS)
    if not metrics:
        return [], [], [], []

    def _sort_key(r: dict) -> float:
        v = r.get(sort_col)
        if v is None:
            return float("-inf")
        fv = safe_float(v)
        return float(fv) if fv is not None else float("-inf")

    rows_sorted = sorted(rows_all, key=_sort_key, reverse=True)
    sub = rows_sorted[: max(1, min(top, _INTENSITY_MAX_PLAYERS))]
    ids = [safe_str(r.get(id_key)) for r in sub]
    names = [safe_str(r.get(name_key)) for r in sub]
    raw_m: list[list[float | None]] = []
    for r in sub:
        row: list[float | None] = []
        for mk in metrics:
            v = r.get(mk)
            row.append(safe_float(v) if v is not None else None)
        raw_m.append(row)
    nrow = len(raw_m)
    ncol = len(metrics)
    if nrow == 0 or ncol == 0:
        return ids, names, metrics, []
    out: list[list[float | None]] = [[None] * ncol for _ in range(nrow)]
    for j in range(ncol):
        col = [raw_m[i][j] for i in range(nrow)]
        coln = _normalize_01_column(col)
        for i in range(nrow):
            out[i][j] = coln[i]
    return ids, names, metrics, out


def _build_heatmap_response(
    *,
    role: str,
    rows: list[dict],
    allow: set[str],
    id_key: str,
    name_key: str,
    min_pair_obs: int,
    intensity_top: int,
    intensity_sort: str,
    intensity_metrics: str | None,
    defaults_metrics: list[str],
) -> LeaderboardHeatmapResponse:
    if not rows:
        return LeaderboardHeatmapResponse(role=role, n_players=0)
    cols = _heatmap_columns_present(rows, allow)
    corr = _correlation_matrix(rows, cols, min_pair_obs) if cols else []
    i_ids, i_names, i_metrics, i_mat = _intensity_matrix(
        rows,
        allow=allow,
        id_key=id_key,
        name_key=name_key,
        top=intensity_top,
        sort_metric=intensity_sort,
        metrics_csv=intensity_metrics,
        defaults=defaults_metrics,
    )
    return LeaderboardHeatmapResponse(
        role=role,
        n_players=len(rows),
        correlation_columns=cols,
        correlation=corr,
        intensity_player_ids=i_ids,
        intensity_player_names=i_names,
        intensity_metrics=i_metrics,
        intensity_matrix=i_mat,
    )


# ── Route: GET /api/rankings/bat ──────────────────────────────────


@router.get("/rankings/bat", response_model=LeaderboardResponse)
async def batting_leaderboard(
    sort: str = Query(
        "rating_current",
        description=(
            "Column to sort by. Includes rating_current, rating_overall (display "
            "ratings), overall_score (pipeline composite), score_acceleration, "
            "score_power, score_control, career_sr, career_avg, innings_count, "
            "total_runs, war_batting, clutch_index, chase_master_index, "
            "flat_track_index, etc."
        ),
    ),
    order: str = Query("desc", description="Sort order: asc or desc"),
    country: str | None = Query(
        None, description="Filter by country (case-insensitive)"
    ),
    archetype: str | None = Query(
        None, description="Filter by archetype (case-insensitive)"
    ),
    position_group: str | None = Query(
        None,
        description=(
            "Filter by batting position group: "
            "top_order, middle_order, lower_order, opener"
        ),
    ),
    modal_slot: int | None = Query(
        None,
        ge=1,
        le=11,
        description="Filter by modal batting entry position (1–11).",
    ),
    min_innings: int | None = Query(None, ge=0, description="Minimum innings played"),
    provisional: bool | None = Query(
        None,
        description="True = only provisional, False = exclude provisional, None = all",
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page"),
    activity: str = Query(
        "active",
        description=(
            "Player pool: active (last match within 1y for T20I, 2y for IPL), "
            "retired, or all"
        ),
        pattern="^(active|retired|all)$",
    ),
    format: str = Query(
        DEFAULT_FORMAT,
        description="Dataset slice (e.g. mens_t20i, womens_t20i, womens_ipl).",
        pattern=_FORMAT_PATTERN,
    ),
    ctx_entry_phase: str = Query(
        "none",
        description=(
            "Innings entry context: none (full career), early (first ball overs 1–4), "
            "death (first ball overs 16–20)."
        ),
        pattern="^(none|early|death)$",
    ),
    ctx_knockouts_only: bool = Query(
        False,
        description="Knockout/playoff-only leaderboard (not yet supported — returns empty).",
    ),
    ctx_chase_high_rpo: bool = Query(
        False,
        description="High required-rate chase leaderboard (not yet supported — returns empty).",
    ),
    db=Depends(_get_store),
) -> LeaderboardResponse:
    """Return a sorted, filterable, paginated batting leaderboard."""
    conn, fmt = db
    f = safe_fmt(fmt)

    if ctx_knockouts_only or ctx_chase_high_rpo:
        return LeaderboardResponse(
            players=[], total=0, page=page, per_page=per_page, total_pages=0
        )

    table = _bat_table(f, ctx_entry_phase)
    cutoff = activity_cutoff_date(conn, f)
    sort_col = _validate_sort(sort, BATTING_SORT_COLUMNS, "rating_current")
    direction = "ASC" if order.lower() == "asc" else "DESC"

    where_clause, params = _build_where(
        country=country,
        archetype=archetype,
        provisional=provisional,
        min_innings=min_innings,
        position_group=position_group,
        modal_slot=modal_slot,
        activity=activity,
        cutoff=cutoff,
        provisional_col="is_provisional_bat",
        innings_col="innings_count",
    )

    offset = (page - 1) * per_page

    sql = f"""
        WITH ranked AS (
            SELECT *,
                {_BAT_RATING_SQL},
                COUNT(*) OVER () AS _total_count
            FROM {table}
            WHERE {where_clause}
        )
        SELECT * FROM ranked
        ORDER BY {sort_col} {direction} NULLS LAST
        LIMIT ? OFFSET ?
    """
    params.extend([per_page, offset])

    try:
        rows = query_all(conn, sql, params)
    except duckdb.CatalogException:
        return LeaderboardResponse(
            players=[], total=0, page=page, per_page=per_page, total_pages=0
        )

    if not rows:
        return LeaderboardResponse(
            players=[], total=0, page=page, per_page=per_page, total_pages=0
        )

    total = int(rows[0].get("_total_count", 0))
    total_pages = max(1, math.ceil(total / per_page))

    players = [_bat_row_to_summary(row, cutoff) for row in rows]

    return LeaderboardResponse(
        players=players,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


# ── Route: GET /api/rankings/bowl ─────────────────────────────────


@router.get("/rankings/bowl", response_model=LeaderboardResponse)
async def bowling_leaderboard(
    sort: str = Query(
        "rating_current",
        description=(
            "Column to sort by. Includes rating_current, rating_overall (display "
            "ratings), overall_score (pipeline composite), score_accuracy, "
            "score_control, score_threat, career_economy, career_sr_bowl, "
            "career_dot_pct, matches, total_wickets, war_bowling, "
            "clutch_index_bowl, flat_track_index_bowl, etc."
        ),
    ),
    order: str = Query("desc", description="Sort order: asc or desc"),
    country: str | None = Query(
        None, description="Filter by country (case-insensitive)"
    ),
    archetype: str | None = Query(
        None, description="Filter by archetype (case-insensitive)"
    ),
    phase_group: str | None = Query(
        None,
        description="Filter by bowling phase group: powerplay, middle, death",
    ),
    min_innings: int | None = Query(None, ge=0, description="Minimum matches bowled"),
    provisional: bool | None = Query(
        None,
        description="True = only provisional, False = exclude provisional, None = all",
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page"),
    activity: str = Query(
        "active",
        description=(
            "Player pool: active (last match within 1y for T20I, 2y for IPL), "
            "retired, or all"
        ),
        pattern="^(active|retired|all)$",
    ),
    format: str = Query(
        DEFAULT_FORMAT,
        description="Dataset slice (e.g. mens_t20i, womens_t20i, womens_ipl).",
        pattern=_FORMAT_PATTERN,
    ),
    db=Depends(_get_store),
) -> LeaderboardResponse:
    """Return a sorted, filterable, paginated bowling leaderboard."""
    conn, fmt = db
    f = safe_fmt(fmt)

    table = f"{f}.bowl_careers"
    cutoff = activity_cutoff_date(conn, f)
    sort_col = _validate_sort(sort, BOWLING_SORT_COLUMNS, "rating_current")
    direction = "ASC" if order.lower() == "asc" else "DESC"

    where_clause, params = _build_where(
        country=country,
        archetype=archetype,
        provisional=provisional,
        min_innings=min_innings,
        phase_group=phase_group,
        activity=activity,
        cutoff=cutoff,
        provisional_col="is_provisional_bowl",
        innings_col="matches",
    )

    offset = (page - 1) * per_page

    sql = f"""
        WITH ranked AS (
            SELECT *,
                {_BOWL_RATING_SQL},
                COUNT(*) OVER () AS _total_count
            FROM {table}
            WHERE {where_clause}
        )
        SELECT * FROM ranked
        ORDER BY {sort_col} {direction} NULLS LAST
        LIMIT ? OFFSET ?
    """
    params.extend([per_page, offset])

    try:
        rows = query_all(conn, sql, params)
    except duckdb.CatalogException:
        return LeaderboardResponse(
            players=[], total=0, page=page, per_page=per_page, total_pages=0
        )

    if not rows:
        return LeaderboardResponse(
            players=[], total=0, page=page, per_page=per_page, total_pages=0
        )

    total = int(rows[0].get("_total_count", 0))
    total_pages = max(1, math.ceil(total / per_page))

    players = [_bowl_row_to_summary(row, cutoff) for row in rows]

    return LeaderboardResponse(
        players=players,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


# ── Route: GET /api/rankings/bat/distribution ─────────────────────


@router.get("/rankings/bat/distribution", response_model=LeaderboardDistributionResponse)
async def batting_distribution(
    metric: str = Query(
        "rating_current",
        description="Numeric column (same names as /api/rankings/columns/bat).",
    ),
    country: str | None = Query(
        None, description="Filter by country (case-insensitive)"
    ),
    archetype: str | None = Query(
        None, description="Filter by archetype (case-insensitive)"
    ),
    position_group: str | None = Query(
        None,
        description=(
            "Filter by batting position group: "
            "top_order, middle_order, lower_order, opener"
        ),
    ),
    modal_slot: int | None = Query(
        None,
        ge=1,
        le=11,
        description="Filter by modal batting entry position (1–11).",
    ),
    min_innings: int | None = Query(None, ge=0, description="Minimum innings played"),
    provisional: bool | None = Query(
        None,
        description="True = only provisional, False = exclude provisional, None = all",
    ),
    activity: str = Query(
        "active",
        description="Player pool: active, retired, or all",
        pattern="^(active|retired|all)$",
    ),
    format: str = Query(
        DEFAULT_FORMAT,
        description="Dataset slice (e.g. mens_t20i, womens_t20i, womens_ipl).",
        pattern=_FORMAT_PATTERN,
    ),
    ctx_entry_phase: str = Query(
        "none",
        description="Innings entry context: none, early, death.",
        pattern="^(none|early|death)$",
    ),
    ctx_knockouts_only: bool = Query(
        False,
        description="Unsupported context — returns empty distribution.",
    ),
    ctx_chase_high_rpo: bool = Query(
        False,
        description="Unsupported context — returns empty distribution.",
    ),
    db=Depends(_get_store),
) -> LeaderboardDistributionResponse:
    """Quartiles, Tukey fences, outliers, and histogram for one metric over the filtered pool."""
    conn, fmt = db
    f = safe_fmt(fmt)

    if ctx_knockouts_only or ctx_chase_high_rpo:
        return LeaderboardDistributionResponse(metric=metric, role="bat", n=0)

    value_col = _validate_sort(metric, BATTING_SORT_COLUMNS, "rating_current")
    table = _bat_table(f, ctx_entry_phase)
    cutoff = activity_cutoff_date(conn, f)

    where_clause, params = _build_where(
        country=country,
        archetype=archetype,
        provisional=provisional,
        min_innings=min_innings,
        position_group=position_group,
        modal_slot=modal_slot,
        activity=activity,
        cutoff=cutoff,
        provisional_col="is_provisional_bat",
        innings_col="innings_count",
    )

    sql = f"""
        WITH ranked AS (
            SELECT *,
                {_BAT_RATING_SQL}
            FROM {table}
            WHERE {where_clause}
        )
        SELECT batter_id, batter, {value_col} AS v
        FROM ranked
        WHERE {value_col} IS NOT NULL
    """
    try:
        rows = query_all(conn, sql, params)
    except duckdb.CatalogException:
        return LeaderboardDistributionResponse(metric=metric, role="bat", n=0)

    points: list[tuple[float, str, str]] = []
    for r in rows:
        v = safe_float(r.get("v"))
        if v is None:
            continue
        points.append(
            (float(v), safe_str(r.get("batter_id")), safe_str(r.get("batter")))
        )
    return _build_distribution_response(metric=metric, role="bat", points=points)


# ── Route: GET /api/rankings/bowl/distribution ────────────────────


@router.get("/rankings/bowl/distribution", response_model=LeaderboardDistributionResponse)
async def bowling_distribution(
    metric: str = Query(
        "career_economy",
        description="Numeric column (same names as /api/rankings/columns/bowl).",
    ),
    country: str | None = Query(
        None, description="Filter by country (case-insensitive)"
    ),
    archetype: str | None = Query(
        None, description="Filter by archetype (case-insensitive)"
    ),
    phase_group: str | None = Query(
        None,
        description="Filter by bowling phase group: powerplay, middle, death",
    ),
    min_innings: int | None = Query(None, ge=0, description="Minimum matches bowled"),
    provisional: bool | None = Query(
        None,
        description="True = only provisional, False = exclude provisional, None = all",
    ),
    activity: str = Query(
        "active",
        description="Player pool: active, retired, or all",
        pattern="^(active|retired|all)$",
    ),
    format: str = Query(
        DEFAULT_FORMAT,
        description="Dataset slice (e.g. mens_t20i, womens_t20i, womens_ipl).",
        pattern=_FORMAT_PATTERN,
    ),
    db=Depends(_get_store),
) -> LeaderboardDistributionResponse:
    """Quartiles, Tukey fences, outliers, and histogram for one bowling metric."""
    conn, fmt = db
    f = safe_fmt(fmt)
    value_col = _validate_sort(metric, BOWLING_SORT_COLUMNS, "career_economy")
    table = f"{f}.bowl_careers"
    cutoff = activity_cutoff_date(conn, f)

    where_clause, params = _build_where(
        country=country,
        archetype=archetype,
        provisional=provisional,
        min_innings=min_innings,
        phase_group=phase_group,
        activity=activity,
        cutoff=cutoff,
        provisional_col="is_provisional_bowl",
        innings_col="matches",
    )

    sql = f"""
        WITH ranked AS (
            SELECT *,
                {_BOWL_RATING_SQL}
            FROM {table}
            WHERE {where_clause}
        )
        SELECT bowler_id, bowler, {value_col} AS v
        FROM ranked
        WHERE {value_col} IS NOT NULL
    """
    try:
        rows = query_all(conn, sql, params)
    except duckdb.CatalogException:
        return LeaderboardDistributionResponse(metric=metric, role="bowl", n=0)

    points: list[tuple[float, str, str]] = []
    for r in rows:
        v = safe_float(r.get("v"))
        if v is None:
            continue
        points.append(
            (float(v), safe_str(r.get("bowler_id")), safe_str(r.get("bowler")))
        )
    return _build_distribution_response(metric=metric, role="bowl", points=points)


# ── Route: GET /api/rankings/bat/heatmap ──────────────────────────


@router.get("/rankings/bat/heatmap", response_model=LeaderboardHeatmapResponse)
async def batting_heatmap(
    country: str | None = Query(None, description="Filter by country"),
    archetype: str | None = Query(None, description="Filter by archetype"),
    position_group: str | None = Query(None, description="Batting position group"),
    modal_slot: int | None = Query(None, ge=1, le=11, description="Modal batting slot 1–11"),
    min_innings: int | None = Query(None, ge=0, description="Minimum innings"),
    provisional: bool | None = Query(None, description="Provisional filter"),
    activity: str = Query(
        "active",
        description="Player pool: active, retired, or all",
        pattern="^(active|retired|all)$",
    ),
    format: str = Query(
        DEFAULT_FORMAT,
        description="Dataset slice",
        pattern=_FORMAT_PATTERN,
    ),
    ctx_entry_phase: str = Query(
        "none",
        description="Innings entry context: none, early, death.",
        pattern="^(none|early|death)$",
    ),
    ctx_knockouts_only: bool = Query(False, description="Unsupported — returns empty."),
    ctx_chase_high_rpo: bool = Query(False, description="Unsupported — returns empty."),
    max_sample: int = Query(
        _HEATMAP_DEFAULT_SAMPLE,
        ge=50,
        le=_HEATMAP_MAX_SAMPLE,
        description="Random sample size from filtered pool for correlations.",
    ),
    min_pair_obs: int = Query(
        _HEATMAP_MIN_PAIR_OBS,
        ge=5,
        le=200,
        description="Minimum paired non-null observations for a correlation cell.",
    ),
    intensity_top: int = Query(
        20,
        ge=5,
        le=_INTENSITY_MAX_PLAYERS,
        description="Number of players in the intensity heatmap (ranked by intensity_sort).",
    ),
    intensity_sort: str = Query(
        "rating_current",
        description="Column to rank players by for the intensity block.",
    ),
    intensity_metrics: str | None = Query(
        None,
        description="Comma-separated metrics for intensity columns (max 10).",
    ),
    db=Depends(_get_store),
) -> LeaderboardHeatmapResponse:
    """Pearson correlation matrix + player×metric intensity (0–1 per column) on a random sample."""
    conn, fmt = db
    f = safe_fmt(fmt)

    if ctx_knockouts_only or ctx_chase_high_rpo:
        return LeaderboardHeatmapResponse(role="bat", n_players=0)

    table = _bat_table(f, ctx_entry_phase)
    cutoff = activity_cutoff_date(conn, f)
    where_clause, params = _build_where(
        country=country,
        archetype=archetype,
        provisional=provisional,
        min_innings=min_innings,
        position_group=position_group,
        modal_slot=modal_slot,
        activity=activity,
        cutoff=cutoff,
        provisional_col="is_provisional_bat",
        innings_col="innings_count",
    )
    sql = f"""
        WITH ranked AS (
            SELECT *,
                {_BAT_RATING_SQL}
            FROM {table}
            WHERE {where_clause}
        )
        SELECT * FROM ranked
        ORDER BY random()
        LIMIT ?
    """
    params.append(max_sample)
    try:
        rows = query_all(conn, sql, params)
    except duckdb.CatalogException:
        return LeaderboardHeatmapResponse(role="bat", n_players=0)

    return _build_heatmap_response(
        role="bat",
        rows=rows,
        allow=BATTING_SORT_COLUMNS,
        id_key="batter_id",
        name_key="batter",
        min_pair_obs=min_pair_obs,
        intensity_top=intensity_top,
        intensity_sort=intensity_sort,
        intensity_metrics=intensity_metrics,
        defaults_metrics=_BAT_INTENSITY_DEFAULT_METRICS,
    )


# ── Route: GET /api/rankings/bowl/heatmap ─────────────────────────


@router.get("/rankings/bowl/heatmap", response_model=LeaderboardHeatmapResponse)
async def bowling_heatmap(
    country: str | None = Query(None),
    archetype: str | None = Query(None),
    phase_group: str | None = Query(None, description="Bowling phase group"),
    min_innings: int | None = Query(None, ge=0, description="Minimum matches bowled"),
    provisional: bool | None = Query(None),
    activity: str = Query(
        "active",
        pattern="^(active|retired|all)$",
    ),
    format: str = Query(DEFAULT_FORMAT, pattern=_FORMAT_PATTERN),
    max_sample: int = Query(
        _HEATMAP_DEFAULT_SAMPLE,
        ge=50,
        le=_HEATMAP_MAX_SAMPLE,
    ),
    min_pair_obs: int = Query(
        _HEATMAP_MIN_PAIR_OBS,
        ge=5,
        le=200,
    ),
    intensity_top: int = Query(20, ge=5, le=_INTENSITY_MAX_PLAYERS),
    intensity_sort: str = Query("rating_current"),
    intensity_metrics: str | None = Query(None),
    db=Depends(_get_store),
) -> LeaderboardHeatmapResponse:
    conn, fmt = db
    f = safe_fmt(fmt)
    table = f"{f}.bowl_careers"
    cutoff = activity_cutoff_date(conn, f)
    where_clause, params = _build_where(
        country=country,
        archetype=archetype,
        provisional=provisional,
        min_innings=min_innings,
        phase_group=phase_group,
        activity=activity,
        cutoff=cutoff,
        provisional_col="is_provisional_bowl",
        innings_col="matches",
    )
    sql = f"""
        WITH ranked AS (
            SELECT *,
                {_BOWL_RATING_SQL}
            FROM {table}
            WHERE {where_clause}
        )
        SELECT * FROM ranked
        ORDER BY random()
        LIMIT ?
    """
    params.append(max_sample)
    try:
        rows = query_all(conn, sql, params)
    except duckdb.CatalogException:
        return LeaderboardHeatmapResponse(role="bowl", n_players=0)

    return _build_heatmap_response(
        role="bowl",
        rows=rows,
        allow=BOWLING_SORT_COLUMNS,
        id_key="bowler_id",
        name_key="bowler",
        min_pair_obs=min_pair_obs,
        intensity_top=intensity_top,
        intensity_sort=intensity_sort,
        intensity_metrics=intensity_metrics,
        defaults_metrics=_BOWL_INTENSITY_DEFAULT_METRICS,
    )


# ── Route: GET /api/rankings/columns/bat ──────────────────────────


@router.get("/rankings/columns/bat", response_model=list[str])
async def batting_sort_columns() -> list[str]:
    """Return the list of valid sort columns for the batting leaderboard."""
    return sorted(BATTING_SORT_COLUMNS)


# ── Route: GET /api/rankings/columns/bowl ─────────────────────────


@router.get("/rankings/columns/bowl", response_model=list[str])
async def bowling_sort_columns() -> list[str]:
    """Return the list of valid sort columns for the bowling leaderboard."""
    return sorted(BOWLING_SORT_COLUMNS)


# ── Route: GET /api/rankings/top ──────────────────────────────────


@router.get("/rankings/top")
async def top_players(
    role: str = Query("bat", description="Role: bat or bowl"),
    metric: str = Query("overall_score", description="Metric to rank by"),
    limit: int = Query(5, ge=1, le=50, description="Number of top players"),
    provisional: bool | None = Query(
        None,
        description=(
            "True = only provisional, False = exclude provisional, "
            "omit = all (default for dashboard cards)"
        ),
    ),
    min_innings: int | None = Query(None, description="Minimum innings/matches"),
    activity: str = Query(
        "active",
        description="active, retired, or all (same recency rules as main leaderboard)",
        pattern="^(active|retired|all)$",
    ),
    format: str = Query(
        DEFAULT_FORMAT,
        description="Dataset slice (e.g. mens_t20i, womens_t20i, womens_ipl).",
        pattern=_FORMAT_PATTERN,
    ),
    db=Depends(_get_store),
) -> list[PlayerSummary]:
    """Quick endpoint to get top-N players for a specific metric."""
    conn, fmt = db
    f = safe_fmt(fmt)

    cutoff = activity_cutoff_date(conn, f)

    if role == "bowl":
        table = f"{f}.bowl_careers"
        sort_col = _validate_sort(metric, BOWLING_SORT_COLUMNS, "overall_score")
        rating_sql = _BOWL_RATING_SQL
        prov_col = "is_provisional_bowl"
        inn_col = "matches"

        where_clause, params = _build_where(
            provisional=provisional,
            min_innings=min_innings,
            activity=activity,
            cutoff=cutoff,
            provisional_col=prov_col,
            innings_col=inn_col,
        )

        sql = f"""
            WITH ranked AS (
                SELECT *,
                    {rating_sql}
                FROM {table}
                WHERE {where_clause}
            )
            SELECT * FROM ranked
            ORDER BY {sort_col} DESC NULLS LAST
            LIMIT ?
        """
        params.append(limit)

        try:
            rows = query_all(conn, sql, params)
        except duckdb.CatalogException:
            return []

        return [_bowl_row_to_summary(row, cutoff) for row in rows]

    else:
        table = f"{f}.bat_careers"
        sort_col = _validate_sort(metric, BATTING_SORT_COLUMNS, "overall_score")
        rating_sql = _BAT_RATING_SQL
        prov_col = "is_provisional_bat"
        inn_col = "innings_count"

        where_clause, params = _build_where(
            provisional=provisional,
            min_innings=min_innings,
            activity=activity,
            cutoff=cutoff,
            provisional_col=prov_col,
            innings_col=inn_col,
        )

        sql = f"""
            WITH ranked AS (
                SELECT *,
                    {rating_sql}
                FROM {table}
                WHERE {where_clause}
            )
            SELECT * FROM ranked
            ORDER BY {sort_col} DESC NULLS LAST
            LIMIT ?
        """
        params.append(limit)

        try:
            rows = query_all(conn, sql, params)
        except duckdb.CatalogException:
            return []

        return [_bat_row_to_summary(row, cutoff) for row in rows]
