"""Profile twins: style-first, format-specific, tier-aware neighbour search.

Impact metrics (WAR, RAE, WPA, pressure) are a filter and a display column.
Distance runs over how the player produced the runs, not how many.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from cricwarehouse.app.catalog import _attach_wtc, _jsonable
from cricwarehouse.competitions import T20_METRICS
from cricwarehouse.teams import POOL_LABELS, default_pool, parse_comps, wtc_match_sql

# Cricsheet ball-by-ball begins here for the mixed formats. T20 competitions
# in this warehouse are complete; men's Tests and ODIs are not.
TIER_WALL = {
    "test": "2001-12-19",
    "odi": "2002-06-27",
}

T20_PHASE = (6, 15)
ODI_PHASE = (10, 40)
ODI_SQUEEZE = (15, 35)

# Feature catalogue. `tier` is "card" (scorecard) or "bbb" (ball-by-ball).
# Distance uses only features both players actually have.
FEATURES: tuple[dict[str, Any], ...] = (
    # Role
    {"key": "median_pos", "label": "Batting position", "block": "role", "role": "bat", "tier": "card", "formats": ("t20", "odi", "test")},
    {"key": "entry_over", "label": "Entry over", "block": "role", "role": "bat", "tier": "bbb", "formats": ("t20", "odi")},
    {"key": "entry_over", "label": "Entry over", "block": "role", "role": "bat", "tier": "card", "formats": ("test",)},
    {"key": "inns_late_share", "label": "3rd/4th innings share", "block": "role", "role": "bat", "tier": "card", "formats": ("test",)},
    {"key": "mean_over", "label": "Mean over bowled", "block": "role", "role": "bowl", "tier": "bbb", "formats": ("t20", "odi")},
    {"key": "death_bowl_share", "label": "Death overs share", "block": "role", "role": "bowl", "tier": "bbb", "formats": ("t20",)},
    {"key": "is_spin", "label": "Spin bowling", "block": "role", "role": "bowl", "tier": "bbb", "formats": ("t20", "odi", "test")},
    # Tempo
    {"key": "rel_sr", "label": "Strike rate vs par", "block": "tempo", "role": "bat", "tier": "card", "formats": ("t20", "odi")},
    {"key": "balls_per_inn", "label": "Balls / innings", "block": "tempo", "role": "bat", "tier": "card", "formats": ("t20", "odi", "test")},
    {"key": "sr_1_10", "label": "SR, balls 1–10", "block": "tempo", "role": "bat", "tier": "bbb", "formats": ("t20", "odi")},
    {"key": "sr_11_20", "label": "SR, balls 11–20", "block": "tempo", "role": "bat", "tier": "bbb", "formats": ("t20", "odi")},
    {"key": "sr_21", "label": "SR, balls 21+", "block": "tempo", "role": "bat", "tier": "bbb", "formats": ("t20", "odi")},
    {"key": "balls_per_out", "label": "Balls per dismissal", "block": "tempo", "role": "bat", "tier": "card", "formats": ("test",)},
    {"key": "rel_econ", "label": "Economy vs par", "block": "tempo", "role": "bowl", "tier": "card", "formats": ("t20", "odi")},
    {"key": "bowl_sr", "label": "Bowling strike rate", "block": "tempo", "role": "bowl", "tier": "card", "formats": ("t20", "odi", "test")},
    {"key": "bowl_balls_per_inn", "label": "Balls / innings", "block": "tempo", "role": "bowl", "tier": "card", "formats": ("t20", "odi", "test")},
    # Method
    {"key": "dot_pct", "label": "Dot %", "block": "method", "role": "bat", "tier": "bbb", "formats": ("t20", "odi")},
    {"key": "ones_pct", "label": "Singles %", "block": "method", "role": "bat", "tier": "bbb", "formats": ("t20", "odi")},
    {"key": "twos_pct", "label": "Twos %", "block": "method", "role": "bat", "tier": "bbb", "formats": ("t20", "odi")},
    {"key": "boundary_pct", "label": "Boundary %", "block": "method", "role": "bat", "tier": "card", "formats": ("t20", "odi")},
    {"key": "six_pct", "label": "Six %", "block": "method", "role": "bat", "tier": "card", "formats": ("t20", "odi")},
    {"key": "balls_per_boundary", "label": "Balls / boundary", "block": "method", "role": "bat", "tier": "card", "formats": ("t20", "odi")},
    {"key": "squeeze_sr", "label": "Middle squeeze SR", "block": "method", "role": "bat", "tier": "bbb", "formats": ("odi",)},
    {"key": "squeeze_dot", "label": "Middle squeeze dot %", "block": "method", "role": "bat", "tier": "bbb", "formats": ("odi",)},
    {"key": "bowl_dot_pct", "label": "Dot %", "block": "method", "role": "bowl", "tier": "card", "formats": ("t20", "odi")},
    {"key": "bowl_boundary_pct", "label": "Boundary % conceded", "block": "method", "role": "bowl", "tier": "bbb", "formats": ("t20", "odi")},
    # Phase
    {"key": "pp_sr", "label": "Powerplay SR", "block": "phase", "role": "bat", "tier": "bbb", "formats": ("t20", "odi")},
    {"key": "mid_sr", "label": "Middle SR", "block": "phase", "role": "bat", "tier": "bbb", "formats": ("t20", "odi")},
    {"key": "death_sr", "label": "Death SR", "block": "phase", "role": "bat", "tier": "bbb", "formats": ("t20",)},
    {"key": "death_run_share", "label": "Death run share", "block": "phase", "role": "bat", "tier": "bbb", "formats": ("t20",)},
    {"key": "pp_econ", "label": "Powerplay economy", "block": "phase", "role": "bowl", "tier": "bbb", "formats": ("t20", "odi")},
    {"key": "death_econ", "label": "Death economy", "block": "phase", "role": "bowl", "tier": "bbb", "formats": ("t20",)},
    {"key": "sr_new", "label": "SR vs new ball", "block": "phase", "role": "bat", "tier": "bbb", "formats": ("test",)},
    {"key": "sr_old", "label": "SR vs old ball", "block": "phase", "role": "bat", "tier": "bbb", "formats": ("test",)},
    # Matchup
    {"key": "sr_pace", "label": "SR vs pace", "block": "matchup", "role": "bat", "tier": "bbb", "formats": ("t20", "odi", "test")},
    {"key": "sr_spin", "label": "SR vs spin", "block": "matchup", "role": "bat", "tier": "bbb", "formats": ("t20", "odi", "test")},
    {"key": "out_pace", "label": "Dismissed vs pace", "block": "matchup", "role": "bat", "tier": "bbb", "formats": ("t20", "odi", "test")},
    {"key": "out_spin", "label": "Dismissed vs spin", "block": "matchup", "role": "bat", "tier": "bbb", "formats": ("t20", "odi", "test")},
    # Risk
    {"key": "fail_rate", "label": "Failure rate", "block": "risk", "role": "bat", "tier": "card", "formats": ("t20", "odi")},
    {"key": "score_sd", "label": "Score variance", "block": "risk", "role": "bat", "tier": "card", "formats": ("t20", "odi", "test")},
    {"key": "thirty_plus", "label": "30+ conversion", "block": "risk", "role": "bat", "tier": "card", "formats": ("t20", "odi")},
    {"key": "d_bowled_lbw", "label": "Bowled/LBW share", "block": "risk", "role": "bat", "tier": "card", "formats": ("t20", "odi", "test")},
    {"key": "d_caught", "label": "Caught share", "block": "risk", "role": "bat", "tier": "card", "formats": ("t20", "odi", "test")},
    {"key": "haz_1_20", "label": "Out in balls 1–20", "block": "risk", "role": "bat", "tier": "card", "formats": ("test",)},
    {"key": "haz_21_50", "label": "Out in balls 21–50", "block": "risk", "role": "bat", "tier": "card", "formats": ("test",)},
    {"key": "haz_51_100", "label": "Out in balls 51–100", "block": "risk", "role": "bat", "tier": "card", "formats": ("test",)},
    {"key": "haz_100", "label": "Out after 100 balls", "block": "risk", "role": "bat", "tier": "card", "formats": ("test",)},
    # Impact — style mode weights this at zero
    {"key": "war", "label": "WAR", "block": "impact", "role": "bat", "tier": "card", "formats": ("t20",)},
    {"key": "war", "label": "WAR", "block": "impact", "role": "bowl", "tier": "card", "formats": ("t20",)},
    {"key": "rae_bat", "label": "RAE bat", "block": "impact", "role": "bat", "tier": "card", "formats": ("t20",)},
    {"key": "rae_bowl", "label": "RAE bowl", "block": "impact", "role": "bowl", "tier": "card", "formats": ("t20",)},
    {"key": "wpa", "label": "WPA", "block": "impact", "role": "both", "tier": "card", "formats": ("t20",)},
    {"key": "pressure", "label": "Pressure", "block": "impact", "role": "both", "tier": "card", "formats": ("t20",)},
)

BLOCK_WEIGHTS = {
    "style": {"role": 1.2, "tempo": 1.2, "method": 1.4, "phase": 1.0, "matchup": 0.9, "risk": 0.8, "impact": 0.0},
    "value": {"role": 0.15, "tempo": 0.15, "method": 0.15, "phase": 0.1, "matchup": 0.1, "risk": 0.1, "impact": 1.0},
}

DISPLAY_BAT = {
    "t20": ["rel_sr", "balls_per_inn", "entry_over", "dot_pct", "boundary_pct", "six_pct", "death_run_share", "fail_rate", "sr_spin"],
    "odi": ["rel_sr", "balls_per_inn", "entry_over", "dot_pct", "boundary_pct", "squeeze_sr", "thirty_plus", "sr_spin"],
    "test": ["balls_per_out", "median_pos", "haz_1_20", "haz_21_50", "haz_51_100", "entry_over", "sr_new", "sr_spin"],
}
DISPLAY_BOWL = {
    "t20": ["rel_econ", "bowl_sr", "bowl_dot_pct", "mean_over", "death_bowl_share", "death_econ", "bowl_boundary_pct"],
    "odi": ["rel_econ", "bowl_sr", "bowl_dot_pct", "mean_over", "pp_econ", "bowl_boundary_pct"],
    "test": ["bowl_sr", "bowl_balls_per_inn"],
}

PRIOR_INNS = {"t20": 12.0, "odi": 10.0, "test": 8.0}
DEFAULT_MIN_INNS = {"t20": 15, "odi": 12, "test": 8}


def format_kind(comps: list[str]) -> str:
    if comps and all(c == "test" for c in comps):
        return "test"
    if comps and all(c == "odi" for c in comps):
        return "odi"
    return "t20"


def default_min_inns(kind: str) -> int:
    return DEFAULT_MIN_INNS.get(kind, 15)


def specs_for(kind: str, role: str, *, tier: str | None = None) -> list[dict[str, Any]]:
    out = []
    seen: set[str] = set()
    for spec in FEATURES:
        if kind not in spec["formats"]:
            continue
        if spec["role"] not in {role, "both"}:
            continue
        if tier and spec["tier"] != tier:
            continue
        if spec["key"] in seen:
            continue
        seen.add(spec["key"])
        out.append(spec)
    return out


def _finite(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return x


def shrink_value(value: float | None, prior: float | None, n: float, n0: float) -> float | None:
    """Pull a rate toward the role prior in proportion to sample size."""
    v = _finite(value)
    p = _finite(prior)
    if v is None:
        return None
    if p is None or n0 <= 0:
        return v
    w = n / (n + n0)
    return w * v + (1.0 - w) * p


def zscore_frame(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Z-score columns. Missing stays missing — never filled with the mean."""
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            continue
        series = pd.to_numeric(out[col], errors="coerce")
        mu = series.mean(skipna=True)
        sd = series.std(skipna=True)
        if sd is None or not np.isfinite(sd) or sd == 0:
            sd = 1.0
        out[f"{col}_z"] = (series - mu) / sd
    return out


