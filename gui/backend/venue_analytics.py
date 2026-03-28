"""
Venue analytics — aggregations for /api/venues/profile, trends, teams, similar, matches, performances.

Keeps heavy pandas logic out of the FastAPI router.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from match_impact import combined_row_for_player


def attach_global_venue_difficulty_index(venue_df: pd.DataFrame) -> pd.DataFrame:
    """Add ``venue_difficulty_index`` (0–100, higher = harder) from ``venue_difficulty``.

    Percentile rank across all rows in *venue_df* (same ordering as the z-style
    ``venue_difficulty``). Recomputed here so API/static export stay aligned with
    the underlying metric even when parquet omits the index column.
    """
    out = venue_df.copy()
    if out.empty or "venue_difficulty" not in out.columns:
        out["venue_difficulty_index"] = np.nan
        return out
    s = pd.to_numeric(out["venue_difficulty"], errors="coerce")
    out["venue_difficulty_index"] = (
        s.rank(method="average", pct=True, ascending=True) * 100.0
    ).where(s.notna())
    return out


# ── Small helpers (mirror venues router) ──────────────────────────


def _sf(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


def _si(v: Any) -> int:
    if v is None:
        return 0
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return 0
        return int(f)
    except (TypeError, ValueError):
        return 0


def _ss(v: Any, default: str = "") -> str:
    if v is None:
        return default
    s = str(v)
    if s in ("nan", "NaN", "None", "<NA>", "NaT"):
        return default
    return s


def pick_venue_col(df: pd.DataFrame) -> str | None:
    for col_name in ("venue", "ground", "stadium"):
        if col_name in df.columns:
            return col_name
    return None


def resolve_venue_row(store: Any, venue_query: str, exact: bool) -> tuple[pd.Series | None, str]:
    """
    Resolve user query to a row in store.venue.

    Returns (row_or_none, canonical_venue_name).
    """
    q = venue_query.strip()
    ql = q.lower()
    if store.venue.empty or "venue" not in store.venue.columns:
        return None, q

    vdf = store.venue
    if exact:
        mask = vdf["venue"].astype(str).str.lower() == ql
        sub = vdf.loc[mask]
        if not sub.empty:
            return sub.iloc[0], _ss(sub.iloc[0]["venue"], q)
        return None, q

    mask = vdf["venue"].astype(str).str.lower() == ql
    sub = vdf.loc[mask]
    if not sub.empty:
        return sub.iloc[0], _ss(sub.iloc[0]["venue"], q)

    mask_p = vdf["venue"].astype(str).str.lower().str.contains(ql, na=False)
    sub = vdf.loc[mask_p]
    if not sub.empty:
        return sub.iloc[0], _ss(sub.iloc[0]["venue"], q)

    return None, q


def filter_bat_by_venue(
    bat: pd.DataFrame,
    venue_canonical: str,
    *,
    exact: bool,
) -> pd.DataFrame:
    vc = pick_venue_col(bat)
    if vc is None:
        return pd.DataFrame()
    vlow = venue_canonical.lower()
    if exact:
        mask = bat[vc].astype(str).str.lower() == vlow
    else:
        mask = bat[vc].astype(str).str.lower().str.contains(vlow, na=False)
    return bat.loc[mask]


def filter_bowl_by_venue(
    bowl: pd.DataFrame,
    venue_canonical: str,
    *,
    exact: bool,
) -> pd.DataFrame:
    return filter_bat_by_venue(bowl, venue_canonical, exact=exact)


def _phase_bat_aggregate(bi: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for phase in ("powerplay", "middle", "death"):
        rb = f"{phase}_runs"
        bb = f"{phase}_balls"
        if rb not in bi.columns or bb not in bi.columns:
            out[phase] = {"sr": None, "balls": 0, "runs": 0}
            continue
        runs = pd.to_numeric(bi[rb], errors="coerce").fillna(0).sum()
        balls = pd.to_numeric(bi[bb], errors="coerce").fillna(0).sum()
        sr = _sf((runs / balls * 100.0) if balls > 0 else None)
        out[phase] = {"sr": sr, "balls": int(balls), "runs": int(runs)}
    return out


def _phase_bat_vs_par_mean(bi: pd.DataFrame) -> dict[str, float | None]:
    """Mean of (phase_sr / phase_par_sr) where both valid."""
    res: dict[str, float | None] = {}
    par_map = {
        "powerplay": ("powerplay_sr", "pp_par_sr"),
        "middle": ("middle_sr", "middle_par_sr"),
        "death": ("death_sr", "death_par_sr"),
    }
    for phase, (sr_c, par_c) in par_map.items():
        if sr_c not in bi.columns or par_c not in bi.columns:
            res[phase] = None
            continue
        sr = pd.to_numeric(bi[sr_c], errors="coerce")
        par = pd.to_numeric(bi[par_c], errors="coerce").replace(0, np.nan)
        ratio = sr / par
        ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()
        res[phase] = _sf(ratio.mean()) if not ratio.empty else None
    return res


def _phase_bowl_aggregate(bs: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for phase in ("powerplay", "middle", "death"):
        lb = f"{phase}_legal_balls"
        rn = f"{phase}_runs"
        if lb not in bs.columns or rn not in bs.columns:
            out[phase] = {"economy": None, "dot_pct": None, "balls": 0}
            continue
        balls = pd.to_numeric(bs[lb], errors="coerce").fillna(0).sum()
        runs = pd.to_numeric(bs[rn], errors="coerce").fillna(0).sum()
        overs = balls / 6.0
        econ = _sf(runs / overs) if overs > 0 else None
        dt = f"{phase}_dots"
        dot_pct = None
        if dt in bs.columns and balls > 0:
            dots = pd.to_numeric(bs[dt], errors="coerce").fillna(0).sum()
            dot_pct = _sf(dots / balls)
        out[phase] = {"economy": econ, "dot_pct": dot_pct, "balls": int(balls)}
    return out


def _percentile_rank(series: pd.Series, value: float | None) -> float | None:
    if value is None or series.empty:
        return None
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return round(float((s < value).mean() * 100.0), 2)


def _chase_defend_from_bat(bi: pd.DataFrame) -> dict[str, Any]:
    if bi.empty or "match_id" not in bi.columns:
        return {}
    cols = [c for c in ("match_id", "innings_num", "batting_team", "total_runs", "winner") if c in bi.columns]
    if len(cols) < 4:
        return {}
    sub = bi[cols].drop_duplicates(subset=["match_id", "innings_num", "batting_team"])
    inn1_scores: list[float] = []
    inn2_scores: list[float] = []
    bat_first_wins = 0
    bat_second_wins = 0
    n_decided = 0

    for _mid, g in sub.groupby("match_id"):
        g = g.sort_values("innings_num")
        if g.empty:
            continue
        inn_min = int(pd.to_numeric(g["innings_num"], errors="coerce").min())
        inn_max = int(pd.to_numeric(g["innings_num"], errors="coerce").max())
        g1 = g.loc[pd.to_numeric(g["innings_num"], errors="coerce") == inn_min]
        r1 = g1.iloc[0]
        score1 = float(pd.to_numeric(r1.get("total_runs"), errors="coerce") or 0)
        inn1_scores.append(score1)
        t_first = str(r1.get("batting_team", "")).strip()
        t_second = ""
        if inn_max != inn_min and len(g) >= 2:
            g2 = g.loc[pd.to_numeric(g["innings_num"], errors="coerce") == inn_max]
            if not g2.empty:
                r2 = g2.iloc[0]
                score2 = float(pd.to_numeric(r2.get("total_runs"), errors="coerce") or 0)
                inn2_scores.append(score2)
                t_second = str(r2.get("batting_team", "")).strip()

        w = r1.get("winner") if "winner" in r1.index else None
        if w is None or (isinstance(w, float) and math.isnan(w)) or str(w).strip() == "":
            continue
        w = str(w).strip()
        n_decided += 1
        if w == t_first:
            bat_first_wins += 1
        elif t_second and w == t_second:
            bat_second_wins += 1

    return {
        "avg_first_innings_score": _sf(np.mean(inn1_scores) if inn1_scores else None),
        "avg_second_innings_score": _sf(np.mean(inn2_scores) if inn2_scores else None),
        "matches_with_result": n_decided,
        "wins_batting_first": bat_first_wins,
        "wins_chasing": bat_second_wins,
        "win_pct_batting_first": _sf((bat_first_wins / n_decided * 100) if n_decided else None),
    }


def build_venue_profile(
    store: Any,
    venue_query: str,
    *,
    exact: bool = False,
    min_venues_for_field: int = 10,
) -> dict[str, Any] | None:
    row, canonical = resolve_venue_row(store, venue_query, exact)
    if row is None:
        return None

    bi = filter_bat_by_venue(store.bat_innings, canonical, exact=exact)
    bs = filter_bowl_by_venue(store.bowl_spells, canonical, exact=exact)

    n_inn = len(bi)
    n_balls = int(pd.to_numeric(bi.get("balls_faced"), errors="coerce").fillna(0).sum()) if not bi.empty and "balls_faced" in bi.columns else 0
    n_matches = bi["match_id"].nunique() if not bi.empty and "match_id" in bi.columns else 0

    vdf = store.venue
    mask_m = (
        pd.to_numeric(vdf["venue_matches"], errors="coerce").fillna(0) >= min_venues_for_field
        if "venue_matches" in vdf.columns
        else pd.Series(True, index=vdf.index)
    )
    ref = vdf.loc[mask_m]

    def pct(col: str, val: float | None) -> float | None:
        if val is None or col not in ref.columns:
            return None
        return _percentile_rank(ref[col], val)

    avg_par = _sf(row.get("venue_avg_par_sr"))
    boundary = _sf(row.get("venue_avg_boundary_rate"))
    dotp = _sf(row.get("venue_avg_dot_pct"))
    diff_z = _sf(row.get("venue_difficulty"))
    vdf_idx = attach_global_venue_difficulty_index(store.venue)
    m_idx = vdf_idx["venue"].astype(str).str.lower() == canonical.lower()
    diff_display = (
        _sf(float(vdf_idx.loc[m_idx, "venue_difficulty_index"].iloc[0]))
        if m_idx.any()
        else None
    )

    phase_loc = _phase_bat_aggregate(bi)
    phase_loc_vs_par = _phase_bat_vs_par_mean(bi)
    phase_bowl = _phase_bowl_aggregate(bs)

    # Field: all innings bat (heavy but one-off per request)
    all_bi = store.bat_innings
    phase_field = _phase_bat_aggregate(all_bi) if not all_bi.empty else {}
    # Median venue phase SR: group by venue
    median_phase: dict[str, float | None] = {}
    vc = pick_venue_col(all_bi)
    if vc is not None and not all_bi.empty:
        rows_med = []
        for vname, g in all_bi.groupby(vc, dropna=True):
            agg = _phase_bat_aggregate(g)
            rows_med.append({ph: agg[ph]["sr"] for ph in ("powerplay", "middle", "death")})
        if rows_med:
            med_df = pd.DataFrame(rows_med)
            for ph in ("powerplay", "middle", "death"):
                s = pd.to_numeric(med_df[ph], errors="coerce").dropna()
                median_phase[ph] = _sf(s.median()) if not s.empty else None

    chase = _chase_defend_from_bat(bi)

    phase_compare = {}
    for ph in ("powerplay", "middle", "death"):
        loc_sr = phase_loc.get(ph, {}).get("sr")
        fld_sr = phase_field.get(ph, {}).get("sr")
        med_sr = median_phase.get(ph)
        phase_compare[ph] = {
            "venue_sr": loc_sr,
            "format_mean_sr": fld_sr,
            "median_venue_sr": med_sr,
            "vs_par_ratio_mean": phase_loc_vs_par.get(ph),
        }

    return {
        "venue": canonical,
        "matches": _si(row.get("venue_matches")),
        "batting_innings": n_inn,
        "balls_faced_total": n_balls,
        "matches_in_slice": int(n_matches),
        "small_sample": n_matches < 10,
        "avg_par_sr": avg_par,
        "boundary_rate": boundary,
        "dot_pct": dotp,
        "difficulty_score": diff_display,
        "par_sr_std": _sf(row.get("venue_par_std")),
        "difficulty_raw": _sf(row.get("venue_difficulty_raw")),
        "vs_world": {
            "avg_par_sr_percentile": pct("venue_avg_par_sr", avg_par),
            "boundary_rate_percentile": pct("venue_avg_boundary_rate", boundary),
            "dot_pct_percentile": pct("venue_avg_dot_pct", dotp),
            "difficulty_percentile": pct("venue_difficulty", diff_z),
        },
        "chase_defend": chase,
        "phases_batting": phase_compare,
        "phases_bowling": {
            ph: {
                "venue": phase_bowl.get(ph, {}),
                "note": "Economy = runs per over in phase; dot_pct when available.",
            }
            for ph in ("powerplay", "middle", "death")
        },
    }


def _venue_trends_by_year(sub: pd.DataFrame) -> list[dict[str, Any]]:
    """One point per calendar year (legacy)."""
    bi = sub.copy()
    bi["_period"] = bi["_dt"].dt.year.astype(str)
    series: list[dict[str, Any]] = []
    for period, g in bi.dropna(subset=["_period"]).groupby("_period", sort=True):
        mpar = None
        if "match_par_sr" in g.columns:
            mpar = _sf(pd.to_numeric(g["match_par_sr"], errors="coerce").mean())
        mteam = None
        if "total_runs" in g.columns:
            mteam = _sf(pd.to_numeric(g["total_runs"], errors="coerce").mean())
        n_m = g["match_id"].nunique() if "match_id" in g.columns else 0
        series.append(
            {
                "period": str(period),
                "matches": int(n_m),
                "mean_team_innings_score": mteam,
                "mean_match_par_sr": mpar,
            }
        )
    return series


def _venue_trends_rolling_matches(
    sub: pd.DataFrame,
    *,
    window: int = 3,
) -> list[dict[str, Any]]:
    """
    Chronological matches at the venue; each point is a rolling average over the
    last ``window`` matches. Per-match values are the mean of team innings at
    this venue in that match (typically two rows).
    """
    if "match_id" not in sub.columns or sub.empty:
        return []

    parts: list[dict[str, Any]] = []
    for mid, g in sub.groupby("match_id", sort=False):
        dmin = g["_dt"].min()
        mteam = None
        if "total_runs" in g.columns:
            mteam = _sf(pd.to_numeric(g["total_runs"], errors="coerce").mean())
        mpar = None
        if "match_par_sr" in g.columns:
            mpar = _sf(pd.to_numeric(g["match_par_sr"], errors="coerce").mean())
        parts.append(
            {
                "match_id": mid,
                "_dt": dmin,
                "avg_innings_runs": mteam,
                "avg_match_par_sr": mpar,
            }
        )

    mdf = pd.DataFrame(parts)
    if mdf.empty:
        return []

    mdf = mdf.sort_values("_dt", kind="mergesort").reset_index(drop=True)
    runs = pd.to_numeric(mdf["avg_innings_runs"], errors="coerce")
    par = pd.to_numeric(mdf["avg_match_par_sr"], errors="coerce")
    mdf["roll_runs"] = runs.rolling(window, min_periods=window).mean()
    mdf["roll_par"] = par.rolling(window, min_periods=window).mean()

    series: list[dict[str, Any]] = []
    for _, row in mdf.iterrows():
        rr = row["roll_runs"]
        rp = row["roll_par"]
        if pd.isna(rr) and pd.isna(rp):
            continue
        ts = row["_dt"]
        if hasattr(ts, "strftime"):
            period = ts.strftime("%Y-%m-%d")
        else:
            period = str(ts)[:10]
        series.append(
            {
                "period": period,
                "matches": int(window),
                "mean_team_innings_score": _sf(rr) if pd.notna(rr) else None,
                "mean_match_par_sr": _sf(rp) if pd.notna(rp) else None,
            }
        )

    return series


def build_venue_trends(
    store: Any,
    venue_query: str,
    *,
    exact: bool = False,
    bucket: str = "rolling_3_match",
) -> dict[str, Any] | None:
    _, canonical = resolve_venue_row(store, venue_query, exact)
    bi = filter_bat_by_venue(store.bat_innings, canonical, exact=exact)
    if bi.empty or "date" not in bi.columns:
        return {"venue": canonical, "bucket": bucket, "series": []}

    bi = bi.copy()
    bi["_dt"] = pd.to_datetime(bi["date"], errors="coerce")
    cols = ["match_id", "innings_num", "batting_team", "total_runs", "match_par_sr", "_dt"]
    use = [c for c in cols if c in bi.columns]
    sub = bi[use].drop_duplicates(subset=["match_id", "innings_num", "batting_team"])
    sub = sub.dropna(subset=["_dt", "match_id"])

    if bucket in ("year", "season"):
        series = _venue_trends_by_year(sub)
    else:
        series = _venue_trends_rolling_matches(sub, window=3)

    out_bucket = bucket if bucket in ("year", "season") else "rolling_3_match"
    return {"venue": canonical, "bucket": out_bucket, "series": series}


def build_venue_teams(
    store: Any,
    venue_query: str,
    *,
    exact: bool = False,
    min_matches: int = 2,
    sort: str = "win_pct",
    order: str = "desc",
    page: int = 1,
    per_page: int = 25,
) -> dict[str, Any] | None:
    _, canonical = resolve_venue_row(store, venue_query, exact)
    if canonical is None:
        return None
    bi = filter_bat_by_venue(store.bat_innings, canonical, exact=exact)
    if bi.empty or "winner" not in bi.columns:
        return {
            "venue": canonical,
            "teams": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    cols = ["match_id", "innings_num", "batting_team", "winner"]
    sub = bi[[c for c in cols if c in bi.columns]].drop_duplicates(
        subset=["match_id", "innings_num", "batting_team"]
    )
    teams: set[str] = set()
    for _, r in sub.iterrows():
        teams.add(_ss(r.get("batting_team")))

    rows = []
    for team in teams:
        if not team:
            continue
        mids = sub.loc[sub["batting_team"] == team, "match_id"].unique()
        played = len(mids)
        if played < min_matches:
            continue
        wins = 0
        for mid in mids:
            w = sub.loc[sub["match_id"] == mid, "winner"].iloc[0]
            if _ss(w) == team:
                wins += 1
        losses = played - wins
        win_pct = (wins / played * 100.0) if played else 0.0
        rows.append(
            {
                "team": team,
                "matches": played,
                "wins": wins,
                "losses": losses,
                "win_pct": round(win_pct, 2),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return {
            "venue": canonical,
            "teams": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    sort_col = sort if sort in df.columns else "win_pct"
    asc = order.lower() == "asc"
    df = df.sort_values(sort_col, ascending=asc, na_position="last")
    total = len(df)
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    chunk = df.iloc[start : start + per_page]
    return {
        "venue": canonical,
        "teams": chunk.to_dict(orient="records"),
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


def build_venue_similar(
    store: Any,
    venue_query: str,
    *,
    exact: bool = False,
    k: int = 8,
) -> dict[str, Any] | None:
    row, canonical = resolve_venue_row(store, venue_query, exact)
    if row is None or store.venue.empty:
        return None

    vdf = attach_global_venue_difficulty_index(store.venue.copy())
    feat_cols = [
        c
        for c in (
            "venue_avg_par_sr",
            "venue_avg_boundary_rate",
            "venue_avg_dot_pct",
            "venue_difficulty",
        )
        if c in vdf.columns
    ]
    if len(feat_cols) < 2:
        return {"venue": canonical, "similar": []}

    M = vdf[feat_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy(dtype=float)
    mu = M.mean(axis=0)
    sig = M.std(axis=0)
    sig = np.where(sig == 0, 1.0, sig)
    Mz = (M - mu) / sig

    i0 = None
    for pos, (_, r) in enumerate(vdf.iterrows()):
        if _ss(r.get("venue")).lower() == canonical.lower():
            i0 = pos
            break
    if i0 is None:
        return {"venue": canonical, "similar": []}
    v0 = Mz[i0]

    sims = []
    for i in range(len(vdf)):
        if i == i0:
            continue
        v = Mz[i, :]
        denom = (np.linalg.norm(v0) * np.linalg.norm(v)) or 1.0
        cos = float(np.dot(v0, v) / denom)
        sims.append((cos, i))
    sims.sort(key=lambda x: -x[0])
    out = []
    for cos, i in sims[:k]:
        r = vdf.iloc[i]
        out.append(
            {
                "venue": _ss(r.get("venue")),
                "similarity": round(cos, 4),
                "matches": _si(r.get("venue_matches")),
                "avg_par_sr": _sf(r.get("venue_avg_par_sr")),
                "difficulty_score": _sf(r.get("venue_difficulty_index")),
            }
        )

    return {"venue": canonical, "similar": out}


def build_venue_matches(
    store: Any,
    venue_query: str,
    *,
    exact: bool = False,
    page: int = 1,
    per_page: int = 25,
) -> dict[str, Any] | None:
    _, canonical = resolve_venue_row(store, venue_query, exact)
    if canonical is None:
        return None
    bi = filter_bat_by_venue(store.bat_innings, canonical, exact=exact)
    if bi.empty:
        return {
            "venue": canonical,
            "matches": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    cols = [
        "match_id",
        "date",
        "event_name",
        "winner",
        "innings_num",
        "batting_team",
        "total_runs",
    ]
    use = [c for c in cols if c in bi.columns]
    sub = bi[use].drop_duplicates(subset=["match_id", "innings_num", "batting_team"])
    # one row per match: collapse
    matches = []
    for mid, g in sub.groupby("match_id", sort=False):
        g = g.sort_values("innings_num") if "innings_num" in g.columns else g
        d0 = g.iloc[0]
        teams = list(dict.fromkeys([_ss(r.get("batting_team")) for _, r in g.iterrows()]))
        scores = []
        for _, r in g.iterrows():
            scores.append(_si(r.get("total_runs")))
        matches.append(
            {
                "match_id": _ss(mid),
                "date": d0["date"].isoformat() if hasattr(d0.get("date"), "isoformat") else _ss(d0.get("date")),
                "event_name": _ss(d0.get("event_name")) or None,
                "winner": _ss(d0.get("winner")) or None,
                "teams": teams,
                "innings_scores": scores,
            }
        )

    df = pd.DataFrame(matches)
    if "date" in df.columns:
        df["_sort"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values("_sort", ascending=False, na_position="last")
    total = len(df)
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    chunk = df.iloc[start : start + per_page]
    recs = chunk.drop(columns=["_sort"], errors="ignore").to_dict(orient="records")
    return {
        "venue": canonical,
        "matches": recs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


def _load_scorecard_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def build_venue_performances(
    store: Any,
    venue_query: str,
    *,
    exact: bool = False,
    role: str = "bat",
    sort: str = "bat_impact",
    order: str = "desc",
    page: int = 1,
    per_page: int = 25,
    min_balls: int = 5,
) -> dict[str, Any] | None:
    """
    Top performances at a venue using the same match-impact rules as scorecards
    and GET /api/scorecards/player/{id}/match-impact (combined_row_for_player).
    """
    _, canonical = resolve_venue_row(store, venue_query, exact)
    if canonical is None:
        return None

    out_dir = getattr(store, "output_dir", None)
    sc_dir = Path(out_dir) / "scorecards" if out_dir else None
    sc_cache: dict[str, dict[str, Any] | None] = {}

    def _sc(mid: str) -> dict[str, Any] | None:
        if mid not in sc_cache:
            p = (sc_dir / f"{mid}.json") if sc_dir else None
            sc_cache[mid] = _load_scorecard_json(p) if p and p.is_file() else None
        return sc_cache[mid]

    rows: list[dict[str, Any]] = []

    if role == "bowl":
        df = filter_bowl_by_venue(store.bowl_spells, canonical, exact=exact)
        if df.empty:
            return {
                "venue": canonical,
                "role": "bowl",
                "sort": sort,
                "performances": [],
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
            }
        mb = max(min_balls, 6)
        if "legal_balls" in df.columns:
            df = df.loc[pd.to_numeric(df["legal_balls"], errors="coerce").fillna(0) >= mb]
        if df.empty:
            return {
                "venue": canonical,
                "role": "bowl",
                "sort": sort,
                "performances": [],
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
            }
        df = df.sort_values("wickets", ascending=False, na_position="last")
        df = df.drop_duplicates(subset=["match_id", "bowler_id"], keep="first")

        for _, r in df.iterrows():
            mid = _ss(r.get("match_id"))
            pid = _ss(r.get("bowler_id"))
            if not mid or not pid:
                continue
            sc = _sc(mid)
            if sc is None:
                continue
            crow = combined_row_for_player(sc, pid)
            if crow is None:
                continue
            d = r.get("date")
            date_out = d.isoformat() if d is not None and hasattr(d, "isoformat") else _ss(d)
            meta = sc.get("meta") or {}
            rows.append(
                {
                    "player_id": pid,
                    "player_name": _ss(r.get("bowler")),
                    "match_id": mid,
                    "date": date_out,
                    "event_name": _ss(r.get("event_name")) or _ss(meta.get("event_name")) or None,
                    "venue": _ss(meta.get("venue")) or None,
                    "bowling_team": _ss(r.get("bowling_team")) or None,
                    "opposition": _ss(r.get("batting_team")) or None,
                    "wickets": _si(crow.get("bowl_wickets")),
                    "runs_conceded": _si(crow.get("bowl_runs_conceded")),
                    "legal_balls": _si(crow.get("bowl_balls")),
                    "economy": _sf(r.get("economy")),
                    "acc_economy_vs_par": _sf(r.get("acc_economy_vs_par")),
                    "bat_impact": _sf(crow.get("bat_impact")),
                    "bowl_impact": _sf(crow.get("bowl_impact")),
                    "total_impact": _sf(crow.get("total_impact")),
                    "bat_runs": _si(crow.get("bat_runs")),
                    "bat_balls": _si(crow.get("bat_balls")),
                }
            )
    else:
        df = filter_bat_by_venue(store.bat_innings, canonical, exact=exact)
        if df.empty:
            return {
                "venue": canonical,
                "role": "bat",
                "sort": sort,
                "performances": [],
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
            }
        if "balls_faced" in df.columns:
            df = df.loc[pd.to_numeric(df["balls_faced"], errors="coerce").fillna(0) >= min_balls]
        if df.empty:
            return {
                "venue": canonical,
                "role": "bat",
                "sort": sort,
                "performances": [],
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
            }
        df = df.sort_values("runs", ascending=False, na_position="last")
        df = df.drop_duplicates(subset=["match_id", "batter_id"], keep="first")

        for _, r in df.iterrows():
            mid = _ss(r.get("match_id"))
            pid = _ss(r.get("batter_id"))
            if not mid or not pid:
                continue
            sc = _sc(mid)
            if sc is None:
                continue
            crow = combined_row_for_player(sc, pid)
            if crow is None:
                continue
            meta = sc.get("meta") or {}
            d = r.get("date")
            date_out = d.isoformat() if d is not None and hasattr(d, "isoformat") else _ss(d)
            rows.append(
                {
                    "player_id": pid,
                    "player_name": _ss(r.get("batter")),
                    "match_id": mid,
                    "date": date_out,
                    "event_name": _ss(r.get("event_name")) or _ss(meta.get("event_name")) or None,
                    "venue": _ss(meta.get("venue")) or None,
                    "batting_team": _ss(r.get("batting_team")) or None,
                    "opposition": _ss(r.get("bowling_team")) or None,
                    "runs": _si(crow.get("bat_runs")),
                    "balls_faced": _si(crow.get("bat_balls")),
                    "sr": _sf(r.get("sr")),
                    "acc_leveraged_rva": _sf(r.get("acc_leveraged_rva")),
                    "acc_runs_above_expected": _sf(r.get("acc_runs_above_expected")),
                    "acc_overall_sr": _sf(r.get("acc_overall_sr")),
                    "team_innings_total": _si(r.get("total_runs")),
                    "match_par_sr": _sf(r.get("match_par_sr")),
                    "bat_impact": _sf(crow.get("bat_impact")),
                    "bowl_impact": _sf(crow.get("bowl_impact")),
                    "total_impact": _sf(crow.get("total_impact")),
                    "bat_runs": _si(crow.get("bat_runs")),
                    "bat_balls": _si(crow.get("bat_balls")),
                    "bowl_wickets": _si(crow.get("bowl_wickets")),
                    "bowl_runs_conceded": _si(crow.get("bowl_runs_conceded")),
                    "bowl_balls": _si(crow.get("bowl_balls")),
                }
            )

    out_df = pd.DataFrame(rows)
    if out_df.empty:
        return {
            "venue": canonical,
            "role": role,
            "sort": sort,
            "performances": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    sort_key = sort.strip()
    if role == "bat":
        legacy = {
            "acc_impact": "bat_impact",
            "impact": "bat_impact",
        }
        sort_key = legacy.get(sort_key, sort_key)
        if sort_key not in out_df.columns:
            sort_key = "bat_impact"
    else:
        legacy = {
            "acc_impact": "bowl_impact",
            "impact": "bowl_impact",
        }
        sort_key = legacy.get(sort_key, sort_key)
        if sort_key not in out_df.columns:
            sort_key = "bowl_impact"

    asc = order.lower() == "asc"
    out_df = out_df.sort_values(sort_key, ascending=asc, na_position="last")
    total = len(out_df)
    total_pages = math.ceil(total / per_page) if total else 0
    start = (page - 1) * per_page
    page_df = out_df.iloc[start : start + per_page]
    perf = page_df.to_dict(orient="records")

    return {
        "venue": canonical,
        "role": role,
        "sort": sort_key,
        "performances": perf,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }
