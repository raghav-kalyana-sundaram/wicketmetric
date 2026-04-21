"""
Condition-Dependence Metrics — algorithm_update.md implementation.

Per the algorithm document:
    "Condition-Dependence Metrics address the 'flat-track bully' phenomenon.
    By introducing an interaction term in the mixed-effects regression models,
    the platform measures whether a player's performance disproportionately
    spikes in highly favorable conditions.  If a batter's WAR is heavily
    concentrated in matches with a pre-game par score above 180, and dips
    significantly when the par score is below 140, they receive a high
    Condition-Dependence tag.  This serves as a descriptive, objective
    metric rather than a simplistic insult label."

This module implements:

1. **Condition-Dependence Index (CDI)** for batters:
   Measures the correlation between a batter's per-innings performance
   residual (SR vs par) and the match's scoring environment difficulty.
   A high positive CDI means the player performs disproportionately well
   in easy conditions (flat-track bully).  A negative CDI means the
   player performs better in tough conditions (clutch performer).

2. **Condition-Dependence Index for bowlers**:
   Measures whether a bowler's economy vs par degrades disproportionately
   in high-scoring conditions (leaky in flat-track games) or holds firm.

3. **Condition tercile splits**:
   Groups matches into "easy", "neutral", "hard" terciles by match par SR
   and computes per-player stats in each tercile for detailed breakdowns.

4. **Condition-Dependence Tag**:
   Categorical label based on CDI magnitude and sign:
   - "Flat-Track Bully"  : CDI > +threshold
   - "Conditions-Proof"  : |CDI| <= threshold
   - "Tough-Track Star"  : CDI < -threshold

Integration
-----------
Called from ``main.py`` after match context and innings/spell extraction.
Outputs merge onto ``bat_careers`` / ``bowl_careers`` as additional columns.

Design
------
- All functions are pure: DataFrames in → DataFrames out, no side effects.
- Config values are resolved by the caller in ``main.py`` and passed as
  arguments; no direct config reads at module level (except defaults).
- Uses Pearson correlation and OLS-style interaction terms, NOT full
  mixed-effects regression (which would require statsmodels), to keep
  the dependency footprint minimal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────


def _decat(df: pd.DataFrame, cols: list[str]) -> None:
    """Convert categorical columns to plain strings (in-place)."""
    for c in cols:
        if c in df.columns and hasattr(df[c], "cat"):
            df[c] = df[c].astype(str)


def _pearson_corr(x: np.ndarray, y: np.ndarray) -> float:
    """
    Compute Pearson correlation between two 1-D arrays.

    Returns 0.0 if either array has zero variance or fewer than 3 valid
    observations (to avoid meaningless correlations from tiny samples).

    Uses the unbiased (N-1) denominator for both covariance and standard
    deviations so that perfectly linear data yields exactly ±1.0.
    """
    mask = np.isfinite(x) & np.isfinite(y)
    x_clean = x[mask]
    y_clean = y[mask]

    n = len(x_clean)
    if n < 3:
        return 0.0

    x_std = np.std(x_clean, ddof=1)
    y_std = np.std(y_clean, ddof=1)

    if x_std < 1e-12 or y_std < 1e-12:
        return 0.0

    # Unbiased sample covariance (ddof=1)
    cov = np.sum((x_clean - np.mean(x_clean)) * (y_clean - np.mean(y_clean))) / (n - 1)
    return float(cov / (x_std * y_std))


def _ols_interaction_coeff(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
) -> float:
    """
    Compute the coefficient of the interaction term x*z in predicting y.

    Model: y = β₀ + β₁·x + β₂·z + β₃·(x·z) + ε

    Returns β₃ (the interaction coefficient), which measures whether
    the effect of condition (z) on performance (y) varies with the
    player's baseline skill (x).

    Uses ordinary least-squares via the normal equation.  Returns 0.0
    if the system is under-determined or degenerate.
    """
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x_c = x[mask]
    y_c = y[mask]
    z_c = z[mask]

    if len(x_c) < 5:
        return 0.0

    ones = np.ones_like(x_c)
    interaction = x_c * z_c
    X = np.column_stack([ones, x_c, z_c, interaction])

    try:
        # Normal equation: β = (X'X)⁻¹ X'y
        XtX = X.T @ X
        Xty = X.T @ y_c
        beta = np.linalg.solve(XtX, Xty)
        return float(beta[3])  # interaction coefficient
    except np.linalg.LinAlgError:
        return 0.0


# ──────────────────────────────────────────────────────────────────────────
# 1. Batting Condition-Dependence Index
# ──────────────────────────────────────────────────────────────────────────


def compute_batting_condition_dependence(
    bat_innings: pd.DataFrame,
    match_ctx: pd.DataFrame,
    min_innings: int = 10,
    par_sr_col: str = "match_par_sr",
    performance_col: str = "acc_overall_sr",
) -> pd.DataFrame:
    """
    Compute a Condition-Dependence Index (CDI) for each batter.

    The CDI measures whether a batter's performance is disproportionately
    concentrated in matches with favourable (high par SR) conditions.

    Methodology
    -----------
    For each batter with at least ``min_innings`` innings:
      1. Merge match-level par SR onto each innings.
      2. Compute the Pearson correlation between per-innings performance
         (``performance_col``, typically SR vs par) and match par SR.
      3. A *positive* correlation means the batter does better in easier
         conditions — the "flat-track bully" signal.
      4. A *negative* correlation means the batter steps up in tough
         conditions.

    Parameters
    ----------
    bat_innings : pd.DataFrame
        Per-innings batting data (output of ``compute_batting_components()``).
        Must contain ``batter_id``, ``batter``, ``match_id``, and the
        ``performance_col``.
    match_ctx : pd.DataFrame
        Match-level context (one row per match).  Must contain ``match_id``
        and ``par_sr_col``.
    min_innings : int
        Minimum number of innings for a CDI to be computed.  Players with
        fewer innings get NaN.
    par_sr_col : str
        Column in ``match_ctx`` representing the scoring environment
        (higher = easier conditions).  Default ``match_par_sr``.
    performance_col : str
        Column in ``bat_innings`` representing the batter's per-innings
        performance residual (higher = better).  Default ``acc_overall_sr``
        which is SR − par SR, so positive = above par.

    Returns
    -------
    pd.DataFrame with columns:
        ``batter_id``, ``batter``,
        ``condition_dependence_index`` : float (Pearson r, clipped to [-1, 1]),
        ``condition_dependence_tag`` : str categorical label,
        ``condition_innings`` : int number of innings used,
        ``easy_sr_vs_par`` : float mean performance in top-tercile conditions,
        ``hard_sr_vs_par`` : float mean performance in bottom-tercile conditions,
        ``condition_spread`` : float (easy minus hard performance).
    """
    if bat_innings.empty or match_ctx.empty:
        return pd.DataFrame(
            columns=[
                "batter_id",
                "batter",
                "condition_dependence_index",
                "condition_dependence_tag",
                "condition_innings",
                "easy_sr_vs_par",
                "hard_sr_vs_par",
                "condition_spread",
            ]
        )

    bi = bat_innings.copy()
    mc = match_ctx.copy()
    _decat(bi, ["batter_id", "batter", "match_id"])
    _decat(mc, ["match_id"])

    # Merge match condition onto innings (skip if already present)
    if par_sr_col not in bi.columns:
        if par_sr_col not in mc.columns:
            return pd.DataFrame(
                columns=[
                    "batter_id",
                    "batter",
                    "condition_dependence_index",
                    "condition_dependence_tag",
                    "condition_innings",
                    "easy_sr_vs_par",
                    "hard_sr_vs_par",
                    "condition_spread",
                ]
            )

        merge_cols = ["match_id", par_sr_col]
        bi = bi.merge(
            mc[merge_cols].drop_duplicates("match_id"), on="match_id", how="left"
        )

    if performance_col not in bi.columns:
        return pd.DataFrame(
            columns=[
                "batter_id",
                "batter",
                "condition_dependence_index",
                "condition_dependence_tag",
                "condition_innings",
                "easy_sr_vs_par",
                "hard_sr_vs_par",
                "condition_spread",
            ]
        )

    # Drop rows where either the performance or par SR is missing
    bi = bi.dropna(subset=[performance_col, par_sr_col])

    # Compute condition terciles (across all matches in the dataset)
    tercile_boundaries = bi[par_sr_col].quantile([1 / 3, 2 / 3])
    low_cutoff = tercile_boundaries.iloc[0]
    high_cutoff = tercile_boundaries.iloc[1]

    bi["_condition_tercile"] = np.where(
        bi[par_sr_col] <= low_cutoff,
        "hard",
        np.where(bi[par_sr_col] >= high_cutoff, "easy", "neutral"),
    )

    # Per-batter CDI computation
    results = []

    for (bid, bname), group in bi.groupby(["batter_id", "batter"]):
        n = len(group)
        if n < min_innings:
            results.append(
                {
                    "batter_id": bid,
                    "batter": bname,
                    "condition_dependence_index": np.nan,
                    "condition_dependence_tag": np.nan,
                    "condition_innings": n,
                    "easy_sr_vs_par": np.nan,
                    "hard_sr_vs_par": np.nan,
                    "condition_spread": np.nan,
                }
            )
            continue

        # Pearson correlation between match par SR and performance
        perf = group[performance_col].values.astype(float)
        cond = group[par_sr_col].values.astype(float)
        cdi = _pearson_corr(cond, perf)

        # Tercile splits
        easy_perf = group.loc[
            group["_condition_tercile"] == "easy", performance_col
        ].mean()
        hard_perf = group.loc[
            group["_condition_tercile"] == "hard", performance_col
        ].mean()

        # Condition spread: easy performance minus hard performance
        # Positive = much better in easy conditions (flat-track bully signal)
        spread = (
            (easy_perf - hard_perf)
            if pd.notna(easy_perf) and pd.notna(hard_perf)
            else np.nan
        )

        # Tag assignment
        tag = _assign_condition_tag(cdi, spread)

        results.append(
            {
                "batter_id": bid,
                "batter": bname,
                "condition_dependence_index": round(cdi, 4),
                "condition_dependence_tag": tag,
                "condition_innings": n,
                "easy_sr_vs_par": round(easy_perf, 4)
                if pd.notna(easy_perf)
                else np.nan,
                "hard_sr_vs_par": round(hard_perf, 4)
                if pd.notna(hard_perf)
                else np.nan,
                "condition_spread": round(spread, 4) if pd.notna(spread) else np.nan,
            }
        )

    return pd.DataFrame(results)


# ──────────────────────────────────────────────────────────────────────────
# 2. Bowling Condition-Dependence Index
# ──────────────────────────────────────────────────────────────────────────


def compute_bowling_condition_dependence(
    bowl_spells: pd.DataFrame,
    match_ctx: pd.DataFrame,
    min_spells: int = 10,
    par_sr_col: str = "match_par_sr",
    performance_col: str = "acc_economy_vs_par",
) -> pd.DataFrame:
    """
    Compute a Condition-Dependence Index (CDI) for each bowler.

    For bowlers, a *negative* CDI means the bowler's performance degrades
    (economy worsens vs par) in high-scoring conditions — they "leak"
    on flat tracks.  A *positive* CDI means they hold firm or improve
    when conditions are tough.

    Note: ``acc_economy_vs_par`` is oriented so that higher = better for
    the bowler (lower economy vs par).  So the interpretation is the same:
    positive CDI = better in high-par-SR matches = leaks on flat tracks
    (INVERTED because higher par SR = easier batting conditions, and if
    a bowler's economy-vs-par IMPROVES when batting is easier, that
    signals they're actually tougher in those conditions).

    For clarity:
    - CDI > 0 → Performs relatively better when conditions are easy
      (this is unusual for bowlers — they may be getting helped by
      batting-heavy games providing wicket opportunities).
    - CDI < 0 → Performs relatively worse when conditions are easy
      (classic "flat-track leaker" — gets carted on good tracks).

    We invert the sign in the final tag so that:
    - Flat-Track Leaker = CDI < -threshold (worse economy vs par in easy games)
    - Conditions-Proof  = |CDI| <= threshold
    - Tough-Track Star  = CDI > +threshold

    Parameters
    ----------
    bowl_spells : pd.DataFrame
        Per-spell bowling data (output of ``compute_bowling_components()``).
    match_ctx : pd.DataFrame
        Match-level context (one row per match).
    min_spells : int
        Minimum spells for a CDI to be computed.
    par_sr_col : str
        Column in ``match_ctx`` representing the scoring environment.
    performance_col : str
        Column in ``bowl_spells`` representing the bowler's per-spell
        performance (higher = better).

    Returns
    -------
    pd.DataFrame with columns:
        ``bowler_id``, ``bowler``,
        ``condition_dependence_index_bowl`` : float,
        ``condition_dependence_tag_bowl`` : str,
        ``condition_spells`` : int,
        ``easy_econ_vs_par`` : float,
        ``hard_econ_vs_par`` : float,
        ``condition_spread_bowl`` : float.
    """
    empty_cols = [
        "bowler_id",
        "bowler",
        "condition_dependence_index_bowl",
        "condition_dependence_tag_bowl",
        "condition_spells",
        "easy_econ_vs_par",
        "hard_econ_vs_par",
        "condition_spread_bowl",
    ]

    if bowl_spells.empty or match_ctx.empty:
        return pd.DataFrame(columns=empty_cols)

    bs = bowl_spells.copy()
    mc = match_ctx.copy()
    _decat(bs, ["bowler_id", "bowler", "match_id"])
    _decat(mc, ["match_id"])

    if performance_col not in bs.columns:
        return pd.DataFrame(columns=empty_cols)

    # Merge match condition onto spells (skip if already present)
    if par_sr_col not in bs.columns:
        if par_sr_col not in mc.columns:
            return pd.DataFrame(columns=empty_cols)

        merge_cols = ["match_id", par_sr_col]
        bs = bs.merge(
            mc[merge_cols].drop_duplicates("match_id"), on="match_id", how="left"
        )

    bs = bs.dropna(subset=[performance_col, par_sr_col])

    # Condition terciles
    tercile_boundaries = bs[par_sr_col].quantile([1 / 3, 2 / 3])
    low_cutoff = tercile_boundaries.iloc[0]
    high_cutoff = tercile_boundaries.iloc[1]

    bs["_condition_tercile"] = np.where(
        bs[par_sr_col] <= low_cutoff,
        "hard",
        np.where(bs[par_sr_col] >= high_cutoff, "easy", "neutral"),
    )

    results = []

    for (bid, bname), group in bs.groupby(["bowler_id", "bowler"]):
        n = len(group)
        if n < min_spells:
            results.append(
                {
                    "bowler_id": bid,
                    "bowler": bname,
                    "condition_dependence_index_bowl": np.nan,
                    "condition_dependence_tag_bowl": np.nan,
                    "condition_spells": n,
                    "easy_econ_vs_par": np.nan,
                    "hard_econ_vs_par": np.nan,
                    "condition_spread_bowl": np.nan,
                }
            )
            continue

        perf = group[performance_col].values.astype(float)
        cond = group[par_sr_col].values.astype(float)
        cdi = _pearson_corr(cond, perf)

        easy_perf = group.loc[
            group["_condition_tercile"] == "easy", performance_col
        ].mean()
        hard_perf = group.loc[
            group["_condition_tercile"] == "hard", performance_col
        ].mean()

        spread = (
            (easy_perf - hard_perf)
            if pd.notna(easy_perf) and pd.notna(hard_perf)
            else np.nan
        )

        # For bowlers, a NEGATIVE spread means they do better in hard
        # conditions (their economy vs par improves at low-par venues).
        # We use the same tag logic but with bowling-appropriate labels.
        tag = _assign_bowling_condition_tag(cdi, spread)

        results.append(
            {
                "bowler_id": bid,
                "bowler": bname,
                "condition_dependence_index_bowl": round(cdi, 4),
                "condition_dependence_tag_bowl": tag,
                "condition_spells": n,
                "easy_econ_vs_par": (
                    round(easy_perf, 4) if pd.notna(easy_perf) else np.nan
                ),
                "hard_econ_vs_par": (
                    round(hard_perf, 4) if pd.notna(hard_perf) else np.nan
                ),
                "condition_spread_bowl": (
                    round(spread, 4) if pd.notna(spread) else np.nan
                ),
            }
        )

    return pd.DataFrame(results)


# ──────────────────────────────────────────────────────────────────────────
# 3. Condition tercile splits (detailed breakdown)
# ──────────────────────────────────────────────────────────────────────────


def compute_batting_condition_terciles(
    bat_innings: pd.DataFrame,
    match_ctx: pd.DataFrame,
    par_sr_col: str = "match_par_sr",
    min_innings_per_tercile: int = 3,
) -> pd.DataFrame:
    """
    Compute per-batter stats split by match condition tercile.

    Returns a long-form DataFrame with one row per (batter, tercile).
    Terciles are "hard" (bottom 33%), "neutral" (middle), "easy" (top 33%)
    based on ``par_sr_col``.

    Parameters
    ----------
    bat_innings : pd.DataFrame
        Per-innings batting data.
    match_ctx : pd.DataFrame
        Match-level context.
    par_sr_col : str
        Match condition column.
    min_innings_per_tercile : int
        Minimum innings in a tercile for stats to be reported.

    Returns
    -------
    pd.DataFrame with columns:
        ``batter_id``, ``batter``, ``condition_tercile``,
        ``tercile_innings``, ``tercile_avg_sr``, ``tercile_avg_runs``,
        ``tercile_avg_sr_vs_par``, ``tercile_boundary_pct``.
    """
    empty_cols = [
        "batter_id",
        "batter",
        "condition_tercile",
        "tercile_innings",
        "tercile_avg_sr",
        "tercile_avg_runs",
        "tercile_avg_sr_vs_par",
    ]

    if bat_innings.empty or match_ctx.empty:
        return pd.DataFrame(columns=empty_cols)

    bi = bat_innings.copy()
    mc = match_ctx.copy()
    _decat(bi, ["batter_id", "batter", "match_id"])
    _decat(mc, ["match_id"])

    # Merge match condition onto innings (skip if already present)
    if par_sr_col not in bi.columns:
        if par_sr_col not in mc.columns:
            return pd.DataFrame(columns=empty_cols)

        bi = bi.merge(
            mc[["match_id", par_sr_col]].drop_duplicates("match_id"),
            on="match_id",
            how="left",
        )
    bi = bi.dropna(subset=[par_sr_col])

    tercile_boundaries = bi[par_sr_col].quantile([1 / 3, 2 / 3])
    low_cutoff = tercile_boundaries.iloc[0]
    high_cutoff = tercile_boundaries.iloc[1]

    bi["condition_tercile"] = np.where(
        bi[par_sr_col] <= low_cutoff,
        "hard",
        np.where(bi[par_sr_col] >= high_cutoff, "easy", "neutral"),
    )

    # Determine which columns are available for aggregation
    has_sr = "acc_overall_sr" in bi.columns
    has_runs = "runs" in bi.columns

    agg_dict = {"tercile_innings": ("match_id", "nunique")}
    if has_sr:
        agg_dict["tercile_avg_sr_vs_par"] = ("acc_overall_sr", "mean")
    if has_runs:
        agg_dict["tercile_avg_runs"] = ("runs", "mean")

    # Compute raw SR per innings if balls column exists
    if "balls" in bi.columns and "runs" in bi.columns:
        bi["_raw_sr"] = np.where(
            bi["balls"] > 0, bi["runs"] / bi["balls"] * 100, np.nan
        )
        agg_dict["tercile_avg_sr"] = ("_raw_sr", "mean")

    grouped = (
        bi.groupby(["batter_id", "batter", "condition_tercile"])
        .agg(**agg_dict)
        .reset_index()
    )

    # Filter by minimum innings per tercile
    grouped = grouped[grouped["tercile_innings"] >= min_innings_per_tercile].copy()

    # Round
    for c in grouped.columns:
        if grouped[c].dtype in ("float64", "float32"):
            grouped[c] = grouped[c].round(3)

    return grouped


# ──────────────────────────────────────────────────────────────────────────
# 4. Tag assignment helpers
# ──────────────────────────────────────────────────────────────────────────

# Thresholds for condition-dependence tags.
# CDI is a Pearson correlation, so it's in [-1, 1].
# Spread is on the scale of the performance metric.
_CDI_THRESHOLD = 0.15  # Correlation threshold for tagging
_SPREAD_THRESHOLD = 0.05  # Minimum spread to confirm tag direction


def _assign_condition_tag(cdi: float, spread: float | None) -> str:
    """
    Assign a batting condition-dependence tag.

    Uses both the correlation (CDI) and the tercile spread as confirmation.
    Both must agree in direction for a strong tag.

    Parameters
    ----------
    cdi : float
        Condition-Dependence Index (Pearson r).  Positive = better in
        easy conditions.
    spread : float or None
        Easy performance minus hard performance.  Positive = better in
        easy conditions.

    Returns
    -------
    str : One of "Flat-Track Bully", "Conditions-Proof", "Tough-Track Star".
    """
    if abs(cdi) < _CDI_THRESHOLD:
        return "Conditions-Proof"

    if spread is None or not np.isfinite(spread):
        # Only CDI available — use it alone but with a higher threshold
        if cdi > _CDI_THRESHOLD * 1.5:
            return "Flat-Track Bully"
        elif cdi < -_CDI_THRESHOLD * 1.5:
            return "Tough-Track Star"
        return "Conditions-Proof"

    # Both CDI and spread agree
    if cdi > _CDI_THRESHOLD and spread > _SPREAD_THRESHOLD:
        return "Flat-Track Bully"
    elif cdi < -_CDI_THRESHOLD and spread < -_SPREAD_THRESHOLD:
        return "Tough-Track Star"

    return "Conditions-Proof"


def _assign_bowling_condition_tag(cdi: float, spread: float | None) -> str:
    """
    Assign a bowling condition-dependence tag.

    For bowlers, the interpretation is:
    - CDI > 0 with positive spread: bowler's economy_vs_par improves in
      easy conditions (unusual — may indicate they thrive when there's
      more to bowl at, or get wicket-taking opportunities).  Tag as
      "Conditions-Proof" unless extreme.
    - CDI < 0 with negative spread: bowler's economy_vs_par degrades in
      easy conditions — they get expensive on flat tracks.  Tag as
      "Flat-Track Leaker".
    - CDI > threshold with large positive spread: truly exceptional in
      easy conditions.  Tag as "Flat-Track Enforcer".

    Returns
    -------
    str : One of "Flat-Track Leaker", "Conditions-Proof", "Tough-Track Enforcer".
    """
    if abs(cdi) < _CDI_THRESHOLD:
        return "Conditions-Proof"

    if spread is None or not np.isfinite(spread):
        if cdi < -_CDI_THRESHOLD * 1.5:
            return "Flat-Track Leaker"
        elif cdi > _CDI_THRESHOLD * 1.5:
            return "Tough-Track Enforcer"
        return "Conditions-Proof"

    # Bowler-specific logic:
    # Negative CDI + negative spread = worse in easy conditions
    if cdi < -_CDI_THRESHOLD and spread < -_SPREAD_THRESHOLD:
        return "Flat-Track Leaker"
    # Positive CDI + positive spread = better in easy conditions (hold firm)
    elif cdi > _CDI_THRESHOLD and spread > _SPREAD_THRESHOLD:
        return "Tough-Track Enforcer"

    return "Conditions-Proof"


# ──────────────────────────────────────────────────────────────────────────
# 5. Convenience wrapper
# ──────────────────────────────────────────────────────────────────────────


def compute_all_condition_metrics(
    bat_innings: pd.DataFrame,
    bowl_spells: pd.DataFrame,
    match_ctx: pd.DataFrame,
    *,
    min_bat_innings: int = 10,
    min_bowl_spells: int = 10,
    par_sr_col: str = "match_par_sr",
    bat_performance_col: str = "acc_overall_sr",
    bowl_performance_col: str = "acc_economy_vs_par",
) -> dict[str, pd.DataFrame]:
    """
    Compute all condition-dependence metrics for batters and bowlers.

    Parameters
    ----------
    bat_innings : pd.DataFrame
        Per-innings batting data (output of ``compute_batting_components()``).
    bowl_spells : pd.DataFrame
        Per-spell bowling data (output of ``compute_bowling_components()``).
    match_ctx : pd.DataFrame
        Match-level context (one row per match).
    min_bat_innings : int
        Minimum batting innings for CDI computation.
    min_bowl_spells : int
        Minimum bowling spells for CDI computation.
    par_sr_col : str
        Column in ``match_ctx`` for scoring environment.
    bat_performance_col : str
        Batting performance metric column.
    bowl_performance_col : str
        Bowling performance metric column.

    Returns
    -------
    dict with keys:
        ``batting_condition`` : pd.DataFrame — CDI per batter
        ``bowling_condition`` : pd.DataFrame — CDI per bowler
        ``batting_terciles``  : pd.DataFrame — per-batter tercile splits
    """
    batting_cdi = compute_batting_condition_dependence(
        bat_innings,
        match_ctx,
        min_innings=min_bat_innings,
        par_sr_col=par_sr_col,
        performance_col=bat_performance_col,
    )

    bowling_cdi = compute_bowling_condition_dependence(
        bowl_spells,
        match_ctx,
        min_spells=min_bowl_spells,
        par_sr_col=par_sr_col,
        performance_col=bowl_performance_col,
    )

    batting_terciles = compute_batting_condition_terciles(
        bat_innings,
        match_ctx,
        par_sr_col=par_sr_col,
    )

    return {
        "batting_condition": batting_cdi,
        "bowling_condition": bowling_cdi,
        "batting_terciles": batting_terciles,
    }