def block_distance(a: pd.Series, b: pd.Series, z_cols: list[str]) -> float | None:
    """RMS of shared z-scores. Skips any feature either player lacks."""
    diffs: list[float] = []
    for col in z_cols:
        va = a.get(col)
        vb = b.get(col)
        if va is None or vb is None:
            continue
        try:
            fa, fb = float(va), float(vb)
        except (TypeError, ValueError):
            continue
        if fa != fa or fb != fb:
            continue
        diffs.append((fa - fb) ** 2)
    if not diffs:
        return None
    return float(np.sqrt(np.mean(diffs)))


def pair_distance(
    a: pd.Series,
    b: pd.Series,
    blocks: dict[str, list[str]],
    weights: dict[str, float],
) -> tuple[float | None, int]:
    used = 0
    weighted: list[tuple[float, float]] = []
    for block, cols in blocks.items():
        w = weights.get(block, 0.0)
        if w <= 0:
            continue
        d = block_distance(a, b, cols)
        if d is None:
            continue
        weighted.append((w, d))
        used += sum(
            1
            for c in cols
            if _finite(a.get(c)) is not None and _finite(b.get(c)) is not None
        )
    if not weighted:
        return None, 0
    wsum = sum(w for w, _ in weighted)
    dist = float(np.sqrt(sum(w * d * d for w, d in weighted) / wsum))
    return dist, used


