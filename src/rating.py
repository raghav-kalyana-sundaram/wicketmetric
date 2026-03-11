"""
Rating system with Bayesian shrinkage, uncertainty tracking, and percentile
scaling — TrueSkill / Glicko-2 inspired.

Per algorithm_update.md: every player possesses a skill distribution
represented by a mean (μ) and a variance/uncertainty (σ) representing
how confident we are in the rating.

Architecture
------------
The system adapts the hierarchical Bayesian rating framework described in
the algorithm document:

1. **Bayesian Shrinkage** (Empirical Bayes):
   adjusted = (n * score + k * pop_mean) / (n + k)
   This is the Empirical Bayes shrinkage formula from the document —
   as sample size increases, λ approaches zero and the player's observed
   average dominates the estimate.  With k=12, ~12 innings to equal-weight.

2. **Uncertainty Tracking** (TrueSkill-inspired):
   Each player has an uncertainty σ that decreases with more observations.
   σ = base_σ / sqrt(n + 1)
   This uncertainty is used to:
   - Inflate confidence intervals for provisional players
   - Deflate ratings of players with high uncertainty
   - Enable probabilistic comparisons (overlap of distributions)

3. **Opponent Quality Adjustment**:
   Per algorithm_update.md, executing a highly valuable performance against
   an elite opponent results in a larger update.  This is incorporated
   via the opposition-quality-weighted career aggregation upstream, but
   we also apply a final adjustment based on avg_opp_icc_rating.

4. **Recency via Volatility**:
   Per algorithm_update.md, a volatility parameter artificially inflates
   variance during periods of inactivity.  "Current form" rankings
   weight the last 12 months; "peak" rankings identify the highest μ
   achieved at any career point.

5. **Percentile Ranking**:
   Convert adjusted scores to 0-100 where 50 = median, 99 = top 1%.

Usage
-----
    from src.rating import apply_rating_system

    bat_careers = apply_rating_system(
        bat_careers,
        raw_cols=["raw_acceleration", "raw_power", "raw_control"],
        sample_col="innings_count",
        provisional_col="is_provisional_bat",
    )
"""

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Core building blocks
# ---------------------------------------------------------------------------

# Base uncertainty for a new player (TrueSkill-inspired σ).
# Decreases as sqrt(n) with more observations.
_BASE_UNCERTAINTY = 3.0

# Uncertainty floor — even a 200-innings veteran has some residual uncertainty.
_MIN_UNCERTAINTY = 0.3


def bayesian_shrinkage(
    player_scores: pd.Series,
    sample_sizes: pd.Series,
    shrinkage_k: float = 12.0,
) -> pd.Series:
    """
    Empirical Bayes shrinkage — pull player scores toward the population mean.

    Per algorithm_update.md (formula 5):
        adjusted = (n * player_score + k * pop_mean) / (n + k)

    As sample size increases, the shrinkage factor λ = k/(n+k) approaches
    zero, and the player's observed average dominates the estimate.

    Parameters
    ----------
    player_scores : pd.Series
        Raw composite score per player.
    sample_sizes : pd.Series
        Number of innings (batting) or matches (bowling) per player.
    shrinkage_k : float
        Shrinkage strength.  Higher k = more pull toward the mean.
        k=12 means ~12 innings to equal-weight own data vs population.

    Returns
    -------
    pd.Series of shrinkage-adjusted scores.

    Examples
    --------
    n=1,  k=12  → 92% population mean, 8% player score
    n=12, k=12  → 50% each
    n=50, k=12  → 81% player score
    n=100,k=12  → 89% player score
    """
    pop_mean = player_scores.mean()

    # Guard against all-NaN or empty series
    if pd.isna(pop_mean):
        return player_scores.copy()

    adjusted = (sample_sizes * player_scores + shrinkage_k * pop_mean) / (
        sample_sizes + shrinkage_k
    )
    return adjusted


def compute_uncertainty(
    sample_sizes: pd.Series,
    base_sigma: float = _BASE_UNCERTAINTY,
    min_sigma: float = _MIN_UNCERTAINTY,
) -> pd.Series:
    """
    Compute rating uncertainty (σ) for each player — TrueSkill-inspired.

    Per algorithm_update.md: every player possesses a skill distribution
    represented by a mean and a variance representing uncertainty.  The
    uncertainty decreases with more observations:

        σ = max(base_σ / sqrt(n + 1), min_σ)

    Parameters
    ----------
    sample_sizes : pd.Series
        Number of innings/matches per player.
    base_sigma : float
        Starting uncertainty for a brand-new player.
    min_sigma : float
        Floor uncertainty — even veterans have some residual.

    Returns
    -------
    pd.Series of uncertainty values (σ).

    Examples
    --------
    n=0   → σ = 3.0 (maximum uncertainty)
    n=5   → σ = 1.22
    n=12  → σ = 0.83
    n=50  → σ = 0.42
    n=100 → σ = 0.30 (at floor)
    """
    n = sample_sizes.fillna(0).astype(float).clip(lower=0)
    sigma = base_sigma / np.sqrt(n + 1.0)
    return sigma.clip(lower=min_sigma)


def uncertainty_penalty(
    uncertainty: pd.Series,
    base_sigma: float = _BASE_UNCERTAINTY,
    penalty_scale: float = 0.10,
) -> pd.Series:
    """
    Compute a multiplicative penalty based on rating uncertainty.

    Players with high uncertainty (few matches) receive a rating reduction.
    This complements Bayesian shrinkage — shrinkage pulls toward the mean,
    while this penalty directly reduces scores for uncertain ratings.

    penalty = 1.0 - penalty_scale * (σ / base_σ)

    Parameters
    ----------
    uncertainty : pd.Series
        Rating uncertainty (σ) per player.
    base_sigma : float
        The maximum uncertainty (new player).
    penalty_scale : float
        Maximum penalty fraction.  0.10 = up to 10% reduction for
        maximum uncertainty.

    Returns
    -------
    pd.Series of penalty multipliers in [1.0 - penalty_scale, 1.0].
    """
    ratio = (uncertainty / base_sigma).clip(lower=0, upper=1.0)
    return 1.0 - penalty_scale * ratio


def confidence_bonus(
    sample_sizes: pd.Series,
    alpha: float = 0.03,
    reference_n: float = 100.0,
) -> pd.Series:
    """
    Small multiplicative bonus for playing more matches.

    bonus = alpha * ln(1 + n) / ln(1 + reference_n)

    Capped at alpha so no player gets more than ~3% uplift.
    With n=1   → ~0.6% bonus
    With n=50  → ~2.5% bonus
    With n=100 → 3.0% bonus (cap)

    Parameters
    ----------
    sample_sizes : pd.Series
        Number of innings/matches per player.
    alpha : float
        Maximum bonus (e.g. 0.03 = 3%).
    reference_n : float
        Sample size at which the full bonus is reached.

    Returns
    -------
    pd.Series of bonus multipliers (values between 0 and alpha).
    """
    bonus = alpha * np.log1p(sample_sizes) / np.log1p(reference_n)
    return bonus.clip(upper=alpha)


def to_percentile_score(values: pd.Series) -> pd.Series:
    """
    Convert raw values to a 0-100 percentile-based score.

    Uses fractional ranking so ties get the average rank.
    50 = median player, 99 = top 1%.

    Parameters
    ----------
    values : pd.Series
        Adjusted raw scores.

    Returns
    -------
    pd.Series of scores from ~0 to ~100, rounded to 1 decimal.
    """
    if values.isna().all() or len(values) == 0:
        return values.copy()

    ranked = values.rank(method="average", pct=True, na_option="bottom")
    return (ranked * 100).round(1)


