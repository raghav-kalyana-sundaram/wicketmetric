"""
Compute match-level and team-level context for normalizing player performances.

Key outputs
-----------
- match_par_sr   : Average strike rate across both innings (pitch / era context)
- innings_sr     : Per-innings strike rate
- team total     : Per-team total runs (for contribution %)
- boundary_rate  : Match-average boundary rate per legal ball
- dot_pct        : Match-average dot ball percentage

The two-layer context model:
  1. Match par  → "what was normal for this pitch on this day?"
  2. Team share → "how much did this player matter to their own team?"
This lets us correctly value 70(60) in a team total of 120 as elite even if
the match par was 150+.
"""

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Per-innings context
# ---------------------------------------------------------------------------


def compute_innings_context(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate delivery-level data to one row per (match, innings, batting_team).

    Columns produced
    ----------------
    total_runs, legal_balls, total_wickets, total_fours, total_sixes,
    dot_balls_bowler, total_deliveries, date, overs_bowled, run_rate,
    innings_sr, boundary_runs, boundary_pct, boundary_rate, dot_pct
    """
    grp = df.groupby(["match_id", "innings_num", "batting_team"])

    innings = grp.agg(
        total_runs=("total_runs", "sum"),
        legal_balls=("is_legal", "sum"),
        total_wickets=("is_wicket", "sum"),
        total_fours=("is_four", "sum"),
        total_sixes=("is_six", "sum"),
        dot_balls_bowler=("is_dot_bowler", "sum"),
        total_deliveries=("total_runs", "size"),  # includes wides/noballs
        date=("date", "first"),
    ).reset_index()

    # Overs bowled (legal balls only, so wides/noballs don't count)
    innings["overs_bowled"] = innings["legal_balls"] / 6.0

    # Run rate (runs per over)
    innings["run_rate"] = np.where(
        innings["overs_bowled"] > 0,
        innings["total_runs"] / innings["overs_bowled"],
        0.0,
    )

    # Innings strike rate (runs per 100 legal balls)
    innings["innings_sr"] = np.where(
        innings["legal_balls"] > 0,
        innings["total_runs"] / innings["legal_balls"] * 100.0,
        0.0,
    )

    # Boundary analysis
    innings["boundary_runs"] = innings["total_fours"] * 4 + innings["total_sixes"] * 6
    innings["boundary_pct"] = np.where(
        innings["total_runs"] > 0,
        innings["boundary_runs"] / innings["total_runs"],
        0.0,
    )
    innings["boundary_rate"] = np.where(
        innings["legal_balls"] > 0,
        (innings["total_fours"] + innings["total_sixes"]) / innings["legal_balls"],
        0.0,
    )

    # Dot ball percentage (bowler dots / legal balls)
    innings["dot_pct"] = np.where(
        innings["legal_balls"] > 0,
        innings["dot_balls_bowler"] / innings["legal_balls"],
        0.0,
    )

    return innings


# ---------------------------------------------------------------------------
# Per-match context
# ---------------------------------------------------------------------------


def compute_match_context(innings_ctx: pd.DataFrame) -> pd.DataFrame:
    """
    From innings-level context, compute match-level par metrics.

    match_par_sr = total runs across BOTH innings / total legal balls * 100.
    This is the single best proxy for "how easy was it to score on this pitch
    on this day" and automatically normalises across eras.
    """
    match = (
        innings_ctx.groupby("match_id")
        .agg(
            match_total_runs=("total_runs", "sum"),
            match_total_legal_balls=("legal_balls", "sum"),
            match_total_fours=("total_fours", "sum"),
            match_total_sixes=("total_sixes", "sum"),
            match_total_wickets=("total_wickets", "sum"),
            match_total_dot_balls=("dot_balls_bowler", "sum"),
            match_date=("date", "first"),
            num_innings=("innings_num", "nunique"),
        )
        .reset_index()
    )

    # Par strike rate (runs per 100 legal balls)
    match["match_par_sr"] = np.where(
        match["match_total_legal_balls"] > 0,
        match["match_total_runs"] / match["match_total_legal_balls"] * 100.0,
        0.0,
    )

    # Par run rate (runs per over)
    match["match_par_rr"] = np.where(
        match["match_total_legal_balls"] > 0,
        match["match_total_runs"] / (match["match_total_legal_balls"] / 6.0),
        0.0,
    )

    # Match-wide boundary rate (boundaries per legal ball)
    match["match_boundary_rate"] = np.where(
        match["match_total_legal_balls"] > 0,
        (match["match_total_fours"] + match["match_total_sixes"])
        / match["match_total_legal_balls"],
        0.0,
    )

    # Match-wide dot ball percentage
    match["match_dot_pct"] = np.where(
        match["match_total_legal_balls"] > 0,
        match["match_total_dot_balls"] / match["match_total_legal_balls"],
        0.0,
    )

    # Wickets per legal ball (useful for normalising bowling threat)
    match["match_wickets_per_ball"] = np.where(
        match["match_total_legal_balls"] > 0,
        match["match_total_wickets"] / match["match_total_legal_balls"],
        0.0,
    )

    return match


# ---------------------------------------------------------------------------
# Per-innings bowler economy (for "economy vs other bowlers" computation)
# ---------------------------------------------------------------------------


def compute_per_bowler_innings_economy(df: pd.DataFrame) -> pd.DataFrame:
    """
    For every bowler in every innings, compute their economy.
    Then compute the *other* bowlers' combined economy in the same innings.
    The difference tells us whether this bowler was better or worse than
    their teammates.

    Returns a DataFrame keyed on (match_id, innings_num, bowler_id) with:
        bowler_economy, other_bowlers_economy, economy_vs_others
    """
    grp = df.groupby(["match_id", "innings_num", "bowler_id"])
    per_bowler = grp.agg(
        bowler_runs=("total_runs", "sum"),
        bowler_legal_balls=("is_legal", "sum"),
    ).reset_index()

    per_bowler["bowler_overs"] = per_bowler["bowler_legal_balls"] / 6.0
    per_bowler["bowler_economy"] = np.where(
        per_bowler["bowler_overs"] > 0,
        per_bowler["bowler_runs"] / per_bowler["bowler_overs"],
        np.nan,
    )

    # Innings totals (all bowlers combined)
    innings_totals = (
        per_bowler.groupby(["match_id", "innings_num"])
        .agg(
            innings_total_runs=("bowler_runs", "sum"),
            innings_total_overs=("bowler_overs", "sum"),
        )
        .reset_index()
    )

    per_bowler = per_bowler.merge(
        innings_totals, on=["match_id", "innings_num"], how="left"
    )

    # Other bowlers = innings total minus this bowler
    other_runs = per_bowler["innings_total_runs"] - per_bowler["bowler_runs"]
    other_overs = per_bowler["innings_total_overs"] - per_bowler["bowler_overs"]
    per_bowler["other_bowlers_economy"] = np.where(
        other_overs > 0, other_runs / other_overs, per_bowler["bowler_economy"]
    )

    # Negative means better than others (lower economy)
    per_bowler["economy_vs_others"] = (
        per_bowler["bowler_economy"] - per_bowler["other_bowlers_economy"]
    )

    return per_bowler[
        [
            "match_id",
            "innings_num",
            "bowler_id",
            "bowler_economy",
            "bowler_overs",
            "other_bowlers_economy",
            "economy_vs_others",
        ]
    ]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_full_context(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build innings-level and match-level context DataFrames, then merge
    match-level par back onto innings context so downstream code can just
    join on (match_id, innings_num, batting_team).

    Returns
    -------
    innings_ctx : pd.DataFrame
        One row per (match, innings, batting_team) with match_par columns.
    match_ctx : pd.DataFrame
        One row per match with aggregate stats.
    """
    innings_ctx = compute_innings_context(df)
    match_ctx = compute_match_context(innings_ctx)

    # Merge match-level par onto innings context
    merge_cols = [
        "match_id",
        "match_par_sr",
        "match_par_rr",
        "match_boundary_rate",
        "match_dot_pct",
        "match_wickets_per_ball",
    ]
    innings_ctx = innings_ctx.merge(
        match_ctx[merge_cols],
        on="match_id",
        how="left",
    )

    return innings_ctx, match_ctx