def calibrate_score(distance: float, median_d: float) -> float:
    """Map distance onto 0–100 so the median pair in the pool sits near 50%."""
    if median_d <= 1e-9:
        return 100.0
    return float(max(0.0, min(100.0, 100.0 * (2.0 ** (-distance / median_d)))))


def sample_median_distance(
    frame: pd.DataFrame,
    blocks: dict[str, list[str]],
    weights: dict[str, float],
    *,
    cap: int = 80,
    rng: np.random.Generator | None = None,
) -> float:
    if frame.empty:
        return 1.0
    n = len(frame)
    take = min(cap, n)
    gen = rng or np.random.default_rng(0)
    idx = gen.choice(n, size=take, replace=False) if n > take else np.arange(n)
    sample = frame.iloc[idx]
    dists: list[float] = []
    rows = [sample.iloc[i] for i in range(len(sample))]
    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            d, _ = pair_distance(a, b, blocks, weights)
            if d is not None:
                dists.append(d)
    if len(dists) < 20:
        return 1.0
    return float(np.median(dists))


def explain_match(
    a: pd.Series,
    b: pd.Series,
    pct_a: dict[str, float | None],
    pct_b: dict[str, float | None],
    specs: list[dict[str, Any]],
    *,
    match_max: float = 12.0,
    diverge_min: float = 28.0,
) -> dict[str, list[dict[str, Any]]]:
    rows: list[tuple[float, dict[str, Any]]] = []
    for spec in specs:
        if spec["block"] == "impact":
            continue
        if spec["key"] == "is_spin":
            continue
        key = spec["key"]
        pa, pb = pct_a.get(key), pct_b.get(key)
        if pa is None or pb is None:
            continue
        delta = abs(pa - pb)
        rows.append(
            (
                delta,
                {
                    "key": key,
                    "label": spec["label"],
                    "a": round(pa, 0),
                    "b": round(pb, 0),
                    "delta": round(delta, 0),
                },
            )
        )
    rows.sort(key=lambda item: item[0])
    matches = [item[1] for item in rows if item[0] <= match_max][:3]
    if len(matches) < 2:
        matches = [item[1] for item in rows[:3]]
    diverges = [item[1] for item in reversed(rows) if item[0] >= diverge_min][:3]
    if len(diverges) < 2:
        diverges = [item[1] for item in list(reversed(rows))[:3]]
    used = {item["key"] for item in matches}
    diverges = [item for item in diverges if item["key"] not in used]
    return {"matches": matches, "diverges": diverges}