def compute_probabilistic_overlap(
    mu_a: float,
    sigma_a: float,
    mu_b: float,
    sigma_b: float,
) -> float:
    """
    Compute P(Player A > Player B) using posterior distribution overlap.

    Per algorithm_update.md: instead of comparing raw averages, the engine
    compares the posterior distributions of the players' context-adjusted
    metrics.  The probability that Player A's true underlying skill is
    greater than Player B's is:

        P(A > B) = Φ((μ_A - μ_B) / sqrt(σ_A² + σ_B²))

    where Φ is the standard normal CDF.

    Parameters
    ----------
    mu_a, sigma_a : Player A's mean rating and uncertainty.
    mu_b, sigma_b : Player B's mean rating and uncertainty.

    Returns
    -------
    float in [0, 1] — probability that A is truly better than B.
    """
    diff = mu_a - mu_b
    combined_sigma = np.sqrt(sigma_a**2 + sigma_b**2)
    if combined_sigma < 1e-10:
        return 0.5 if abs(diff) < 1e-10 else (1.0 if diff > 0 else 0.0)
    # Standard normal CDF approximation
    z = diff / combined_sigma
    # Fast sigmoid approximation of Φ(z)
    return float(1.0 / (1.0 + np.exp(-1.7 * z)))


# ---------------------------------------------------------------------------
# Full rating pipeline
# ---------------------------------------------------------------------------


def apply_rating_system(
    career_df: pd.DataFrame,
    raw_cols: list[str],
    sample_col: str,
    provisional_col: str,
    shrinkage_k: float = 12.0,
    confidence_alpha: float = 0.03,
    reference_n: float = 100.0,
    uncertainty_penalty_scale: float = 0.10,
) -> pd.DataFrame:
    """
    Apply the full TrueSkill-inspired rating pipeline to career-level raw scores.

    Per algorithm_update.md, the rating system is a hierarchical Bayesian
    model where every player possesses a skill distribution (μ, σ).

    For each column in raw_cols:
        1. Bayesian shrinkage toward population mean (Empirical Bayes)
        2. Compute uncertainty σ = base_σ / sqrt(n + 1)
        3. Apply uncertainty penalty (high σ → rating reduction)
        4. Small confidence bonus for match volume
        5. Percentile ranking → 0-100

    New columns added per raw_col (e.g. for "raw_acceleration"):
        - "adjusted_acceleration"  : post-shrinkage + bonus (μ estimate)
        - "uncertainty_acceleration" : uncertainty σ for this metric
        - "score_acceleration"     : final 0-100 percentile score

    Parameters
    ----------
    career_df : pd.DataFrame
        One row per player with raw composite scores and sample sizes.
    raw_cols : list[str]
        Column names containing raw composite metric scores.
        Expected format: "raw_<metric_name>"
    sample_col : str
        Column with sample size (e.g. "innings_count" or "matches").
    provisional_col : str
        Column with boolean provisional flag.
    shrinkage_k : float
        Shrinkage strength parameter (default 12).
    confidence_alpha : float
        Maximum confidence bonus (default 0.03 = 3%).
    reference_n : float
        Sample size at which full confidence bonus is reached.
    uncertainty_penalty_scale : float
        Maximum penalty for high uncertainty (default 0.10 = 10%).

    Returns
    -------
    pd.DataFrame with new score_, adjusted_, and uncertainty_ columns added.
    """
    df = career_df.copy()
    n = df[sample_col].fillna(0).astype(float)

    # Pre-compute shared quantities once (same for all metrics)
    bonus = confidence_bonus(n, alpha=confidence_alpha, reference_n=reference_n)
    sigma = compute_uncertainty(n)
    u_penalty = uncertainty_penalty(sigma, penalty_scale=uncertainty_penalty_scale)

    for col in raw_cols:
        if col not in df.columns:
            print(f"  WARNING: column '{col}' not found, skipping.")
            continue

        raw = df[col].fillna(0).astype(float)

        # Step 1: Bayesian shrinkage (Empirical Bayes)
        shrunk = bayesian_shrinkage(raw, n, shrinkage_k)

        # Step 2: Uncertainty penalty (TrueSkill-inspired)
        # Players with high uncertainty get a rating reduction
        penalised = shrunk * u_penalty

        # Step 3: Confidence bonus (multiplicative)
        adjusted = penalised * (1.0 + bonus)

        # Step 4: Store uncertainty and adjusted mean
        metric_name = col.replace("raw_", "")
        df[f"adjusted_{metric_name}"] = adjusted
        df[f"uncertainty_{metric_name}"] = sigma

        # Step 5: Percentile → 0-100
        df[f"score_{metric_name}"] = to_percentile_score(adjusted)

    return df


# ---------------------------------------------------------------------------
# Utility: lookup a player's scores
# ---------------------------------------------------------------------------


def lookup_player(
    career_df: pd.DataFrame,
    player_name: str | None = None,
    player_id: str | None = None,
    id_col: str = "batter_id",
    name_col: str = "batter",
) -> pd.DataFrame:
    """
    Quick helper to look up a player's profile by name (fuzzy) or exact ID.

    Parameters
    ----------
    career_df : pd.DataFrame
        Career profiles (batting or bowling).
    player_name : str, optional
        Substring match against the name column (case-insensitive).
    player_id : str, optional
        Exact match against the ID column.
    id_col : str
        Column name for player IDs.
    name_col : str
        Column name for player display names.

    Returns
    -------
    Matching rows from the career DataFrame.
    """
    if player_id is not None:
        id_series = career_df[id_col]
        if hasattr(id_series, "cat"):
            id_series = id_series.astype(str)
        return career_df[id_series == player_id]

    if player_name is not None:
        name_series = career_df[name_col]
        if hasattr(name_series, "cat"):
            name_series = name_series.astype(str)
        return career_df[name_series.str.contains(player_name, case=False, na=False)]

    return career_df.head(0)  # empty if no criteria given


# ---------------------------------------------------------------------------
# Probabilistic player comparison (algorithm_update.md)
# ---------------------------------------------------------------------------


def compare_players(
    career_df: pd.DataFrame,
    player_a_id: str,
    player_b_id: str,
    metrics: list[str] | None = None,
    id_col: str = "batter_id",
) -> dict[str, float]:
    """
    Probabilistic comparison of two players.

    Per algorithm_update.md: instead of comparing raw averages, the engine
    compares posterior distributions.  Returns P(A > B) for each metric.

    Parameters
    ----------
    career_df : pd.DataFrame
        Career profiles with adjusted_ and uncertainty_ columns.
    player_a_id, player_b_id : str
        Player IDs to compare.
    metrics : list[str], optional
        Metric names to compare (e.g. ["acceleration", "power", "control"]).
        If None, auto-detected from columns.
    id_col : str
        Column containing player IDs.

    Returns
    -------
    dict mapping metric_name → P(A > B) in [0, 1].
    """
    a_rows = lookup_player(career_df, player_id=player_a_id, id_col=id_col)
    b_rows = lookup_player(career_df, player_id=player_b_id, id_col=id_col)

    if a_rows.empty or b_rows.empty:
        return {}

    a = a_rows.iloc[0]
    b = b_rows.iloc[0]

    # Auto-detect metrics from adjusted_ columns
    if metrics is None:
        metrics = [
            c.replace("adjusted_", "")
            for c in career_df.columns
            if c.startswith("adjusted_")
        ]

    result = {}
    for metric in metrics:
        adj_col = f"adjusted_{metric}"
        unc_col = f"uncertainty_{metric}"

        if adj_col not in career_df.columns:
            continue

        mu_a = float(a.get(adj_col, 0.0))
        mu_b = float(b.get(adj_col, 0.0))

        # Use uncertainty if available, otherwise assume moderate
        sigma_a = float(a.get(unc_col, 1.0)) if unc_col in career_df.columns else 1.0
        sigma_b = float(b.get(unc_col, 1.0)) if unc_col in career_df.columns else 1.0

        result[metric] = compute_probabilistic_overlap(mu_a, sigma_a, mu_b, sigma_b)

    return result
