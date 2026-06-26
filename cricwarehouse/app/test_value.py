"""Test-match runs above replacement — overall, peak, and form.

Per-innings context (venue-era pitch, then opposition) → RAA → career volume
plus a shrunk peak rate, linearly calibrated so Bradman is 99 and a replacement
regular is 50. Form is a recency-weighted rate on a 0–10 scale so it cannot be
read against overall.

Bowling replacement is the dual of batting replacement (1.10 × context per
wicket vs 0.75 × context per out). Using 0.75 on both sides makes the average
bowler accumulate negative value and empties the overall top 10 of bowlers.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from cricwarehouse.app.db import connect, warehouse_ready, write_parquet
from cricwarehouse.paths import WAREHOUSE

TEST_VALUE_VERSION = "test-raa-v1.0.0"

NO_OUT = {
    "retired hurt",
    "retired not out",
    "retired - hurt",
    "retired - not out",
    "absent hurt",
    "absent ill",
}

SPINNERS = frozenset(
    {
        "SK Warne", "M Muralitharan", "A Kumble", "R Ashwin", "HMRKB Herath",
        "NM Lyon", "Taijul Islam", "Harbhajan Singh", "GP Swann", "Saeed Ajmal",
        "Yasir Shah", "LR Gibbs", "BS Bedi", "BS Chandrasekhar", "S Venkataraghavan",
        "Iqbal Qasim", "Abdul Qadir", "Mushtaq Ahmed", "Danish Kaneria", "SA Durani",
        "EAS Prasanna", "R Benaud", "CV Grimmett", "WJ O'Reilly", "JC Laker",
        "DL Underwood", "R Illingworth", "AA Mallett", "RJ Shastri", "NS Yadav",
        "SLV Raju", "A Mishra", "PP Ojha", "RA Jadeja", "Kuldeep Yadav",
        "Washington Sundar", "AR Patel", "AU Rashid", "MM Ali", "MJ Leach",
        "KA Maharaj", "SNJ O'Keefe", "NM Hauritz", "S Ramadhin", "AL Valentine",
        "PR Adams", "N Boje", "DL Vettori", "MDK Perera", "HDPK Dharmasena",
        "SA Jayasuriya", "ST Jayasuriya", "MS Panesar", "AF Giles", "JE Emburey",
        "PH Edmonds", "MH Mankad", "V Mankad", "SP Gupte", "H Verity",
        "J Briggs", "R Peel", "C Blythe", "W Rhodes", "H Trumble", "AG Ironmonger",
        "IWG Johnson", "GAR Lock", "PL Harris", "Shakib Al Hasan",
        "Mehidy Hasan Miraz", "Mohammad Rafique", "Enamul Haque jnr", "Sohag Gazi",
        "Nayeem Hasan", "Devendra Bishoo", "Suleiman Benn", "A Zampa", "T Shamsi",
        "Prabath Jayasuriya", "NGRP Jayasuriya", "A Dananjaya", "L Ambuldeniya",
        "Abdur Rehman", "Zulfiqar Babar", "Nauman Ali", "Sajid Khan", "Abrar Ahmed",
        "Noman Ali", "Saqlain Mushtaq", "Tauseef Ahmed", "Intikhab Alam",
        "CL Hooper", "Gudakesh Motie", "NO Miller", "S Muthusamy", "MJ Swepson",
        "Todd Murphy", "T Murphy", "YS Chahal", "Nasum Ahmed", "UDU Chandana",
    }
)

PACE_OVERRIDE = frozenset(
    {
        "SF Barnes", "MD Marshall", "GD McGrath", "CEL Ambrose", "DW Steyn",
        "RJ Hadlee", "DK Lillee", "Wasim Akram", "JM Anderson", "IT Botham",
        "BA Stokes", "JJ Bumrah", "FS Trueman", "JA Snow", "RGD Willis",
        "MA Starc", "PJ Cummins", "JR Hazlewood", "KAJ Roach", "MG Johnson",
        "L Ngidi", "TG Southee", "KR Miller", "AK Davidson", "GA Lohmann",
        "CTB Turner", "CL Cairns", "GS Sobers",
    }
)

BRADMAN_NAME = "DG Bradman"
LN2 = np.log(2.0)


def _nanmed(arr, default: float = 30.0) -> float:
    arr = np.asarray(arr, dtype=float)
    if arr.size == 0 or not np.isfinite(arr).any():
        return default
    val = float(np.nanmedian(arr))
    return val if np.isfinite(val) else default


@dataclass(frozen=True)
class Params:
    k_ctx: float = 12.0
    k_era: float = 25.0
    k_peak: float = 40.0
    k_form: float = 12.0
    k_rate: float = 20.0
    repl_bat: float = 0.75
    repl_bowl: float = 1.00
    quality_exp: float = 2.0
    quality_lo: float = 0.32
    quality_hi: float = 2.50
    blend_career: float = 0.40
    peak_min_days: int = 730
    peak_max_days: int = 1825
    peak_min_tests: int = 20
    peak_min_bat_inns: int = 20
    peak_min_wkts: int = 40
    attack_passes: int = 4
    attack_window_days: int = 1095
    venue_window_days: int = 1825
    form_half_life_days: float = 365.0
    form_gate_inns: int = 10
    form_gate_days: int = 730
    min_list_inns: int = 20
    min_list_wkts: int = 40
    z_pool_min_tests: int = 30
    bradman_score: float = 99.0
    replacement_score: float = 50.0
    active_days: int = 270


DEFAULT_PARAMS = Params()


def _outs(not_out, kind) -> int:
    if bool(not_out):
        return 0
    text = str(kind or "").strip().lower()
    if text in NO_OUT:
        return 0
    return 1


def _clip_quality(val: np.ndarray, params: Params) -> np.ndarray:
    powered = np.sign(val) * np.abs(val) ** float(params.quality_exp)
    return np.clip(powered, params.quality_lo, params.quality_hi)


def _safe_div(num, den, default=np.nan):
    den = np.asarray(den, dtype=float)
    num = np.asarray(num, dtype=float)
    out = np.full(np.broadcast_shapes(np.shape(num), np.shape(den)), default, dtype=float)
    ok = den > 0
    out[ok] = num[ok] / den[ok]
    return out


NS_PER_DAY = np.int64(86_400_000_000_000)


def _date_ns(values) -> np.ndarray:
    """Integer nanoseconds, regardless of pandas datetime resolution."""
    return pd.to_datetime(values).to_numpy(dtype="datetime64[ns]").astype(np.int64)


def load_test_frames(
    con=None,
    *,
    gender: str | None = "male",
    exclude_teams: tuple[str, ...] = (),
    as_of: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Batting lines, bowling lines, and matches for Tests."""
    own = con is None
    if own:
        if not warehouse_ready():
            raise RuntimeError("Warehouse not built yet.")
        con = connect()
    try:
        gender_sql = "AND m.gender = ?" if gender else ""
        match_gender_sql = "AND gender = ?" if gender else ""
        params: list[Any] = []
        if gender:
            params.append(gender)
        as_of_sql = ""
        match_as_of_sql = ""
        if as_of:
            as_of_sql = "AND m.start_date <= ?"
            match_as_of_sql = "AND start_date <= ?"
            params.append(str(as_of)[:10])
        bat = con.execute(
            f"""
            SELECT b.person_id, b.match_id, b.innings, b.runs, b.balls, b.not_out,
                   b.dismissal_kind, b.team, b.player_name,
                   m.start_date, m.venue, m.team_home, m.team_away, m.gender
            FROM batting_lines b
            JOIN matches m ON m.match_id = b.match_id
            WHERE m.competition = 'test' AND b.innings_kind = 'regular'
              {gender_sql} {as_of_sql}
            """,
            params,
        ).fetchdf()
        bowl = con.execute(
            f"""
            SELECT bl.person_id, bl.match_id, bl.innings, bl.runs, bl.legal_balls,
                   bl.wickets, bl.team, bl.player_name,
                   m.start_date, m.venue, m.team_home, m.team_away, m.gender
            FROM bowling_lines bl
            JOIN matches m ON m.match_id = bl.match_id
            WHERE m.competition = 'test' AND bl.innings_kind = 'regular'
              {gender_sql} {as_of_sql}
            """,
            params,
        ).fetchdf()
        matches = con.execute(
            f"""
            SELECT match_id, start_date, venue, team_home, team_away, gender
            FROM matches
            WHERE competition = 'test' {match_gender_sql} {match_as_of_sql}
            """,
            params,
        ).fetchdf()
        names = con.execute(
            "SELECT person_id, display_name, unique_name, slug FROM people"
        ).fetchdf()
    finally:
        if own:
            con.close()

    if exclude_teams:
        banned = set(exclude_teams)
        if not matches.empty:
            keep = ~matches["team_home"].isin(banned) & ~matches["team_away"].isin(banned)
            allowed = set(matches.loc[keep, "match_id"].astype(str))
            matches = matches.loc[keep].reset_index(drop=True)
            if not bat.empty:
                bat = bat.loc[bat["match_id"].astype(str).isin(allowed)].reset_index(drop=True)
            if not bowl.empty:
                bowl = bowl.loc[bowl["match_id"].astype(str).isin(allowed)].reset_index(drop=True)
    if not names.empty:
        names = names.drop_duplicates("person_id")
        if not bat.empty:
            bat = bat.merge(names, on="person_id", how="left")
        if not bowl.empty:
            bowl = bowl.merge(names, on="person_id", how="left")
    return bat, bowl, matches