def percentile_map(frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = pd.DataFrame({"person_id": frame["person_id"]})
    for col in cols:
        if col not in frame.columns:
            out[col] = np.nan
            continue
        series = pd.to_numeric(frame[col], errors="coerce")
        out[col] = series.rank(pct=True, method="average") * 100.0
    return out


def _comps(pool: str | None, gender: str | None) -> tuple[str, list[str]]:
    pool = pool or default_pool(gender)
    comps = parse_comps(pool) or ["t20i", "ipl"]
    return pool, comps


def _year_sql(from_year: int | None, to_year: int | None) -> tuple[str, list[Any]]:
    sql = ""
    params: list[Any] = []
    if from_year:
        sql += " AND year(try_cast(m.start_date AS DATE)) >= ?"
        params.append(int(from_year))
    if to_year:
        sql += " AND year(try_cast(m.start_date AS DATE)) <= ?"
        params.append(int(to_year))
    return sql, params


def _ph(n: int) -> str:
    return ",".join(["?"] * n)


def _scope_sql(
    comps: list[str],
    gender: str | None,
    from_year: int | None,
    to_year: int | None,
    *,
    full_members: bool = False,
) -> tuple[str, list[Any]]:
    sql = f"m.competition IN ({_ph(len(comps))})"
    params: list[Any] = list(comps)
    if gender:
        sql += " AND m.gender = ?"
        params.append(gender)
    extra, extra_params = _year_sql(from_year, to_year)
    sql += extra
    params += extra_params
    if full_members:
        sql += f" AND {wtc_match_sql('m')}"
    return sql, params


def _coverage(con, comps: list[str], gender: str | None) -> dict[str, Any]:
    kind = format_kind(comps)
    params: list[Any] = list(comps)
    gender_sql = ""
    if gender:
        gender_sql = " AND m.gender = ?"
        params.append(gender)
    rows = con.execute(
        f"""
        SELECT m.competition,
               COUNT(*) AS matches,
               SUM(CASE WHEN d.match_id IS NOT NULL THEN 1 ELSE 0 END) AS with_bbb,
               MIN(m.start_date) AS first_match,
               MIN(CASE WHEN d.match_id IS NOT NULL THEN m.start_date END) AS first_bbb
        FROM matches m
        LEFT JOIN (SELECT DISTINCT match_id FROM deliveries) d ON d.match_id = m.match_id
        WHERE m.competition IN ({_ph(len(comps))}){gender_sql}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    ).fetchdf()
    by_comp = []
    for rec in rows.to_dict("records"):
        matches = int(rec["matches"] or 0)
        bbb = int(rec["with_bbb"] or 0)
        by_comp.append(
            {
                "competition": rec["competition"],
                "matches": matches,
                "with_bbb": bbb,
                "first_match": str(rec["first_match"] or "")[:10] or None,
                "first_bbb": str(rec["first_bbb"] or "")[:10] or None,
                "tier": "A" if matches and bbb == matches else ("mixed" if bbb else "B"),
            }
        )
    wall = None if kind == "t20" else TIER_WALL.get(kind)
    return {"kind": kind, "wall": wall, "competitions": by_comp}


def _player_formats(con, person_id: str, gender: str | None) -> list[dict[str, Any]]:
    params: list[Any] = [person_id]
    gender_sql = ""
    if gender:
        gender_sql = " AND m.gender = ?"
        params.append(gender)
    rows = con.execute(
        f"""
        SELECT m.competition, COUNT(*) AS inns
        FROM batting_lines b
        JOIN matches m ON m.match_id = b.match_id
        WHERE b.person_id = ? AND b.innings_kind = 'regular'{gender_sql}
        GROUP BY 1
        ORDER BY inns DESC
        """,
        params,
    ).fetchall()
    return [{"competition": r[0], "inns": int(r[1])} for r in rows]


def _classify_bowlers(con, scope_sql: str, params: list[Any]) -> None:
    df = con.execute(
        f"""
        SELECT d.bowler AS person_id,
               COUNT(*) AS balls,
               SUM(CASE WHEN lower(coalesce(d.wicket_kind, '')) = 'stumped' THEN 1 ELSE 0 END) AS stumpings,
               SUM(CASE WHEN d.d_bowl = 1 THEN 1 ELSE 0 END) AS credited,
               AVG(d."over") AS mean_over
        FROM deliveries d
        JOIN matches m ON m.match_id = d.match_id
        WHERE d.innings_kind = 'regular' AND {scope_sql}
        GROUP BY 1
        HAVING COUNT(*) >= 180
        """,
        params,
    ).fetchdf()
    if df.empty:
        df = pd.DataFrame({"person_id": pd.Series(dtype="object"), "style": pd.Series(dtype="object")})
    else:
        stump_share = df["stumpings"] / df["credited"].clip(lower=1)
        spin = (df["stumpings"] >= 2) | (stump_share >= 0.06)
        df = df.copy()
        df["style"] = np.where(spin, "spin", "pace")
        df = df[["person_id", "style"]]
    con.register("bowler_style", df)


def _card_profiles(
    con,
    role: str,
    scope_sql: str,
    params: list[Any],
    kind: str,
) -> pd.DataFrame:
    if role == "bowl":
        return _bowl_card(con, scope_sql, params, kind)
    return _bat_card(con, scope_sql, params, kind)


def _bat_card(con, scope_sql: str, params: list[Any], kind: str) -> pd.DataFrame:
    entry_sql = """
        LEFT JOIN (
          SELECT match_id, innings, person_id, MIN(entry_legal) AS entry_legal
          FROM (
            SELECT match_id, innings, person_id_1 AS person_id, MIN(start_legal_index) AS entry_legal
            FROM partnerships GROUP BY 1, 2, 3
            UNION ALL
            SELECT match_id, innings, person_id_2, MIN(start_legal_index)
            FROM partnerships GROUP BY 1, 2, 3
          ) u
          GROUP BY 1, 2, 3
        ) ent ON ent.match_id = b.match_id AND ent.innings = b.innings AND ent.person_id = b.person_id
    """
    df = con.execute(
        f"""
        WITH par AS (
          SELECT m.competition, m.season, m.gender,
                 SUM(b.runs) * 100.0 / NULLIF(SUM(b.balls), 0) AS par_sr
          FROM batting_lines b
          JOIN matches m ON m.match_id = b.match_id
          WHERE b.innings_kind = 'regular' AND {scope_sql}
          GROUP BY 1, 2, 3
        )
        SELECT
          b.person_id,
          any_value(p.display_name) AS display_name,
          any_value(p.slug) AS slug,
          COUNT(*) AS inns,
          SUM(b.runs) AS runs,
          SUM(b.balls) AS balls,
          SUM(CASE WHEN NOT b.not_out THEN 1 ELSE 0 END) AS outs,
          MEDIAN(b.position) AS median_pos,
          AVG(b.balls) AS balls_per_inn,
          STDDEV_POP(b.runs) AS score_sd,
          SUM(b.fours) AS fours,
          SUM(b.sixes) AS sixes,
          SUM(CASE WHEN b.balls < 10 THEN 1 ELSE 0 END) AS fails,
          SUM(CASE WHEN b.runs >= 30 THEN 1 ELSE 0 END) AS thirty_n,
          SUM(CASE WHEN lower(coalesce(b.dismissal_kind, '')) IN ('bowled', 'lbw') THEN 1 ELSE 0 END) AS n_bowled_lbw,
          SUM(CASE WHEN lower(coalesce(b.dismissal_kind, '')) LIKE 'caught%' THEN 1 ELSE 0 END) AS n_caught,
          SUM(CASE WHEN b.innings >= 3 AND b.innings < 100 THEN 1 ELSE 0 END) AS inns_late,
          SUM(CASE WHEN NOT b.not_out AND b.balls BETWEEN 1 AND 20 THEN 1 ELSE 0 END) AS out_1_20,
          SUM(CASE WHEN b.balls >= 1 THEN 1 ELSE 0 END) AS ent_1,
          SUM(CASE WHEN NOT b.not_out AND b.balls BETWEEN 21 AND 50 THEN 1 ELSE 0 END) AS out_21_50,
          SUM(CASE WHEN b.balls > 20 THEN 1 ELSE 0 END) AS ent_21,
          SUM(CASE WHEN NOT b.not_out AND b.balls BETWEEN 51 AND 100 THEN 1 ELSE 0 END) AS out_51_100,
          SUM(CASE WHEN b.balls > 50 THEN 1 ELSE 0 END) AS ent_51,
          SUM(CASE WHEN NOT b.not_out AND b.balls > 100 THEN 1 ELSE 0 END) AS out_100,
          SUM(CASE WHEN b.balls > 100 THEN 1 ELSE 0 END) AS ent_100,
          SUM(b.balls * par.par_sr) / NULLIF(SUM(b.balls), 0) AS mix_par_sr,
          AVG(ent.entry_legal * 1.0 / NULLIF(coalesce(m.balls_per_over, 6), 0)) AS card_entry_over,
          SUM(CASE WHEN d.match_id IS NOT NULL THEN 1 ELSE 0 END) AS bbb_inns,
          MIN(year(try_cast(m.start_date AS DATE))) AS year_from,
          MAX(year(try_cast(m.start_date AS DATE))) AS year_to
        FROM batting_lines b
        JOIN matches m ON m.match_id = b.match_id
        JOIN people p ON p.person_id = b.person_id
        LEFT JOIN par ON par.competition = m.competition AND par.season = m.season AND par.gender = m.gender
        LEFT JOIN (SELECT DISTINCT match_id FROM deliveries) d ON d.match_id = b.match_id
        {entry_sql}
        WHERE b.innings_kind = 'regular' AND {scope_sql}
        GROUP BY b.person_id
        """,
        params + params,
    ).fetchdf()
    if df.empty:
        return df
    inns = df["inns"].replace(0, np.nan)
    balls = df["balls"].replace(0, np.nan)
    outs = df["outs"].replace(0, np.nan)
    df["sr"] = df["runs"] * 100.0 / balls
    df["rel_sr"] = df["sr"] / df["mix_par_sr"].replace(0, np.nan)
    df["boundary_pct"] = (df["fours"] + df["sixes"]) * 100.0 / balls
    df["six_pct"] = df["sixes"] * 100.0 / balls
    df["balls_per_boundary"] = balls / (df["fours"] + df["sixes"]).replace(0, np.nan)
    df["fail_rate"] = df["fails"] / inns
    df["thirty_plus"] = df["thirty_n"] / inns
    df["d_bowled_lbw"] = df["n_bowled_lbw"] / outs
    df["d_caught"] = df["n_caught"] / outs
    df["balls_per_out"] = df["balls"] / outs
    df["inns_late_share"] = df["inns_late"] / inns
    df["haz_1_20"] = df["out_1_20"] / df["ent_1"].replace(0, np.nan)
    df["haz_21_50"] = df["out_21_50"] / df["ent_21"].replace(0, np.nan)
    df["haz_51_100"] = df["out_51_100"] / df["ent_51"].replace(0, np.nan)
    df["haz_100"] = df["out_100"] / df["ent_100"].replace(0, np.nan)
    df["entry_over"] = df["card_entry_over"]
    df["tier"] = np.where(df["bbb_inns"] * 2 >= df["inns"], "A", "B")
    df["sample"] = df["inns"]
    return df


def _bowl_card(con, scope_sql: str, params: list[Any], kind: str) -> pd.DataFrame:
    df = con.execute(
        f"""
        WITH par AS (
          SELECT m.competition, m.season, m.gender,
                 SUM(b.runs) * 6.0 / NULLIF(SUM(b.legal_balls), 0) AS par_econ
          FROM bowling_lines b
          JOIN matches m ON m.match_id = b.match_id
          WHERE b.innings_kind = 'regular' AND {scope_sql}
          GROUP BY 1, 2, 3
        )
        SELECT
          b.person_id,
          any_value(p.display_name) AS display_name,
          any_value(p.slug) AS slug,
          COUNT(*) AS inns,
          SUM(b.legal_balls) AS balls,
          SUM(b.runs) AS runs,
          SUM(b.wickets) AS wickets,
          SUM(b.dots) AS dots,
          SUM(b.legal_balls * par.par_econ) / NULLIF(SUM(b.legal_balls), 0) AS mix_par_econ,
          SUM(CASE WHEN d.match_id IS NOT NULL THEN 1 ELSE 0 END) AS bbb_inns,
          MIN(year(try_cast(m.start_date AS DATE))) AS year_from,
          MAX(year(try_cast(m.start_date AS DATE))) AS year_to
        FROM bowling_lines b
        JOIN matches m ON m.match_id = b.match_id
        JOIN people p ON p.person_id = b.person_id
        LEFT JOIN par ON par.competition = m.competition AND par.season = m.season AND par.gender = m.gender
        LEFT JOIN (SELECT DISTINCT match_id FROM deliveries) d ON d.match_id = b.match_id
        WHERE b.innings_kind = 'regular' AND {scope_sql}
        GROUP BY b.person_id
        """,
        params + params,
    ).fetchdf()
    if df.empty:
        return df
    balls = df["balls"].replace(0, np.nan)
    df["bowl_balls_per_inn"] = df["balls"] / df["inns"].replace(0, np.nan)
    df["econ"] = df["runs"] * 6.0 / balls
    df["rel_econ"] = df["econ"] / df["mix_par_econ"].replace(0, np.nan)
    df["bowl_sr"] = df["balls"] / df["wickets"].replace(0, np.nan)
    df["bowl_dot_pct"] = df["dots"] * 100.0 / balls
    df["tier"] = np.where(df["bbb_inns"] * 2 >= df["inns"], "A", "B")
    df["sample"] = df["inns"]
    return df


def _bbb_bat(con, scope_sql: str, params: list[Any], kind: str) -> pd.DataFrame:
    lo, hi = (T20_PHASE if kind == "t20" else ODI_PHASE)
    squeeze_lo, squeeze_hi = ODI_SQUEEZE
    df = con.execute(
        f"""
        WITH faced AS (
          SELECT
            d.striker AS person_id,
            d.match_id,
            d.innings,
            d."over" AS ov,
            d.runs_batter,
            d.is_legal,
            d.non_boundary,
            d.player_out,
            d.striker,
            CASE WHEN d.is_wide THEN 0 ELSE 1 END AS faced,
            SUM(CASE WHEN NOT d.is_wide THEN 1 ELSE 0 END) OVER (
              PARTITION BY d.match_id, d.innings, d.striker
              ORDER BY d.legal_ball_index, d.ball_in_over
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS ball_of_inn,
            CASE
              WHEN d."over" < {int(lo)} THEN 'pp'
              WHEN d."over" < {int(hi)} THEN 'mid'
              ELSE 'death'
            END AS phase,
            CASE
              WHEN (d."over" % 80) < 16 THEN 'new'
              WHEN (d."over" % 80) < 50 THEN 'midball'
              ELSE 'old'
            END AS ball_age,
            bs.style AS bowl_style
          FROM deliveries d
          JOIN matches m ON m.match_id = d.match_id
          LEFT JOIN bowler_style bs ON bs.person_id = d.bowler
          WHERE d.innings_kind = 'regular' AND NOT d.is_wide AND {scope_sql}
        )
        SELECT
          person_id,
          AVG(entry_over) AS entry_over,
          SUM(CASE WHEN ball_of_inn BETWEEN 1 AND 10 THEN runs_batter ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN ball_of_inn BETWEEN 1 AND 10 THEN faced ELSE 0 END), 0) AS sr_1_10,
          SUM(CASE WHEN ball_of_inn BETWEEN 11 AND 20 THEN runs_batter ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN ball_of_inn BETWEEN 11 AND 20 THEN faced ELSE 0 END), 0) AS sr_11_20,
          SUM(CASE WHEN ball_of_inn >= 21 THEN runs_batter ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN ball_of_inn >= 21 THEN faced ELSE 0 END), 0) AS sr_21,
          SUM(CASE WHEN is_legal AND runs_batter = 0 THEN 1 ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN is_legal THEN 1 ELSE 0 END), 0) AS dot_pct,
          SUM(CASE WHEN runs_batter = 1 THEN 1 ELSE 0 END) * 100.0 / NULLIF(SUM(faced), 0) AS ones_pct,
          SUM(CASE WHEN runs_batter = 2 THEN 1 ELSE 0 END) * 100.0 / NULLIF(SUM(faced), 0) AS twos_pct,
          SUM(CASE WHEN phase = 'pp' THEN runs_batter ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN phase = 'pp' THEN faced ELSE 0 END), 0) AS pp_sr,
          SUM(CASE WHEN phase = 'mid' THEN runs_batter ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN phase = 'mid' THEN faced ELSE 0 END), 0) AS mid_sr,
          SUM(CASE WHEN phase = 'death' THEN runs_batter ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN phase = 'death' THEN faced ELSE 0 END), 0) AS death_sr,
          SUM(CASE WHEN phase = 'death' THEN runs_batter ELSE 0 END) * 1.0
            / NULLIF(SUM(runs_batter), 0) AS death_run_share,
          SUM(CASE WHEN ov >= {int(squeeze_lo)} AND ov < {int(squeeze_hi)} THEN runs_batter ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN ov >= {int(squeeze_lo)} AND ov < {int(squeeze_hi)} THEN faced ELSE 0 END), 0) AS squeeze_sr,
          SUM(CASE WHEN ov >= {int(squeeze_lo)} AND ov < {int(squeeze_hi)} AND is_legal AND runs_batter = 0 THEN 1 ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN ov >= {int(squeeze_lo)} AND ov < {int(squeeze_hi)} AND is_legal THEN 1 ELSE 0 END), 0) AS squeeze_dot,
          SUM(CASE WHEN ball_age = 'new' THEN runs_batter ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN ball_age = 'new' THEN faced ELSE 0 END), 0) AS sr_new,
          SUM(CASE WHEN ball_age = 'old' THEN runs_batter ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN ball_age = 'old' THEN faced ELSE 0 END), 0) AS sr_old,
          SUM(CASE WHEN bowl_style = 'pace' THEN runs_batter ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN bowl_style = 'pace' THEN faced ELSE 0 END), 0) AS sr_pace,
          SUM(CASE WHEN bowl_style = 'spin' THEN runs_batter ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN bowl_style = 'spin' THEN faced ELSE 0 END), 0) AS sr_spin,
          SUM(CASE WHEN bowl_style = 'pace' AND player_out = striker THEN 1 ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN bowl_style = 'pace' THEN faced ELSE 0 END), 0) AS out_pace,
          SUM(CASE WHEN bowl_style = 'spin' AND player_out = striker THEN 1 ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN bowl_style = 'spin' THEN faced ELSE 0 END), 0) AS out_spin
        FROM (
          SELECT faced.*,
                 MIN(ov) OVER (PARTITION BY match_id, innings, person_id) AS entry_over
          FROM faced
        ) x
        GROUP BY person_id
        """,
        params,
    ).fetchdf()
    return df


def _bbb_bowl(con, scope_sql: str, params: list[Any], kind: str) -> pd.DataFrame:
    lo, hi = (T20_PHASE if kind == "t20" else ODI_PHASE)
    df = con.execute(
        f"""
        SELECT
          d.bowler AS person_id,
          AVG(d."over") AS mean_over,
          SUM(CASE WHEN d."over" >= {int(hi)} THEN 1 ELSE 0 END) * 1.0
            / NULLIF(COUNT(*), 0) AS death_bowl_share,
          SUM(CASE WHEN d."over" < {int(lo)} THEN d.runs_total ELSE 0 END) * 6.0
            / NULLIF(SUM(CASE WHEN d."over" < {int(lo)} AND d.is_legal THEN 1 ELSE 0 END), 0) AS pp_econ,
          SUM(CASE WHEN d."over" >= {int(hi)} THEN d.runs_total ELSE 0 END) * 6.0
            / NULLIF(SUM(CASE WHEN d."over" >= {int(hi)} AND d.is_legal THEN 1 ELSE 0 END), 0) AS death_econ,
          SUM(CASE WHEN d.runs_batter IN (4, 6) AND NOT d.non_boundary THEN 1 ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN d.is_legal THEN 1 ELSE 0 END), 0) AS bowl_boundary_pct
        FROM deliveries d
        JOIN matches m ON m.match_id = d.match_id
        WHERE d.innings_kind = 'regular' AND {scope_sql}
        GROUP BY 1
        """,
        params,
    ).fetchdf()
    return df


def _value_profiles(con, comps: list[str], gender: str | None) -> pd.DataFrame:
    if not all(c in T20_METRICS for c in comps):
        return pd.DataFrame()
    params: list[Any] = list(comps)
    gender_sql = ""
    if gender:
        gender_sql = " AND mt.gender = ?"
        params.append(gender)
    return con.execute(
        f"""
        SELECT mt.person_id,
               SUM(mt.war) / NULLIF(SUM(mt.innings), 0) AS war,
               SUM(mt.rae_bat * mt.balls_bat) / NULLIF(SUM(mt.balls_bat), 0) AS rae_bat,
               SUM(mt.rae_bowl * mt.balls_bowl) / NULLIF(SUM(mt.balls_bowl), 0) AS rae_bowl,
               SUM(mt.wpa) AS wpa,
               SUM(mt.pressure_impact) / NULLIF(COUNT(*), 0) AS pressure
        FROM metrics_t20 mt
        WHERE mt.competition IN ({_ph(len(comps))}){gender_sql}
        GROUP BY 1
        """,
        params,
    ).fetchdf()


def _anchor_role(con, person_id: str, scope_sql: str, params: list[Any]) -> str:
    row = con.execute(
        f"""
        SELECT
          coalesce((
            SELECT SUM(b.balls) FROM batting_lines b
            JOIN matches m ON m.match_id = b.match_id
            WHERE b.person_id = ? AND b.innings_kind = 'regular' AND {scope_sql}
          ), 0),
          coalesce((
            SELECT SUM(b.legal_balls) FROM bowling_lines b
            JOIN matches m ON m.match_id = b.match_id
            WHERE b.person_id = ? AND b.innings_kind = 'regular' AND {scope_sql}
          ), 0)
        """,
        [person_id] + params + [person_id] + params,
    ).fetchone()
    bat, bowl = (row[0] or 0), (row[1] or 0)
    return "bowl" if bowl > bat else "bat"


def _apply_shrink(df: pd.DataFrame, cols: list[str], n0: float) -> pd.DataFrame:
    out = df.copy()
    n = pd.to_numeric(out.get("sample"), errors="coerce").fillna(0)
    for col in cols:
        if col not in out.columns:
            continue
        prior = pd.to_numeric(out[col], errors="coerce").mean(skipna=True)
        shrunk = []
        series = pd.to_numeric(out[col], errors="coerce")
        for value, ni in zip(series, n):
            shrunk.append(shrink_value(None if pd.isna(value) else float(value), prior, float(ni), n0))
        out[col] = shrunk
    return out


def find_twins(
    con,
    person: dict[str, Any],
    *,
    pool: str | None = None,
    mode: str = "style",
    min_inns: int | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    role: str | None = None,
    gender: str | None = None,
    full_members: bool = True,
) -> dict[str, Any]:
    gender = gender or person.get("gender")
    pool, comps = _comps(pool, gender)
    kind = format_kind(comps)
    mode = "value" if mode == "value" else "style"
    role = role if role in {"bat", "bowl"} else None
    min_inns = int(min_inns) if min_inns else default_min_inns(kind)
    min_inns = max(3, min(80, min_inns))
    if full_members:
        _attach_wtc(con, gender)
    coverage = _coverage(con, comps, gender)
    scope_sql, params = _scope_sql(comps, gender, from_year, to_year, full_members=full_members)
    pid = person["person_id"]
    role = role or _anchor_role(con, pid, scope_sql, params)

    card = _card_profiles(con, role, scope_sql, params, kind)
    if card.empty:
        return {
            "ok": True,
            "person": person,
            "twins": [],
            "anchor": None,
            "coverage": coverage,
            "pool": pool,
            "pool_label": POOL_LABELS.get(pool, pool),
            "mode": mode,
            "role": role,
            "kind": kind,
            "message": "No innings in this pool.",
            "also_played": _player_formats(con, pid, gender),
        }

    bbb = pd.DataFrame()
    if (card["bbb_inns"] > 0).any():
        _classify_bowlers(con, scope_sql, params)
        bbb = _bbb_bowl(con, scope_sql, params, kind) if role == "bowl" else _bbb_bat(con, scope_sql, params, kind)
        if not bbb.empty:
            idx = card.set_index("person_id")
            incoming = bbb.set_index("person_id")
            for col in incoming.columns:
                if col in idx.columns:
                    idx[col] = incoming[col].reindex(idx.index).combine_first(idx[col])
                else:
                    idx[col] = incoming[col].reindex(idx.index)
            card = idx.reset_index()
        if role == "bowl":
            styles = con.execute(
                "SELECT person_id, CASE WHEN style = 'spin' THEN 1.0 ELSE 0.0 END AS is_spin FROM bowler_style"
            ).fetchdf()
            if not styles.empty:
                card = card.drop(columns=["is_spin"], errors="ignore").merge(styles, on="person_id", how="left")

    value = _value_profiles(con, comps, gender)
    if not value.empty:
        card = card.merge(value, on="person_id", how="left")

    eligible = card[(card["inns"] >= min_inns) & (card["balls"] >= min_inns * (8 if role == "bat" else 18))].copy()
    mine = eligible[eligible["person_id"] == pid]
    if mine.empty:
        had = card[card["person_id"] == pid]
        n = int(had.iloc[0]["inns"]) if not had.empty else 0
        return {
            "ok": True,
            "person": person,
            "twins": [],
            "anchor": None,
            "coverage": coverage,
            "pool": pool,
            "pool_label": POOL_LABELS.get(pool, pool),
            "mode": mode,
            "role": role,
            "kind": kind,
            "min_inns": min_inns,
            "message": f"Not enough innings in this pool ({n}; need {min_inns}).",
            "also_played": _player_formats(con, pid, gender),
        }

    specs = specs_for(kind, role)
    feat_keys = [s["key"] for s in specs]
    n0 = PRIOR_INNS.get(kind, 12.0)
    eligible = _apply_shrink(eligible, feat_keys, n0)
    z_keys = [f"{k}_z" for k in feat_keys]
    eligible = zscore_frame(eligible, feat_keys)
    blocks: dict[str, list[str]] = {}
    for spec in specs:
        blocks.setdefault(spec["block"], []).append(f"{spec['key']}_z")
    weights = BLOCK_WEIGHTS[mode]

    median_d = sample_median_distance(eligible, blocks, weights)
    anchor = eligible[eligible["person_id"] == pid].iloc[0]
    others = eligible[eligible["person_id"] != pid]
    rows = []
    for _, rec in others.iterrows():
        pair_tier = "A" if anchor.get("tier") == "A" and rec.get("tier") == "A" else "B"
        use_blocks = blocks
        if pair_tier == "B":
            use_blocks = {}
            for spec in specs:
                if spec["tier"] != "card":
                    continue
                use_blocks.setdefault(spec["block"], []).append(f"{spec['key']}_z")
        dist, used = pair_distance(anchor, rec, use_blocks, weights)
        if dist is None:
            continue
        match = calibrate_score(dist, median_d)
        n_pair = min(float(anchor.get("inns") or 0), float(rec.get("inns") or 0))
        se = 12.0 / max(n_pair, 1.0) ** 0.5
        rows.append(
            {
                "person_id": rec["person_id"],
                "display_name": rec["display_name"],
                "slug": rec["slug"],
                "distance": round(float(dist), 3),
                "match": round(match, 1),
                "match_lo": round(max(0.0, match - 1.96 * se), 1),
                "match_hi": round(min(100.0, match + 1.96 * se), 1),
                "inns": int(rec["inns"] or 0),
                "tier": pair_tier,
                "features_used": used,
                "primary_role": role,
                "war": _finite(rec.get("war")),
                "year_from": int(rec["year_from"]) if pd.notna(rec.get("year_from")) else None,
                "year_to": int(rec["year_to"]) if pd.notna(rec.get("year_to")) else None,
            }
        )
    rows.sort(key=lambda r: r["distance"])
    twins = rows[:8]

    pct_cols = list(dict.fromkeys(feat_keys + (DISPLAY_BAT if role == "bat" else DISPLAY_BOWL)[kind]))
    pct = percentile_map(eligible, [c for c in pct_cols if c in eligible.columns])
    pct_idx = pct.set_index("person_id")
    anchor_pct = pct_idx.loc[pid].to_dict() if pid in pct_idx.index else {}
    best = twins[0] if twins else None
    twin_pct = pct_idx.loc[best["person_id"]].to_dict() if best and best["person_id"] in pct_idx.index else {}
    explain = (
        explain_match(anchor, others[others["person_id"] == best["person_id"]].iloc[0], anchor_pct, twin_pct, specs)
        if best is not None
        else {"matches": [], "diverges": []}
    )

    display_keys = (DISPLAY_BAT if role == "bat" else DISPLAY_BOWL)[kind]
    if mode == "value":
        display_keys = [s["key"] for s in specs if s["block"] == "impact"]
    bars = []
    twin_row = others[others["person_id"] == best["person_id"]].iloc[0] if best is not None else None
    labels = {s["key"]: s["label"] for s in FEATURES}
    for key in display_keys:
        if key not in eligible.columns:
            continue
        av = _finite(anchor.get(key))
        tv = _finite(twin_row.get(key) if twin_row is not None else None)
        if av is None and tv is None:
            continue
        bars.append(
            {
                "key": key,
                "label": labels.get(key, key),
                "a": round(av, 2) if av is not None else None,
                "b": round(tv, 2) if tv is not None else None,
                "a_pct": round(float(anchor_pct[key]), 0) if _finite(anchor_pct.get(key)) is not None else None,
                "b_pct": round(float(twin_pct[key]), 0) if _finite(twin_pct.get(key)) is not None else None,
            }
        )

    for twin in twins:
        if twin.get("war") is not None:
            twin["war"] = round(twin["war"], 2)

    return {
        "ok": True,
        "person": person,
        "anchor": {
            "primary_role": role,
            "inns": int(anchor.get("inns") or 0),
            "tier": str(anchor.get("tier") or "B"),
            "war": None if _finite(anchor.get("war")) is None else round(float(anchor["war"]), 2),
            "year_from": int(anchor["year_from"]) if pd.notna(anchor.get("year_from")) else None,
            "year_to": int(anchor["year_to"]) if pd.notna(anchor.get("year_to")) else None,
            "bbb_inns": int(anchor["bbb_inns"]) if pd.notna(anchor.get("bbb_inns")) else 0,
        },
        "pool": pool,
        "pool_label": POOL_LABELS.get(pool, pool),
        "mode": mode,
        "role": role,
        "kind": kind,
        "min_inns": min_inns,
        "from_year": from_year,
        "to_year": to_year,
        "full_members": full_members,
        "median_distance": round(median_d, 3),
        "coverage": coverage,
        "explain": explain,
        "twins": _jsonable(twins),
        "bars": bars,
    }