def prepare_lines(bat: pd.DataFrame, bowl: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    bat = bat.copy()
    bowl = bowl.copy()
    if bat.empty and bowl.empty:
        return bat, bowl
    if not bat.empty:
        bat["date"] = pd.to_datetime(bat["start_date"], errors="coerce")
        bat["runs"] = pd.to_numeric(bat["runs"], errors="coerce").fillna(0.0)
        bat["balls"] = pd.to_numeric(bat["balls"], errors="coerce").fillna(0.0)
        bat["not_out"] = bat["not_out"].fillna(False).astype(bool)
        bat["outs"] = [
            float(_outs(n, k)) for n, k in zip(bat["not_out"], bat["dismissal_kind"])
        ]
        bat["home"] = bat["team"].astype(str) == bat["team_home"].astype(str)
        bat["opposition"] = np.where(bat["home"], bat["team_away"], bat["team_home"])
        bat["venue"] = bat["venue"].fillna("").astype(str)
        bat["match_id"] = bat["match_id"].astype(str)
        bat["person_id"] = bat["person_id"].astype(str)
        bat["innings"] = pd.to_numeric(bat["innings"], errors="coerce").fillna(1).astype(int)
    if not bowl.empty:
        bowl["date"] = pd.to_datetime(bowl["start_date"], errors="coerce")
        bowl["runs"] = pd.to_numeric(bowl["runs"], errors="coerce").fillna(0.0)
        bowl["legal_balls"] = pd.to_numeric(bowl["legal_balls"], errors="coerce").fillna(0.0)
        bowl["wickets"] = pd.to_numeric(bowl["wickets"], errors="coerce").fillna(0.0)
        bowl["home"] = bowl["team"].astype(str) == bowl["team_home"].astype(str)
        bowl["opposition"] = np.where(bowl["home"], bowl["team_away"], bowl["team_home"])
        bowl["venue"] = bowl["venue"].fillna("").astype(str)
        bowl["match_id"] = bowl["match_id"].astype(str)
        bowl["person_id"] = bowl["person_id"].astype(str)
        bowl["innings"] = pd.to_numeric(bowl["innings"], errors="coerce").fillna(1).astype(int)
    return bat, bowl


def _match_player_baseline(bat: pd.DataFrame) -> pd.DataFrame:
    """Leave-the-player-out runs per wicket inside the same innings."""
    if bat.empty:
        return pd.DataFrame(
            columns=["match_id", "person_id", "innings", "baseline_m", "w_m", "match_runs", "match_outs"]
        )
    inn = bat.groupby(["match_id", "innings"], sort=False).agg(
        match_runs=("runs", "sum"),
        match_outs=("outs", "sum"),
    )
    player = bat.groupby(["match_id", "innings", "person_id"], sort=False).agg(
        p_runs=("runs", "sum"),
        p_outs=("outs", "sum"),
    )
    joined = player.join(inn, on=["match_id", "innings"])
    others_runs = joined["match_runs"] - joined["p_runs"]
    others_outs = joined["match_outs"] - joined["p_outs"]
    baseline = _safe_div(others_runs.to_numpy(), others_outs.to_numpy(), default=np.nan)
    out = joined.reset_index()
    out["baseline_m"] = baseline
    out["w_m"] = joined["match_outs"].to_numpy()
    return out[["match_id", "person_id", "innings", "baseline_m", "w_m", "match_runs", "match_outs"]]


def _rolling_group_rpw(
    df: pd.DataFrame,
    *,
    group: str,
    date_col: str,
    runs_col: str,
    wkts_col: str,
    window_days: int,
    min_wkts: float = 8.0,
) -> np.ndarray:
    """Leave-one-out rolling runs-per-wicket inside each group."""
    n = len(df)
    out = np.full(n, np.nan)
    if n == 0:
        return out
    days = window_days
    dates = df[date_col].to_numpy()
    runs = df[runs_col].to_numpy(dtype=float)
    wkts = df[wkts_col].to_numpy(dtype=float)
    keys = df[group].to_numpy()
    order = np.argsort(keys, kind="mergesort")
    # Stable sort by group then date
    dates_k = dates[order]
    keys_k = keys[order]
    # re-sort dates inside groups
    # We iterate groups.
    inv = np.empty(n, dtype=int)
    inv[order] = np.arange(n)
    starts = np.r_[0, 1 + np.flatnonzero(keys_k[1:] != keys_k[:-1]), n]
    for a, b in zip(starts[:-1], starts[1:]):
        idx = order[a:b]
        d = _date_ns(dates[idx])
        r = runs[idx]
        w = wkts[idx]
        inner = np.argsort(d, kind="mergesort")
        d, r, w, idx = d[inner], r[inner], w[inner], idx[inner]
        cr = np.concatenate([[0.0], np.cumsum(r)])
        cw = np.concatenate([[0.0], np.cumsum(w)])
        span = np.int64(days) * NS_PER_DAY
        lo = np.searchsorted(d, d - span, side="left")
        hi = np.searchsorted(d, d + span, side="right")
        tot_r = cr[hi] - cr[lo]
        tot_w = cw[hi] - cw[lo]
        tot_r -= r
        tot_w -= w
        rpw = np.full(len(idx), np.nan)
        ok = tot_w >= min_wkts
        rpw[ok] = tot_r[ok] / tot_w[ok]
        out[idx] = rpw
    return out


def _era_rpw(matches_idx: pd.DataFrame, window_days: int, min_wkts: float = 20.0) -> np.ndarray:
    """Global rolling R/W (no group), leave-one-out."""
    dummy = matches_idx.assign(_g=0)
    return _rolling_group_rpw(
        dummy, group="_g", date_col="date", runs_col="runs", wkts_col="wickets",
        window_days=window_days, min_wkts=min_wkts,
    )


def _match_totals(bat: pd.DataFrame) -> pd.DataFrame:
    if bat.empty:
        return pd.DataFrame(columns=["match_id", "date", "venue", "runs", "wickets", "gender"])
    g = bat.groupby("match_id", sort=False).agg(
        date=("date", "min"),
        venue=("venue", "first"),
        runs=("runs", "sum"),
        wickets=("outs", "sum"),
        gender=("gender", "first"),
    ).reset_index()
    return g


def attach_context(bat: pd.DataFrame, params: Params) -> pd.DataFrame:
    """Phase 1: leave-one-out match baseline shrunk toward a venue-era prior."""
    if bat.empty:
        bat = bat.copy()
        bat["context_m"] = pd.Series(dtype=float)
        bat["baseline_m"] = pd.Series(dtype=float)
        bat["prior_ve"] = pd.Series(dtype=float)
        return bat
    base = _match_player_baseline(bat)
    bat = bat.merge(base, on=["match_id", "innings", "person_id"], how="left")
    totals = _match_totals(bat)
    totals = totals.sort_values("date").reset_index(drop=True)
    totals["venue_rpw"] = _rolling_group_rpw(
        totals, group="venue", date_col="date", runs_col="runs", wkts_col="wickets",
        window_days=params.venue_window_days, min_wkts=8.0,
    )
    totals["era_rpw"] = _era_rpw(totals, params.venue_window_days, min_wkts=20.0)
    global_rpw = _nanmed(totals["era_rpw"], 30.0)
    if not np.isfinite(global_rpw) or global_rpw <= 0:
        global_rpw = 30.0
    venue_n = totals.groupby("venue")["wickets"].transform("sum")
    prior = (
        venue_n.to_numpy(dtype=float) * totals["venue_rpw"].to_numpy(dtype=float)
        + params.k_era * totals["era_rpw"].fillna(global_rpw).to_numpy(dtype=float)
    ) / (venue_n.to_numpy(dtype=float) + params.k_era)
    prior = np.where(np.isfinite(prior) & (prior > 0), prior, totals["era_rpw"].fillna(global_rpw))
    totals["prior_ve"] = prior
    bat = bat.merge(totals[["match_id", "prior_ve", "era_rpw", "venue_rpw"]], on="match_id", how="left")
    w = pd.to_numeric(bat["w_m"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    baseline = pd.to_numeric(bat["baseline_m"], errors="coerce").to_numpy(dtype=float)
    prior_ve = pd.to_numeric(bat["prior_ve"], errors="coerce").fillna(global_rpw).to_numpy(dtype=float)
    baseline = np.where(np.isfinite(baseline) & (baseline > 0), baseline, prior_ve)
    ctx = (w * baseline + params.k_ctx * prior_ve) / np.maximum(w + params.k_ctx, 1.0)
    bat["context_m"] = ctx
    bat["global_rpw"] = global_rpw
    return bat


def _player_recent_rpw(
    df: pd.DataFrame,
    *,
    runs_col: str,
    wkts_col: str,
    window_days: int,
    min_wkts: float,
) -> np.ndarray:
    return _rolling_group_rpw(
        df,
        group="person_id",
        date_col="date",
        runs_col=runs_col,
        wkts_col=wkts_col,
        window_days=window_days,
        min_wkts=min_wkts,
    )


def _team_recent_rpw(
    df: pd.DataFrame,
    *,
    team_col: str,
    runs_col: str,
    wkts_col: str,
    window_days: int,
    min_wkts: float,
) -> np.ndarray:
    return _rolling_group_rpw(
        df,
        group=team_col,
        date_col="date",
        runs_col=runs_col,
        wkts_col=wkts_col,
        window_days=window_days,
        min_wkts=min_wkts,
    )


def attach_opposition(
    bat: pd.DataFrame,
    bowl: pd.DataFrame,
    params: Params,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Phase 2: iterative attack / batting quality, sequential approximation."""
    if bat.empty:
        return bat, bowl
    era = _nanmed(bat["era_rpw"], 30.0) if "era_rpw" in bat else 30.0
    if era <= 0:
        era = 30.0

    bowl = bowl.copy()
    if not bowl.empty:
        bowl["bowl_team_rpw"] = _team_recent_rpw(
            bowl, team_col="team", runs_col="runs", wkts_col="wickets",
            window_days=params.attack_window_days, min_wkts=12.0,
        )
        bowl["player_rpw"] = _player_recent_rpw(
            bowl, runs_col="runs", wkts_col="wickets",
            window_days=params.attack_window_days, min_wkts=8.0,
        )
    bat = bat.copy()
    bat["bat_team_rpw"] = _team_recent_rpw(
        bat, team_col="team", runs_col="runs", wkts_col="outs",
        window_days=params.attack_window_days, min_wkts=12.0,
    )
    bat["player_bat_rpw"] = _player_recent_rpw(
        bat, runs_col="runs", wkts_col="outs",
        window_days=params.attack_window_days, min_wkts=8.0,
    )

    # Innings-level attack from the bowling side.
    inn_keys = ["match_id", "innings"]
    if not bowl.empty:
        team_attack = (
            bowl.groupby(inn_keys, sort=False)["bowl_team_rpw"].median().rename("attack_rpw")
        )
        bat = bat.merge(team_attack, on=inn_keys, how="left")
        bowl = bowl.merge(team_attack, on=inn_keys, how="left")
    else:
        bat["attack_rpw"] = era
        bowl["attack_rpw"] = era

    # Batting quality of the side being bowled at (this innings), not both teams mixed.
    team_bat = bat.groupby(inn_keys, sort=False)["bat_team_rpw"].median().rename("opp_bat_rpw")
    if not bowl.empty:
        bowl = bowl.merge(team_bat, on=inn_keys, how="left")

    for _ in range(max(params.attack_passes - 1, 0)):
        if bowl.empty:
            break
        tmp = bowl.copy()
        tmp["use_rpw"] = tmp["player_rpw"].fillna(tmp["bowl_team_rpw"])
        tmp["wt"] = tmp["legal_balls"].clip(lower=1.0)
        tmp["wr"] = tmp["use_rpw"] * tmp["wt"]
        num = tmp.groupby(inn_keys, sort=False)["wr"].sum()
        den = tmp.groupby(inn_keys, sort=False)["wt"].sum()
        attack_rpw = (num / den.replace(0, np.nan)).rename("attack_rpw")
        bat = bat.drop(columns=["attack_rpw"], errors="ignore").merge(
            attack_rpw, on=inn_keys, how="left"
        )
        bowl = bowl.drop(columns=["attack_rpw"], errors="ignore").merge(
            attack_rpw, on=inn_keys, how="left"
        )
        bowl["player_rpw"] = _player_recent_rpw(
            bowl, runs_col="runs", wkts_col="wickets",
            window_days=params.attack_window_days, min_wkts=8.0,
        )

    if not bowl.empty:
        match_attack = bowl.groupby("match_id", sort=False)["bowl_team_rpw"].median()
        if "attack_rpw" in bat:
            bat["attack_rpw"] = bat["attack_rpw"].fillna(bat["match_id"].map(match_attack))
        match_bat = bat.groupby("match_id", sort=False)["bat_team_rpw"].median()
        if "opp_bat_rpw" in bowl:
            bowl["opp_bat_rpw"] = bowl["opp_bat_rpw"].fillna(bowl["match_id"].map(match_bat))

    bat["attack_rpw"] = pd.to_numeric(bat.get("attack_rpw"), errors="coerce").fillna(era)
    attack_q = _clip_quality(era / np.maximum(bat["attack_rpw"].to_numpy(dtype=float), 1.0), params)
    bat["attack_quality"] = attack_q
    if not bowl.empty:
        bowl["attack_rpw"] = pd.to_numeric(bowl.get("attack_rpw"), errors="coerce").fillna(era)
        bowl["opp_bat_rpw"] = pd.to_numeric(bowl.get("opp_bat_rpw"), errors="coerce").fillna(era)
        bowl_q = _clip_quality(
            bowl["opp_bat_rpw"].to_numpy(dtype=float) / max(era, 1.0), params
        )
        bowl["batting_quality"] = bowl_q
    return bat, bowl


def score_raa(
    bat: pd.DataFrame,
    bowl: pd.DataFrame,
    params: Params,
    *,
    apply_opposition: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Phase 3: runs above replacement, same unit for bat and ball."""
    bat = bat.copy()
    bowl = bowl.copy()
    ctx = pd.to_numeric(bat["context_m"], errors="coerce").fillna(30.0).clip(lower=8.0, upper=80.0)
    if apply_opposition and "attack_quality" in bat:
        quality = pd.to_numeric(bat["attack_quality"], errors="coerce").fillna(1.0)
    else:
        quality = 1.0
    bat["raa_bat"] = bat["runs"] * quality - params.repl_bat * ctx * bat["outs"]
    bat["raa_bowl"] = 0.0
    bat["raa"] = bat["raa_bat"]
    bat["discipline"] = "bat"
    if bowl.empty:
        bowl["raa_bowl"] = pd.Series(dtype=float)
        bowl["raa"] = pd.Series(dtype=float)
        bowl["discipline"] = pd.Series(dtype=str)
        return bat, bowl
    ctx_map = bat.groupby("match_id", sort=False)["context_m"].median().rename("_ctx")
    bowl = bowl.drop(columns=["_ctx"], errors="ignore").merge(ctx_map, on="match_id", how="left")
    ctx_b = pd.to_numeric(bowl["_ctx"], errors="coerce")
    ctx_b = ctx_b.fillna(float(ctx.median()) if len(ctx) else 30.0)
    ctx_b = ctx_b.clip(lower=8.0, upper=80.0)
    bowl = bowl.drop(columns=["_ctx"], errors="ignore")
    if apply_opposition and "batting_quality" in bowl:
        bq = pd.to_numeric(bowl["batting_quality"], errors="coerce").fillna(1.0)
    else:
        bq = 1.0
    bowl = bowl.copy()
    bowl["context_m"] = ctx_b.to_numpy()
    bowl["raa_bowl"] = params.repl_bowl * bowl["context_m"] * bowl["wickets"] * bq - bowl["runs"]
    bowl["raa_bat"] = 0.0
    bowl["raa"] = bowl["raa_bowl"]
    bowl["discipline"] = "bowl"
    return bat, bowl


def _combine_player_matches(bat: pd.DataFrame, bowl: pd.DataFrame) -> pd.DataFrame:
    """One row per player-match, with batting and bowling RAA added."""
    parts = []
    if not bat.empty:
        g = bat.groupby(["person_id", "match_id"], sort=False).agg(
            date=("date", "min"),
            venue=("venue", "first"),
            team=("team", "first"),
            opposition=("opposition", "first"),
            home=("home", "first"),
            gender=("gender", "first"),
            unique_name=("unique_name", "first") if "unique_name" in bat else ("person_id", "first"),
            display_name=("display_name", "first") if "display_name" in bat else ("player_name", "first"),
            slug=("slug", "first") if "slug" in bat else ("person_id", "first"),
            bat_runs=("runs", "sum"),
            bat_outs=("outs", "sum"),
            bat_inns=("runs", "count"),
            raa_bat=("raa_bat", "sum"),
            context_m=("context_m", "mean"),
        ).reset_index()
        parts.append(g)
    if not bowl.empty:
        g = bowl.groupby(["person_id", "match_id"], sort=False).agg(
            date=("date", "min"),
            venue=("venue", "first"),
            team=("team", "first"),
            opposition=("opposition", "first"),
            home=("home", "first"),
            gender=("gender", "first"),
            unique_name=("unique_name", "first") if "unique_name" in bowl else ("person_id", "first"),
            display_name=("display_name", "first") if "display_name" in bowl else ("player_name", "first"),
            slug=("slug", "first") if "slug" in bowl else ("person_id", "first"),
            bowl_runs=("runs", "sum"),
            bowl_wkts=("wickets", "sum"),
            bowl_inns=("runs", "count"),
            bowl_balls=("legal_balls", "sum"),
            raa_bowl=("raa_bowl", "sum"),
        ).reset_index()
        parts.append(g)
    if not parts:
        return pd.DataFrame()
    if len(parts) == 1:
        out = parts[0]
    else:
        out = parts[0].merge(parts[1], on=["person_id", "match_id"], how="outer", suffixes=("", "_b"))
        for col in ("date", "venue", "team", "opposition", "home", "gender", "unique_name", "display_name", "slug"):
            alt = f"{col}_b"
            if alt in out.columns:
                out[col] = out[col].where(out[col].notna(), out[alt])
                out = out.drop(columns=[alt])
    for col, default in (
        ("bat_runs", 0.0), ("bat_outs", 0.0), ("bat_inns", 0.0), ("raa_bat", 0.0),
        ("bowl_runs", 0.0), ("bowl_wkts", 0.0), ("bowl_inns", 0.0), ("bowl_balls", 0.0),
        ("raa_bowl", 0.0), ("context_m", np.nan),
    ):
        if col not in out:
            out[col] = default
        else:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(default)
    out["raa"] = out["raa_bat"] + out["raa_bowl"]
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["tests"] = 1.0
    return out.sort_values(["person_id", "date", "match_id"]).reset_index(drop=True)


def _peak_for_player(g: pd.DataFrame, params: Params) -> dict[str, Any]:
    """Best RAA-per-Test over windows spanning ≥24 months with enough volume."""
    empty = {"peak_rate": 0.0, "peak_n": 0.0, "peak_start": None, "peak_end": None, "peak_inns": 0}
    if g.empty:
        return empty
    g = g.sort_values("date")
    n = len(g)
    raa = g["raa"].to_numpy(dtype=float)
    bat_inns = g["bat_inns"].to_numpy(dtype=float)
    wkts = g["bowl_wkts"].to_numpy(dtype=float)
    craa = np.concatenate([[0.0], np.cumsum(raa)])
    cbat = np.concatenate([[0.0], np.cumsum(bat_inns)])
    cwk = np.concatenate([[0.0], np.cumsum(wkts)])
    d64 = _date_ns(g["date"])
    min_span = np.int64(params.peak_min_days) * NS_PER_DAY
    max_span = np.int64(getattr(params, "peak_max_days", 1095)) * NS_PER_DAY
    min_tests = int(getattr(params, "peak_min_tests", 12))
    best = -1e18
    best_i = best_j = 0
    best_n = 0.0
    for i in range(n):
        if pd.isna(g["date"].iloc[i]):
            continue
        j0 = int(np.searchsorted(d64, d64[i] + min_span, side="left"))
        j1 = int(np.searchsorted(d64, d64[i] + max_span, side="right")) - 1
        if j0 >= n or j1 < j0:
            continue
        for j in range(j0, j1 + 1):
            n_bat = cbat[j + 1] - cbat[i]
            n_wk = cwk[j + 1] - cwk[i]
            n_match = j - i + 1
            if n_match < min_tests:
                continue
            if n_bat < params.peak_min_bat_inns and n_wk < params.peak_min_wkts:
                continue
            rate = (craa[j + 1] - craa[i]) / float(n_match)
            if rate > best:
                best = rate
                best_i, best_j, best_n = i, j, float(n_match)
    if best < -1e17:
        return empty
    start = g["date"].iloc[best_i]
    end = g["date"].iloc[best_j]
    return {
        "peak_rate": float(best),
        "peak_n": float(best_n),
        "peak_start": start.date().isoformat() if pd.notna(start) else None,
        "peak_end": end.date().isoformat() if pd.notna(end) else None,
        "peak_inns": float(best_n),
    }


def aggregate_players(pm: pd.DataFrame, params: Params) -> pd.DataFrame:
    """Phase 4: career volume and shrunk peak rate."""
    if pm.empty:
        return pd.DataFrame()
    rows = []
    for pid, g in pm.groupby("person_id", sort=False):
        peak = _peak_for_player(g, params)
        home = g[g["home"] == True]  # noqa: E712
        away = g[g["home"] == False]  # noqa: E712
        rec = {
            "person_id": pid,
            "gender": g["gender"].dropna().iloc[0] if g["gender"].notna().any() else None,
            "unique_name": g["unique_name"].dropna().iloc[0] if "unique_name" in g and g["unique_name"].notna().any() else None,
            "display_name": g["display_name"].dropna().iloc[0] if "display_name" in g and g["display_name"].notna().any() else None,
            "slug": g["slug"].dropna().iloc[0] if "slug" in g and g["slug"].notna().any() else None,
            "tests": int(g["match_id"].nunique()),
            "bat_inns": float(g["bat_inns"].sum()),
            "bowl_wkts": float(g["bowl_wkts"].sum()),
            "bowl_inns": float(g["bowl_inns"].sum()),
            "bowl_balls": float(g["bowl_balls"].sum()),
            "bat_runs": float(g["bat_runs"].sum()),
            "bowl_runs": float(g["bowl_runs"].sum()),
            "career_raa": float(g["raa"].sum()),
            "career_raa_bat": float(g["raa_bat"].sum()),
            "career_raa_bowl": float(g["raa_bowl"].sum()),
            "career_raa_home": float(home["raa"].sum()) if len(home) else 0.0,
            "career_raa_away": float(away["raa"].sum()) if len(away) else 0.0,
            "home_tests": int(home["match_id"].nunique()) if len(home) else 0,
            "away_tests": int(away["match_id"].nunique()) if len(away) else 0,
            "last_date": g["date"].max().date().isoformat() if g["date"].notna().any() else None,
            "first_date": g["date"].min().date().isoformat() if g["date"].notna().any() else None,
            **peak,
        }
        n_inn = rec["bat_inns"] + rec["bowl_inns"]
        rec["career_rate"] = rec["career_raa"] / max(float(rec["tests"]), 1.0)
        rec["n_inn"] = n_inn
        rec["home_rate"] = (rec["career_raa_home"] / max(float(rec["home_tests"]), 1.0)) if rec["home_tests"] else None
        rec["away_rate"] = (rec["career_raa_away"] / max(float(rec["away_tests"]), 1.0)) if rec["away_tests"] else None
        rows.append(rec)
    players = pd.DataFrame(rows)
    pop_mean = float(players.loc[players["tests"] >= 30, "career_rate"].median()) if (players["tests"] >= 30).any() else float(players["career_rate"].median())
    if not np.isfinite(pop_mean) or pop_mean < 0:
        pop_mean = 0.0
    n = players["peak_n"].to_numpy(dtype=float)
    raw = players["peak_rate"].to_numpy(dtype=float)
    shrunk = (n * raw + params.k_peak * pop_mean) / np.maximum(n + params.k_peak, 1.0)
    players["peak_shrunk"] = np.where(n > 0, shrunk, 0.0)
    n_t = players["tests"].to_numpy(dtype=float)
    k_r = float(params.k_rate)
    players["rate_shrunk"] = (n_t * players["career_rate"].to_numpy(dtype=float) + k_r * pop_mean) / np.maximum(n_t + k_r, 1.0)
    players["pop_mean_rate"] = pop_mean
    return players


def _z(values: np.ndarray) -> tuple[np.ndarray, float, float]:
    arr = np.asarray(values, dtype=float)
    mu = float(np.nanmean(arr)) if len(arr) else 0.0
    sd = float(np.nanstd(arr)) if len(arr) else 1.0
    if not np.isfinite(sd) or sd < 1e-9:
        sd = 1.0
    return (arr - mu) / sd, mu, sd


def _slog(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return np.sign(arr) * np.log1p(np.abs(arr))


def _ssqrt(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return np.sign(arr) * np.sqrt(np.abs(arr))


def calibrate(players: pd.DataFrame, params: Params, *, anchor_name: str = BRADMAN_NAME) -> pd.DataFrame:
    """Phase 5: two-point linear map, Bradman = 99, replacement = 50."""
    if players.empty:
        return players
    players = players.copy()
    pool = players[
        (players["tests"] >= params.z_pool_min_tests)
        | (players["bat_inns"] >= params.min_list_inns)
        | (players["bowl_wkts"] >= params.min_list_wkts)
    ]
    if pool.empty:
        pool = players
    z_c, mu_c, sd_c = _z(_ssqrt(pool["career_raa"].to_numpy(dtype=float)))
    z_r, mu_r, sd_r = _z(pool["rate_shrunk"].to_numpy(dtype=float) if "rate_shrunk" in pool else pool["career_rate"].to_numpy(dtype=float))
    z_p, mu_p, sd_p = _z(pool["peak_shrunk"].to_numpy())
    zc = (_ssqrt(players["career_raa"].to_numpy(dtype=float)) - mu_c) / sd_c
    zr = ((players["rate_shrunk"] if "rate_shrunk" in players else players["career_rate"]).to_numpy(dtype=float) - mu_r) / sd_r
    zp = (players["peak_shrunk"].to_numpy(dtype=float) - mu_p) / sd_p
    blend = params.blend_career
    # Career rate (Bradman's outlier) carries more weight than volume, so a
    # 168-Test pile cannot outrank 99 runs per out.
    raw = blend * zc + (1.0 - blend) * zr
    players["overall_raw"] = raw
    zc0 = (0.0 - mu_c) / sd_c
    zr0 = (0.0 - mu_r) / sd_r
    raw0 = blend * zc0 + (1.0 - blend) * zr0
    anchor = players["unique_name"] == anchor_name
    if not anchor.any():
        idx = int(players["career_raa"].idxmax())
        raw_b = float(players.loc[idx, "overall_raw"])
    else:
        raw_b = float(players.loc[anchor, "overall_raw"].iloc[0])
    span = raw_b - raw0
    if abs(span) < 1e-9:
        span = 1.0
    a = params.replacement_score
    b = (params.bradman_score - params.replacement_score) / span
    players["overall"] = a + b * (players["overall_raw"] - raw0)
    peak_raw = 0.20 * zc + 0.80 * zp
    players["peak_raw"] = peak_raw
    players["peak"] = a + b * (peak_raw - raw0)
    for src, dest in (("career_raa_bat", "bat"), ("career_raa_bowl", "bowl"),
                      ("career_raa_home", "home_overall"), ("career_raa_away", "away_overall")):
        z_disc = (_ssqrt(players[src].to_numpy(dtype=float)) - mu_c) / sd_c
        disc_raw = blend * z_disc + (1.0 - blend) * zr
        players[dest] = a + b * (disc_raw - raw0)
    players["cal_a"] = a
    players["cal_b"] = b
    players["cal_raw0"] = raw0
    players["cal_mu_c"] = mu_c
    players["cal_sd_c"] = sd_c
    players["cal_mu_p"] = mu_p
    players["cal_sd_p"] = sd_p
    players["cal_mu_r"] = mu_r
    players["cal_sd_r"] = sd_r
    return players


def qualify(players: pd.DataFrame, params: Params) -> pd.DataFrame:
    """Judgment 39: need 20 innings or 40 wickets to appear on any list."""
    if players.empty:
        return players
    ok = (players["bat_inns"] >= params.min_list_inns) | (players["bowl_wkts"] >= params.min_list_wkts)
    out = players.loc[ok].copy()
    return out


def classify(players: pd.DataFrame) -> pd.DataFrame:
    players = players.copy()
    names = players["unique_name"].fillna("").astype(str)
    bowl_more = players["career_raa_bowl"] > players["career_raa_bat"]
    players["primary"] = np.where(bowl_more, "bowl", "bat")
    both = (players["bat_inns"] >= 40) & (players["bowl_wkts"] >= 80)
    allround = both & (players["career_raa_bat"] > 0) & (players["career_raa_bowl"] > 0)
    players.loc[allround, "primary"] = "allround"
    # All-rounders are not frontline bowlers — Imran/Kallis/Jadeja must not
    # displace Marshall as the top fast bowler or pad the bowler quota.
    players["is_frontline_bowl"] = (players["bowl_wkts"] >= 100) & bowl_more & ~allround
    is_spin = names.isin(SPINNERS) & ~names.isin(PACE_OVERRIDE)
    players["is_spin"] = is_spin
    players["is_fast"] = players["is_frontline_bowl"] & ~is_spin
    return players


def _map_form_scale(rates: np.ndarray, active: np.ndarray) -> np.ndarray:
    """0–10 among active players: median 6.5, 90th 8.8, current best 9.6."""
    out = np.full(len(rates), np.nan)
    ok = active & np.isfinite(rates)
    if int(ok.sum()) < 5:
        return out
    pool = rates[ok]
    p10 = float(np.percentile(pool, 10))
    p50 = float(np.median(pool))
    p90 = float(np.percentile(pool, 90))
    hi = float(np.max(pool))
    r = rates
    span_lo = max(p50 - p10, 1e-6)
    span_mid = max(p90 - p50, 1e-6)
    mapped = np.where(r >= p50, 6.5 + 2.3 * (r - p50) / span_mid, 6.5 + 3.5 * (r - p50) / span_lo)
    if hi > p90 + 1e-9:
        mapped = np.where(r >= p90, 8.8 + 0.8 * (r - p90) / (hi - p90), mapped)
    finite = np.isfinite(r)
    out[finite] = np.clip(mapped[finite], 1.0, 9.7)
    out[~ok] = np.nan
    return out


def compute_form(
    pm: pd.DataFrame,
    players: pd.DataFrame,
    params: Params,
    *,
    as_of=None,
) -> pd.DataFrame:
    """Phase 6: decay-weighted RAA per Test, shrunk toward the player's own career."""
    if pm.empty or players.empty:
        players = players.copy()
        players["form"] = np.nan
        players["form_rate"] = np.nan
        players["form_n"] = 0.0
        return players
    as_of_ts = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(pm["date"].max())
    half = float(params.form_half_life_days)
    gate_days = params.form_gate_days
    rows = []
    career = players.set_index("person_id")["career_rate"].to_dict()
    for pid, g in pm.groupby("person_id", sort=False):
        g = g[g["date"] <= as_of_ts]
        if g.empty:
            continue
        days = (as_of_ts - g["date"]).dt.days.to_numpy(dtype=float)
        recent = days <= gate_days
        n_recent = float((g.loc[recent, "bat_inns"] + g.loc[recent, "bowl_inns"]).sum()) if recent.any() else 0.0
        if n_recent < params.form_gate_inns:
            rows.append({"person_id": pid, "form_rate": None, "form_n": n_recent, "form_as_of": as_of_ts.date().isoformat()})
            continue
        w = np.exp(-LN2 * np.clip(days, 0, None) / max(half, 1.0))
        raa = g["raa"].to_numpy(dtype=float)
        den = float(np.sum(w))
        rate = float(np.sum(w * raa) / den) if den > 0 else 0.0
        n_eff = den
        prior = float(career.get(pid, 0.0) or 0.0)
        shrunk = (n_eff * rate + params.k_form * prior) / max(n_eff + params.k_form, 1.0)
        rows.append({
            "person_id": pid,
            "form_rate": shrunk,
            "form_n": n_eff,
            "form_as_of": as_of_ts.date().isoformat(),
            "last_match": g["date"].max().date().isoformat(),
        })
    form = pd.DataFrame(rows)
    players = players.merge(form, on="person_id", how="left")
    rates = pd.to_numeric(players["form_rate"], errors="coerce")
    last_src = players["last_match"] if "last_match" in players.columns else players.get("last_date")
    if not isinstance(last_src, pd.Series):
        last_src = pd.Series(pd.NaT, index=players.index)
    last = pd.to_datetime(last_src, errors="coerce")
    age = (as_of_ts - last).dt.days
    active = rates.notna() & last.notna() & (age <= params.active_days)
    players["active"] = active
    players["form"] = _map_form_scale(rates.to_numpy(dtype=float), active.to_numpy(dtype=bool))
    players.loc[~players["active"].fillna(False), "form"] = np.nan
    return players


def scale_round(players: pd.DataFrame) -> pd.DataFrame:
    players = players.copy()
    for col in ("overall", "peak", "bat", "bowl", "home_overall", "away_overall"):
        if col in players:
            players[col] = pd.to_numeric(players[col], errors="coerce").clip(40.0, 99.9).round(1)
    if "form" in players:
        players["form"] = pd.to_numeric(players["form"], errors="coerce").clip(0.0, 10.0).round(1)
    return players


def innings_table(bat: pd.DataFrame, bowl: pd.DataFrame) -> pd.DataFrame:
    """Stored per-innings values — every published rating is a function of these."""
    cols = [
        "match_id", "person_id", "innings", "date", "venue", "team", "opposition", "home",
        "discipline", "runs", "outs", "wickets", "legal_balls", "context_m",
        "baseline_m", "prior_ve", "attack_quality", "batting_quality",
        "raa_bat", "raa_bowl", "raa",
    ]
    frames = []
    if not bat.empty:
        b = bat.copy()
        b["wickets"] = 0.0
        b["legal_balls"] = 0.0
        b["batting_quality"] = np.nan
        frames.append(b)
    if not bowl.empty:
        w = bowl.copy()
        w["outs"] = 0.0
        w["runs_bat"] = w.get("runs")
        w["baseline_m"] = np.nan
        w["prior_ve"] = np.nan
        w["attack_quality"] = np.nan
        frames.append(w)
    if not frames:
        return pd.DataFrame(columns=cols)
    out = pd.concat(frames, ignore_index=True, sort=False)
    for c in cols:
        if c not in out:
            out[c] = np.nan
    keep = out[cols].copy()
    keep["date"] = pd.to_datetime(keep["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return keep


def rating_series(pm: pd.DataFrame, players: pd.DataFrame, params: Params) -> pd.DataFrame:
    """Overall as-of each of a player's matches — the career trajectory."""
    if pm.empty or players.empty:
        return pd.DataFrame()
    mu_c = float(players["cal_mu_c"].iloc[0])
    sd_c = float(players["cal_sd_c"].iloc[0]) or 1.0
    mu_p = float(players["cal_mu_p"].iloc[0])
    sd_p = float(players["cal_sd_p"].iloc[0]) or 1.0
    raw0 = float(players["cal_raw0"].iloc[0])
    a = float(players["cal_a"].iloc[0])
    b = float(players["cal_b"].iloc[0])
    blend = params.blend_career
    peak_map = players.set_index("person_id")["peak_shrunk"].to_dict()
    rows = []
    for pid, g in pm.groupby("person_id", sort=False):
        g = g.sort_values("date")
        cum = g["raa"].cumsum()
        pk = float(peak_map.get(pid, 0.0) or 0.0)
        for date, val in zip(g["date"], cum):
            zc = (float(np.sign(val) * np.sqrt(abs(val))) - mu_c) / sd_c
            zp = (pk - mu_p) / sd_p
            raw = blend * zc + (1.0 - blend) * zp
            overall = a + b * (raw - raw0)
            rows.append({
                "person_id": pid,
                "as_of": date.date().isoformat() if pd.notna(date) else None,
                "career_raa": float(val),
                "overall": round(float(np.clip(overall, 40.0, 99.9)), 1),
            })
    return pd.DataFrame(rows)


def run_model(
    bat: pd.DataFrame,
    bowl: pd.DataFrame,
    params: Params = DEFAULT_PARAMS,
    *,
    apply_opposition: bool = True,
    as_of=None,
) -> dict[str, pd.DataFrame]:
    """Full pipeline on already-loaded frames. Used by rebuild and by tests."""
    bat, bowl = prepare_lines(bat, bowl)
    if bat.empty:
        return {"innings": pd.DataFrame(), "players": pd.DataFrame(), "player_matches": pd.DataFrame(), "series": pd.DataFrame()}
    bat = attach_context(bat, params)
    if apply_opposition:
        bat, bowl = attach_opposition(bat, bowl, params)
    bat, bowl = score_raa(bat, bowl, params, apply_opposition=apply_opposition)
    pm = _combine_player_matches(bat, bowl)
    players = aggregate_players(pm, params)
    # Unadjusted career pile (global mean context, no opposition) for judgment 42.
    if apply_opposition and not bat.empty:
        era = _nanmed(bat["era_rpw"], 30.0) if "era_rpw" in bat else 30.0
        bat_u = bat.copy()
        bat_u["context_m"] = era if np.isfinite(era) and era > 0 else 30.0
        bat_u["attack_quality"] = 1.0
        bowl_u = bowl.copy()
        if not bowl_u.empty:
            bowl_u["batting_quality"] = 1.0
        bat_u, bowl_u = score_raa(bat_u, bowl_u, params, apply_opposition=False)
        pm_u = _combine_player_matches(bat_u, bowl_u)
        unadj = pm_u.groupby("person_id", sort=False)["raa"].sum().rename("career_raa_unadj")
        players = players.merge(unadj, on="person_id", how="left")
    players = calibrate(players, params)
    players = classify(players)
    qualified = qualify(players, params)
    qualified = compute_form(pm, qualified, params, as_of=as_of)
    qualified = scale_round(qualified)
    inn = innings_table(bat, bowl)
    series = rating_series(pm, qualified, params) if not qualified.empty else pd.DataFrame()
    return {
        "innings": inn,
        "players": qualified,
        "all_players": players,
        "player_matches": pm,
        "series": series,
        "params": params,
    }


def _write_df(name: str, df: pd.DataFrame) -> None:
    path = WAREHOUSE / f"{name}.parquet"
    if df is None or df.empty:
        write_parquet(name, [])
        return
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path, compression="zstd")


def rebuild(
    *,
    gender: str | None = None,
    params: Params = DEFAULT_PARAMS,
    exclude_teams: tuple[str, ...] = (),
    as_of: str | None = None,
) -> dict[str, Any]:
    """Score men's and women's Tests separately and write parquet."""
    if not warehouse_ready():
        raise RuntimeError("Warehouse not built yet.")
    genders = (gender,) if gender in {"male", "female"} else ("male", "female")
    player_parts = []
    inn_parts = []
    series_parts = []
    pm_parts = []
    print(f"Test RAA {TEST_VALUE_VERSION}", flush=True)
    for g in genders:
        print(f"  scoring {g} Tests…", flush=True)
        bat, bowl, _matches = load_test_frames(gender=g, exclude_teams=exclude_teams, as_of=as_of)
        if bat.empty:
            print(f"    no {g} Test innings", flush=True)
            continue
        model = run_model(bat, bowl, params, as_of=as_of)
        players = model["players"]
        if not players.empty:
            players = players.copy()
            players["gender"] = g
            player_parts.append(players)
        if not model["innings"].empty:
            inn_parts.append(model["innings"])
        if not model["series"].empty:
            series_parts.append(model["series"])
        if not model["player_matches"].empty:
            pm_parts.append(model["player_matches"])
        print(f"    {len(players):,} qualified {g} players", flush=True)
    players = pd.concat(player_parts, ignore_index=True) if player_parts else pd.DataFrame()
    innings = pd.concat(inn_parts, ignore_index=True) if inn_parts else pd.DataFrame()
    series = pd.concat(series_parts, ignore_index=True) if series_parts else pd.DataFrame()
    _write_df("test_ratings", players)
    _write_df("test_innings_raa", innings)
    _write_df("test_rating_series", series)
    meta = {
        "version": TEST_VALUE_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "params": asdict(params),
        "players": int(len(players)),
        "innings": int(len(innings)),
        "exclude_teams": list(exclude_teams),
    }
    (WAREHOUSE / "test_value_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Test RAA written: {len(players):,} players, {len(innings):,} innings", flush=True)
    return meta


def ratings_ready() -> bool:
    return (WAREHOUSE / "test_ratings.parquet").exists()


def load_ratings(con=None) -> pd.DataFrame:
    own = con is None
    if own:
        con = connect()
    try:
        if not ratings_ready():
            return pd.DataFrame()
        return con.execute("SELECT * FROM test_ratings").fetchdf()
    finally:
        if own:
            con.close()
