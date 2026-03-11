# Cricket Metrics — Version 0.2 Feature Roadmap

> **Goal:** Transform the statistical engine into a fan-facing product.
> Every feature below is grounded in the existing codebase and data structures.

---

## Implementation Progress

| # | Feature | Status | Date | Notes |
|---|---------|--------|------|-------|
| 1 | Grades (Translation Layer) | ✅ **Done** | 2025-06-17 | `src/presentation.py` created. Grades (S/A+/A/B+/B/C+/C/D), overall score with superstar bonus, integrated into CSV + spot-checks. 49 tests. |
| 2 | Archetypes & Badges | ✅ **Done** | 2025-06-17 | 7 batting + 5 bowling archetypes in `src/presentation.py`. First-match-wins, `_max` suffix convention, "Utility Player" fallback. 49 tests (shared with Feature 1). |
| 12 | Expose AWQ (Wicket Value) | ✅ **Done** | 2025-06-17 | `avg_wicket_quality_mean` and `bowled_lbw_pct` added to `bowling_profiles.csv`. Zero-cost — was already computed internally. |
| — | Config keys (all features) | ✅ **Done** | 2025-06-17 | All v0.2 config sections added to `config.yaml` and `_DEFAULTS` in `config.py`. |
| 6 | Chase Master Index | ✅ **Done** | 2025-06-18 | `compute_chase_splits()` in `src/batting.py`. Setting vs chasing splits, `chase_master_index`, `bat_first_index`, `chase_master_full` (includes control). Min-innings filter. Merged onto `bat_careers` in `main.py`. 37 tests (shared with Features 8 & 11). |
| 11 | Anchor Cost / Balls-to-Par | ✅ **Done** | 2025-06-18 | Per-delivery cumulative SR tracking in `extract_batting_innings`. `balls_to_par` per innings, `avg_balls_to_par` and `anchor_cost_ratio` at career level. Added to CSV output + spot-checks. 37 tests (shared). |
| 8 | Selfless / Stat-Padder Index | ✅ **Done** | 2025-06-18 | Milestone approach zone SRs (40-49 for fifty, 90-99 for century) in `extract_batting_innings`. `selfless_fifty`, `selfless_century`, and combined `selfless_index` at career level. Weighted 0.7/0.3 (fifty/century). 37 tests (shared). |
| 13 | Form Tracker (Time-Series) | ✅ **Done** | 2025-06-19 | `src/form_tracker.py` created (444 lines). Rolling-window batting & bowling form series — one row per (player, match_date) with windowed Acceleration, Power, Control proxies + composite score. Configurable window size and min_window. Outputs `batting_form_series.parquet` and `bowling_form_series.parquet`. Convenience `compute_form_series()` for both at once. 69 tests (shared with Features 5 & 7). |
| 5 | Peak vs Current Ratings | ✅ **Done** | 2025-06-19 | `src/peak_ratings.py` created (661 lines). Two approaches: (1) **Simple peak** — recency-free career aggregate via `compute_peak_ratings()` / `compute_peak_ratings_bowl()`, divides out `recency_weight` from `opp_quality_weight` to preserve opposition/team adjustments. (2) **Sliding-window peak** — `compute_sliding_peak()` / `compute_sliding_peak_bowl()` with two-pointer O(N) scan over date-sorted innings, finds best 2-year window. Both batting + bowling. Merged onto `bat_careers`/`bowl_careers`, added to CSV output. 69 tests (shared). |
| 7 | Player Similarity Engine | ✅ **Done** | 2025-06-19 | `src/similarity.py` created (548 lines). Cosine similarity on z-normalised career component vectors (17 batting features, 16 bowling features + optional supplementary cols). Pure NumPy — no sklearn dependency. `compute_batting_similarity()` / `compute_bowling_similarity()` return long-form top-K comps; `pivot_similarity_wide()` reshapes for CSV. Supports within-group filtering (`position_group` / `phase_group`). Min-innings threshold for comp targets. Outputs `batting_similarities.parquet`, `bowling_similarities.parquet`, plus wide-form CSVs. 69 tests (shared). |
| 9 | Venue & Pitch Difficulty | ✅ **Done** | 2025-06-20 | `src/venue.py` created (710 lines). Per-venue difficulty baselines from match context (`compute_venue_baselines()`), normalised difficulty score (positive = harder). **Flat Track Bully Index** — Pearson correlation of SR-vs-par × venue difficulty at career level (batting + bowling). Venue-adjusted performance composite (±30% cap). Enrichment helpers to propagate `venue` from deliveries onto match context and innings DataFrames. Convenience `compute_all_venue_metrics()` wrapper. Merged `flat_track_index`, `flat_track_index_bowl`, `venue_adjusted_composite` onto career DataFrames. Outputs `venue_baselines.parquet`. 93 tests (shared with Features 14 & 15). |
| 14 | Positional WAR | ✅ **Done** | 2025-06-20 | `src/war.py` created (595 lines). Batting WAR within `position_group`, bowling WAR within `phase_group`. Replacement level = configurable percentile (default 25th) within each group; fallback to population for small groups (<5 players). Value above replacement clipped at 0, scaled by log-volume factor (`log1p(innings)/log1p(50)`). Per-component WAR (`war_acceleration`, `war_power`, `war_control` / `war_accuracy`, `war_control`, `war_threat`) + combined `war_batting` / `war_bowling`. WAR rate metrics (`war_batting_rate`, `war_bowling_rate`). Leaderboard generators + position/phase value summary tables. 93 tests (shared). |
| 15 | Era-Adjusted Ratings | ✅ **Done** | 2025-06-20 | `src/era.py` created (758 lines). Per-year era baselines from match context with configurable rolling-window smoothing (default 3-year centered). Era multipliers relative to most recent year — multiplier > 1.0 boosts historical performances. Clamped to [0.70, 1.60]. `apply_era_adjustment_to_innings()` adjusts batting components; `apply_era_adjustment_to_bowling()` applies inverse multiplier for bowling. `compute_era_summary()` for human-readable table. `compute_era_adjusted_career_composite()` for standalone post-hoc composite. Convenience `compute_all_era_metrics()` wrapper. Disabled by default (`era_adjustment.enabled: false`). Outputs `era_baselines.parquet`, `era_summary.csv`. 93 tests (shared). |
| 3 | Clutch / Pressure Index | ✅ **Done** | 2025-06-20 | `src/clutch.py` created (932 lines). Delivery-level pressure tagging: high required run rate (>9 RPO), powerplay collapse (3+ wickets), knockout matches (final/semi-final/eliminator/qualifier), deep chase (>50% of target remaining in last 8 overs). Bowling pressure: defending low total (≤140), death-overs close chase (margin ≤30, over 16+). Innings/spell-level aggregation with 30% threshold + knockout override. **Batting Clutch Index** — pressure composite minus normal composite (weighted by opp_quality_weight); uses acc_overall_sr, acc_impact, ctrl_scoring_consistency, ctrl_contribution. **Bowling Clutch Index** — same approach with acc_economy_vs_par, acc_dot_pct, wickets. `clutch_sr_delta` for pure SR-based interpretation. Configurable thresholds via `clutch.*` config keys. Convenience `compute_all_clutch_metrics()` wrapper. Merged `clutch_index`, `clutch_sr_delta`, `pressure_innings` onto `bat_careers`; `clutch_index_bowl`, `pressure_spells` onto `bowl_careers`. Added to CSV output + spot-check printout. 66 tests in `tests/test_v02_phase4.py`. |
| 4 | Head-to-Head Matchups | ✅ **Done** | 2025-06-21 | `src/matchups.py` created (754 lines). Delivery-level batter × bowler matchup aggregation with phase-level breakdowns. **Dominance Index** — composite measure (SR premium + boundary bonus − dot penalty − dismissal rate); positive = batter dominates, negative = bowler dominates. Bowler dismissals tracked separately from run-outs. Optional bowling-style matchups via external lookup (Cricsheet JSON does not include bowling style). Player-centric views: `find_batter_nemeses()`, `find_bowler_bunnies()`, `find_batter_dominant_matchups()`. Career-level summaries: `compute_matchup_diversity_stats()` (unique bowlers, avg dominance, pct dominant, matchup consistency), `compute_bowler_matchup_summary()`. Pivot helpers for single-player profile pages. Convenience `compute_all_matchup_metrics()` wrapper. Configurable via `matchups.*` config keys (min_balls, top_k_bunnies, top_k_dominant). Merged `avg_dominance`, `pct_dominant`, `matchup_consistency` onto `bat_careers`; `avg_dominance_bowl`, `pct_dominant_bowl` onto `bowl_careers`. Outputs `matchups.parquet`, `matchups_by_phase.parquet`. Added to CSV output + spot-check printout. 81 tests in `tests/test_v02_phase5.py` (shared with Feature 10). |
| 10 | Win Probability Added (WPA) | ✅ **Done** | 2025-06-21 | `src/wpa.py` created (970 lines). Empirical win-probability models for both innings: **2nd innings** — lookup by (over, wickets, score_ratio_bucket) with Laplace smoothing; **1st innings** — lookup by (over, wickets, rr_ratio_bucket) using historical par-score baselines. Delivery-level WPA scoring via row-by-row (`compute_delivery_wpa()`) and vectorised (`compute_delivery_wpa_vectorised()`) implementations with multi-level fallback for sparse buckets. Terminal state handling: chase completion → WP 1.0, all out → WP 0.0. Career batting WPA: `career_wpa_bat`, `wpa_per_match_bat`, `positive_wpa_bat`, `negative_wpa_bat`, `clutch_wpa_pct_bat`. Career bowling WPA: sign-flipped so positive = good bowler; `career_wpa_bowl`, `wpa_per_match_bowl`. Match-level WPA summary with ball-by-ball timeline for visualisation. Configurable via `wpa.*` config keys (enabled, score_ratio_buckets, rr_ratio_buckets). Disabled by default (`wpa.enabled: false`) due to computational cost. Convenience `compute_all_wpa_metrics()` wrapper. Merged `career_wpa_bat`, `wpa_per_match_bat` onto `bat_careers`; `career_wpa_bowl`, `wpa_per_match_bowl` onto `bowl_careers`. Outputs `wpa_batting.parquet`, `wpa_bowling.parquet`. 81 tests in `tests/test_v02_phase5.py` (shared with Feature 4). |
| 16 | Bowl First / Bowl Second Index | ✅ **Done** | 2025-03-10 | `compute_bowling_innings_splits()` added to `src/bowling.py` (183 lines). Bowling equivalent of Chase Master Index — splits bowler career into bowling-first (restricting unknown total, innings 1) and bowling-second (defending set target, innings 2) spells. Composite performance score per innings type using economy_vs_par (35%), dot_pct (20%), wickets_per_spell (15%), bowling_rv (15%), ctrl_vs_others (15%). `bowl_first_index` = first composite − second composite (positive = better restricting); `bowl_second_index` = inverse. Min-spells-per-type filter (configurable, default 5). Merged `bowl_first_index`, `bowl_second_index`, `bowl_first_avg_econ_vs_par`, `bowl_second_avg_econ_vs_par`, `bowl_first_avg_dot_pct`, `bowl_second_avg_dot_pct`, `bowl_first_wickets_per_spell`, `bowl_second_wickets_per_spell` onto `bowl_careers`. Configurable via `bowl_splits.*` config keys. 15 tests in `tests/test_v02_phase6.py` (shared with Features 17 & 18). |
| 17 | Condition-Dependence Metrics | ✅ **Done** | 2025-03-10 | `src/condition.py` created (756 lines). Per algorithm_update.md: measures whether a player's performance disproportionately spikes in favorable conditions. **Batting CDI** — Pearson correlation between per-innings SR-vs-par and match par SR; positive = flat-track bully, negative = tough-track star. **Bowling CDI** — same approach for economy_vs_par; negative CDI = flat-track leaker. **Condition tercile splits** — "easy"/"neutral"/"hard" terciles by match par SR with per-player stats in each. **Condition tags**: "Flat-Track Bully", "Conditions-Proof", "Tough-Track Star" (batting) / "Flat-Track Leaker", "Conditions-Proof", "Tough-Track Enforcer" (bowling) — requires both CDI and tercile spread to agree for strong tags. OLS interaction coefficient helper for future mixed-effects integration. Convenience `compute_all_condition_metrics()` wrapper. Merged `condition_dependence_index`, `condition_dependence_tag`, `condition_spread` onto `bat_careers`; `condition_dependence_index_bowl`, `condition_dependence_tag_bowl`, `condition_spread_bowl` onto `bowl_careers`. Outputs `batting_condition_terciles.parquet`. Configurable via `condition_dependence.*` config keys. 45 tests in `tests/test_v02_phase6.py` (shared). |
| 18 | Bayesian Matchup Shrinkage | ✅ **Done** | 2025-03-10 | Enhanced `src/matchups.py` (+439 lines). Per algorithm_update.md §Matchup Modeling: applies Empirical Bayes shrinkage to sparse head-to-head matchup data, regressing toward broader archetype baselines. `compute_archetype_baselines()` — computes batter-vs-bowler-archetype and bowler-vs-batter-archetype dominance priors weighted by balls faced. `apply_bayesian_matchup_shrinkage()` — blends observed dominance with archetype prior using λ = k/(n+k) where k = configurable shrinkage_balls (default 30). With 6 balls: 83% prior; with 30 balls: 50/50; with 120 balls: 80% observed. Falls back to batter's global average dominance when archetype data unavailable. `project_unseen_matchup()` — projects matchup values for encounters that have never occurred using archetype-level signals. Added `matchup_confidence` to base matchup output (n/(n+k)). `bayesian_dominance`, `archetype_prior`, `shrinkage_applied` columns added to matchup DataFrames. Configurable via `matchup_shrinkage.*` config keys. 34 tests in `tests/test_v02_phase6.py` (shared). |

### Files Changed So Far

| File | Change |
|------|--------|
| `src/matchups.py` | **Created + Modified.** Head-to-Head Matchup Analysis (1209 lines). Original: Delivery-level batter × bowler aggregation, phase breakdowns, dominance index, bowling-style matchups (external lookup), player-centric views (nemeses, bunnies, dominant matchups), career diversity stats, bowler summary, pivot helpers. `compute_matchups()`, `find_batter_nemeses()`, `find_bowler_bunnies()`, `find_batter_dominant_matchups()`, `compute_matchup_diversity_stats()`, `compute_bowler_matchup_summary()`, `pivot_matchup_summary_for_batter()`, `pivot_matchup_summary_for_bowler()`, `compute_all_matchup_metrics()`. **Phase 6 additions:** `compute_archetype_baselines()`, `apply_bayesian_matchup_shrinkage()`, `project_unseen_matchup()` — Bayesian Empirical Bayes shrinkage of matchup dominance toward archetype priors; `matchup_confidence` column in base output. |
| `src/wpa.py` | **Created.** Win Probability Added (970 lines). Empirical WP models for 1st and 2nd innings, delivery-level WPA scoring (row-by-row + vectorised), career batting/bowling WPA aggregation, match-level WPA summary with timeline. `build_second_innings_wp_model()`, `build_first_innings_wp_model()`, `compute_delivery_wpa()`, `compute_delivery_wpa_vectorised()`, `aggregate_batting_wpa()`, `aggregate_bowling_wpa()`, `compute_match_wpa_summary()`, `compute_all_wpa_metrics()`. |
| `tests/test_v02_phase5.py` | **Created.** 81 tests covering matchup aggregation (basic, min_balls filter, multiple players, dismissals, wides, dominance index), phase matchups, bowling-style matchups, batter nemeses / bowler bunnies / dominant matchups, matchup diversity stats, bowler summary, pivot helpers, convenience wrapper, WP model building (2nd + 1st innings, Laplace smoothing, empty/edge cases), delivery-level WPA (column presence, win prob range, chase completion terminal), vectorised WPA, batting/bowling WPA aggregation (positive/negative split, clutch pct, per-match, sign convention), match WPA summary, WPA convenience wrapper (vectorised/non-vectorised, configurable buckets), edge cases (single delivery, no target, no winner, all zeros, categorical cols, fallback lookups), bucketisation, cross-feature integration. |
| `src/clutch.py` | **Created.** Clutch / Pressure Index — delivery-level pressure tagging (batting + bowling), innings/spell aggregation, batting & bowling clutch index computation (932 lines). `tag_pressure_deliveries()`, `tag_bowling_pressure_deliveries()`, `aggregate_pressure_to_innings()`, `aggregate_pressure_to_spells()`, `compute_clutch_index()`, `compute_bowling_clutch_index()`, `compute_all_clutch_metrics()`. |
| `tests/test_v02_phase4.py` | **Created.** 66 tests covering pressure tagging (high RRR, collapse, knockout, deep chase), bowling pressure (low defend, death close), innings/spell aggregation, batting clutch index (clutch player, choker, equal performance, min threshold, multiple batters, SR delta, opp quality weight), bowling clutch index, convenience wrapper, edge cases (single delivery, NaN target, categorical columns, boundary conditions). |
| `src/condition.py` | **Created.** Condition-Dependence Metrics (756 lines). Pearson correlation-based CDI for batters and bowlers, OLS interaction coefficient helper, condition tercile splits, tag assignment logic ("Flat-Track Bully" / "Conditions-Proof" / "Tough-Track Star" for batting; "Flat-Track Leaker" / "Conditions-Proof" / "Tough-Track Enforcer" for bowling). `_pearson_corr()`, `_ols_interaction_coeff()`, `compute_batting_condition_dependence()`, `compute_bowling_condition_dependence()`, `compute_batting_condition_terciles()`, `compute_all_condition_metrics()`. |
| `src/bowling.py` | **Modified.** Added `compute_bowling_innings_splits()` (183 lines) — Bowl First / Bowl Second Index with composite performance scoring per innings type. Config constants `BOWL_SPLITS_ENABLED`, `BOWL_SPLITS_MIN_SPELLS`. |
| `tests/test_v02_phase6.py` | **Created.** 94 tests covering Bowl First/Second Index (basic splits, positive indices, negatives, min_spells filter, single/missing innings, multiple bowlers, empty/categorical/NaN handling, wickets_per_spell, rounding), Condition-Dependence (_pearson_corr perfect/zero/NaN, _ols_interaction, tag assignment batting + bowling, CDI computation flat-track/tough-track/min filter/spread/multiple batters/valid range, bowling CDI, tercile splits, convenience wrapper, custom cols), Bayesian Matchup Shrinkage (archetype baselines, shrinkage factor range, balls-vs-shrinkage relationship, bayesian-between-observed-and-prior, bowler/batter archetypes, empty/categorical handling, global fallback, extreme k values, matchup confidence, project_unseen_matchup archetype/global/unknown), edge cases (single spell, constant par SR, constant performance, column preservation, row count), cross-feature integration. |
| `src/main.py` | **Modified.** Added imports for `compute_bowling_innings_splits`, `compute_all_condition_metrics`, `apply_bayesian_matchup_shrinkage`. Steps 7k2 (Bowl Splits), 7l2 (Bayesian Matchup Shrinkage), 7n (Condition-Dependence Metrics). Expanded CSV columns with `bowl_first_index`, `bowl_second_index`, `condition_dependence_index`, `condition_dependence_tag`, `condition_spread`, `condition_dependence_index_bowl`, `condition_dependence_tag_bowl`, `condition_spread_bowl`. `batting_condition_terciles.parquet` output. Return dict includes `batting_condition`, `bowling_condition`, `batting_terciles`. |
| `src/config.py` | **Modified.** Added `bowl_splits`, `condition_dependence`, and `matchup_shrinkage` sections to `_DEFAULTS` dict. |
| `config.yaml` | **Modified.** Added `bowl_splits` (enabled, min_spells_per_type), `condition_dependence` (enabled, min_bat_innings, min_bowl_spells, par_sr_col, bat_performance_col, bowl_performance_col), `matchup_shrinkage` (enabled, shrinkage_balls) config sections. |


| File | Change |
|------|--------|
| `src/presentation.py` | **Created.** Grades translation layer + archetype assignment (374 lines). |
| `src/form_tracker.py` | **Created.** Rolling-window form tracker for batting and bowling time-series (444 lines). `compute_batting_form_series()`, `compute_bowling_form_series()`, `compute_form_series()`. |
| `src/peak_ratings.py` | **Created.** Peak vs Current ratings — recency-free aggregate + sliding-window peak (661 lines). `compute_peak_ratings()`, `compute_peak_ratings_bowl()`, `compute_sliding_peak()`, `compute_sliding_peak_bowl()`. |
| `src/similarity.py` | **Created.** Player Similarity Engine — cosine similarity on normalised component vectors (548 lines). `compute_batting_similarity()`, `compute_bowling_similarity()`, `pivot_similarity_wide()`. |
| `tests/test_presentation.py` | **Created.** 49 tests covering grades, overall scores, archetypes, edge cases (590 lines). |
| `tests/test_v02_phase2.py` | **Created.** 37 tests covering Chase Master Index, Anchor Cost, and Selfless Index — per-innings extraction, career aggregation, edge cases. |
| `tests/test_v02_phase3.py` | **Created.** 69 tests covering Form Tracker (batting/bowling series, window sizing, min_window, composites, edge cases), Peak Ratings (simple recency-free, sliding window, bowling, weight handling, thresholds), Similarity Engine (cosine matrix, batting/bowling comps, pivot wide, within-group, supplementary cols, edge cases), and cross-feature integration. |
| `src/venue.py` | **Created.** Venue & Pitch Difficulty — baselines, flat track bully index (batting + bowling), venue-adjusted performance, enrichment helpers (710 lines). `compute_venue_baselines()`, `compute_flat_track_index()`, `compute_bowling_flat_track_index()`, `compute_venue_adjusted_performance()`, `enrich_match_context_with_venue()`, `enrich_innings_with_venue()`, `compute_all_venue_metrics()`. |
| `src/war.py` | **Created.** Positional WAR — batting WAR within position_group, bowling WAR within phase_group (595 lines). `compute_batting_war()`, `compute_bowling_war()`, `compute_batting_war_rate()`, `compute_bowling_war_rate()`, `war_batting_leaderboard()`, `war_bowling_leaderboard()`, `compute_position_value_summary()`, `compute_phase_value_summary()`. |
| `src/era.py` | **Created.** Era-Adjusted Ratings — yearly baselines, rolling-smoothed multipliers, innings/spell adjustment (758 lines). `compute_era_baselines()`, `apply_era_adjustment_to_innings()`, `apply_era_adjustment_to_bowling()`, `compute_era_summary()`, `get_era_multiplier()`, `compute_era_adjusted_career_composite()`, `compute_all_era_metrics()`. |
| `tests/test_v02_phase3b.py` | **Created.** 93 tests covering Venue (baselines, difficulty scoring, flat track index batting + bowling, venue-adjusted performance, enrichment helpers, convenience wrapper, edge cases), WAR (batting + bowling WAR, volume scaling, replacement levels, leaderboards, rate metrics, position/phase summaries, edge cases), Era (baselines, smoothing, multipliers, innings adjustment batting + bowling, summary, lookup, career composite, convenience wrapper, edge cases), and cross-feature integration. |
| `src/batting.py` | **Modified.** Added cumulative SR tracking, `balls_to_par` (Anchor Cost), milestone approach zone SRs (Selfless Index) in `extract_batting_innings`; career aggregation for `avg_balls_to_par`, `anchor_cost_ratio`, `selfless_fifty`, `selfless_century`, `selfless_index` in `aggregate_batting_careers`; new `compute_chase_splits()` function; config constants for Features 6, 8, 11. |
| `src/main.py` | **Modified.** Imports for `form_tracker`, `peak_ratings`, `similarity`, `venue`, `war`, `era`, `clutch`, `matchups`, `wpa` modules; Step 7c (Chase Master merge), 7d (Anchor Cost & Selfless status), 7e (Peak Ratings — simple + sliding window, bat + bowl), 7f (Similarity Engine — bat + bowl), 7g (Form Tracker — bat + bowl series), 7h (Venue & Pitch Difficulty — baselines + flat track index bat/bowl + venue-adjusted composite), 7i (Positional WAR — batting + bowling WAR + rate metrics), 7j (Era-Adjusted Ratings — baselines + summary), 7k (Clutch / Pressure Index — batting + bowling clutch index), 7l (Head-to-Head Matchups — batter × bowler matchups + phase breakdowns + diversity stats merged onto careers), 7m (Win Probability Added — WP model building + delivery scoring + career batting/bowling WPA merged onto careers); expanded CSV columns with `flat_track_index`, `venue_adjusted_composite`, `war_batting`, `war_batting_rate`, `clutch_index`, `clutch_sr_delta`, `pressure_innings`, `flat_track_index_bowl`, `war_bowling`, `war_bowling_rate`, `clutch_index_bowl`, `pressure_spells`, `avg_dominance`, `pct_dominant`, `matchup_consistency`, `avg_dominance_bowl`, `pct_dominant_bowl`, `career_wpa_bat`, `wpa_per_match_bat`, `career_wpa_bowl`, `wpa_per_match_bowl`; matchups + WPA parquet outputs; dominance + WPA in spot-check printout; return dict includes `venue_baselines`, `era_baselines`, `era_summary`, `batting_clutch`, `bowling_clutch`, `matchups`, `matchups_by_phase`, `batter_diversity`, `bowler_matchup_summary`, `wpa_batting`, `wpa_bowling`. |
| `src/config.py` | **Modified.** Added all v0.2 feature defaults to `_DEFAULTS` dict, including `matchups` (min_balls, min_balls_phase, top_k_bunnies, top_k_dominant) and expanded `wpa` (rr_ratio_buckets). |
| `config.yaml` | **Modified.** Added all v0.2 config sections (presentation, clutch, chase_master, similarity, selfless, venue, matchups, wpa, anchor_cost, form_tracker, war, era_adjustment). |

---

## Table of Contents

1. [Translation Layer (Grades)](#1-translation-layer-z-scores--fan-grades)
2. [Player Archetypes & Badges](#2-player-archetypes--badges)
3. [Clutch / Pressure Index](#3-clutch--pressure-index)
4. [Head-to-Head & Matchup Analysis](#4-head-to-head--matchup-analysis)
5. [Peak vs Current Ratings](#5-peak-vs-current-ratings)
6. [Chase Master Index](#6-chase-master-index-innings-1-vs-2-splits)
7. [Player Similarity Engine](#7-player-similarity-engine-comps)
8. [Selfless vs Stat-Padder Index](#8-selfless-vs-stat-padder-index-milestone-context)
9. [Venue & Pitch Difficulty Adjustment](#9-venue--pitch-difficulty-adjustment-flat-track-bully-check)
10. [Win Probability Added (WPA)](#10-win-probability-added-wpa--leverage-multiplier)
11. [Anchor Cost / Balls-to-Par](#11-anchor-cost--innings-trajectory-metric)
12. [Explicit Wicket Value (AWQ)](#12-explicit-wicket-value-for-bowlers-top-order-menace)
13. [Form Tracker (Time-Series)](#13-form-tracker--rolling-averages-time-series-outputs)
14. [Positional WAR](#14-positional-war-wins-above-replacement)
15. [Era-Adjusted Ratings](#15-era-adjusted-ratings-cross-generational-harmonization)
16. [Implementation Priority Matrix](#16-implementation-priority-matrix)

---

## 1. Translation Layer: Z-Scores → Fan Grades

> ✅ **IMPLEMENTED** — `src/presentation.py` (grades + overall score with superstar bonus), integrated in `main.py` Step 7b. 49 tests in `tests/test_presentation.py`.

### The Concept

The pipeline outputs statistical measures like z-scores and context-normalised rates. Fans generally don't intuitively grasp a "1.85 Z-score." A presentation layer that maps percentile scores to one single score would be great. However, that single score shouldn't just be an average. If one player is so much better than everyone else at a particular skill, they should get a higher grade. 

### Why Fans Care

Letter grades are the language of video games (FIFA, NBA 2K, etc.) and school report cards — universally understood. A grade summary like **"Kohli: 97.5 / A+"** is immediately shareable on social media.

### Where It Hooks In

After `apply_rating_system()` in `main.py` (Step 6), scores are already 0–100 percentiles via `to_percentile_score()` in `rating.py`. This feature adds a labelling layer on top.

### Implementation

Created `src/presentation.py` with:

- `score_to_grade()` — maps 0-100 score to letter grade using configurable boundaries
- `_compute_overall_score()` — single overall score with **superstar bonus** (not a simple average; elite dimensions pull the overall up)
- `add_batting_grades()` — adds `grade_acceleration`, `grade_power`, `grade_control`, `overall_score`, `overall_grade`
- `add_bowling_grades()` — adds `grade_accuracy`, `grade_control`, `grade_threat`, `overall_score`, `overall_grade`

Grade boundaries are configurable via `presentation.grade_boundaries` in `config.yaml`.

### Integration in `main.py`

`add_batting_grades()` and `add_bowling_grades()` are called in Step 7b (after all gates/scaling), before writing CSVs. The `grade_*`, `overall_score`, `overall_grade` columns are included in `bat_csv_cols` and `bowl_csv_cols`. Spot-check output also shows overall score, grade, and archetype.

## 2. Player Archetypes & Badges

> ✅ **IMPLEMENTED** — `assign_batting_archetypes()` and `assign_bowling_archetypes()` in `src/presentation.py`. Integrated in `main.py` Step 7b. Tests in `tests/test_presentation.py`.

### The Concept

Use the existing granular components (`timing_factor`, `boundary_pct`, `acc_sr_growth`, etc.) to automatically tag players with recognizable **Archetypes** or **Badges**:

- *High Timing + High Control* = **"Classic Anchor"**
- *Extreme Power + High Death SR* = **"Explosive Finisher"**
- *High Powerplay Dot Penalty evasion + High Impact* = **"Pinch Hitter"**

### Why Fans Care

This creates immediate, shareable narratives. Fans can debate whether a player's archetype tag matches their "eye test." It also helps fans unfamiliar with a player instantly understand their style.

### Where It Hooks In

After grades, still in `src/presentation.py`. Uses the already-computed final `score_acceleration`, `score_power`, `score_control` columns.

### Implementation

Added to `src/presentation.py`:

```python
# Archetype definitions: (name, conditions_dict)
# Conditions are: metric >= threshold (or metric_max <= threshold for caps)
BATTING_ARCHETYPES = [
    ("Explosive Finisher",  {"acceleration": 85, "power": 85}),
    ("Power Anchor",        {"power": 75, "control": 75}),
    ("Classic Anchor",      {"control": 80, "acceleration_max": 55}),
    ("Pinch Hitter",        {"acceleration": 85, "control_max": 45}),
    ("All-Round Elite",     {"acceleration": 75, "power": 70, "control": 70}),
    ("Strike Rotator",      {"control": 80, "power_max": 40}),
    ("Accumulator",         {"control": 70, "acceleration_max": 50, "power_max": 50}),
]

BOWLING_ARCHETYPES = [
    ("Death Specialist",    {"accuracy": 75, "control": 75, "threat": 70}),
    ("Spin Restrictor",     {"accuracy": 80, "threat_max": 55}),
    ("Strike Bowler",       {"threat": 80}),
    ("Economical",          {"accuracy": 80, "control": 75, "threat_max": 50}),
    ("All-Round Threat",    {"accuracy": 70, "control": 70, "threat": 70}),
]




### Design Notes

- Archetype order matters — first match wins — so the most specific / elite profiles come first.
- The `_max` suffix convention allows capping: `"acceleration_max": 55` means the player must have ACC ≤ 55.
- "Utility Player" is the fallback for players who don't fit any specific mold.
- Uses the *already-computed final 0–100 scores*, so it is zero-cost on the pipeline and just adds a column.

### Expected Output

| Player | Archetype |
|--------|-----------|
| GJ Maxwell | Explosive Finisher |
| V Kohli | Classic Anchor |
| JC Buttler | All-Round Elite |
| SA Yadav | Power Anchor |

---

## 3. Clutch / Pressure Index

> ✅ **IMPLEMENTED** — `src/clutch.py` (932 lines), integrated in `main.py` Step 7k. 66 tests in `tests/test_v02_phase4.py`.

### The Concept

A "Clutch Index" that filters the `Delivery DataFrame` for high-leverage situations: knockout tournament matches, chasing a high required run rate (e.g., >9 RPO), or batting with a collapsed top order (3+ wickets down inside the powerplay). It answers: **who performs when it matters most?**

### Why Fans Care

Fans obsess over who is "clutch." This metric settles debates like "Is Kohli a big-match player?" or "Does Dhoni really finish games?" by putting hard numbers behind the narrative.

### Where It Hooks In

Requires filtering at the *delivery level* before `extract_batting_innings`. The parser already captures `innings_num`, `team_score_before`, `team_wickets_before`, `target_runs`, `event_name`, and `winner`.

### Implementation

Created `src/clutch.py` (932 lines) with a full pressure-tagging and clutch-index pipeline:

**Step 1 — Tag high-leverage deliveries** (`tag_pressure_deliveries()`):
- `is_pressure_high_rrr` — chasing with required run rate > 9 RPO (configurable)
- `is_pressure_collapse` — 3+ wickets down in the powerplay (configurable)
- `is_pressure_knockout` — event name contains "final", "semi-final", "eliminator", "qualifier", etc. (case-insensitive)
- `is_pressure_deep_chase` — innings 2, last 8 overs, >50% of target remaining
- `is_pressure` — any of the above

**Step 1b — Bowling-specific pressure** (`tag_bowling_pressure_deliveries()`):
- `is_pressure_low_defend` — defending ≤140 in innings 2
- `is_pressure_death_close` — death overs (16+) of a close chase (margin ≤30)
- `is_bowl_pressure` — any bowling flag OR knockout

**Step 2 — Aggregate to innings/spell level** (`aggregate_pressure_to_innings()`, `aggregate_pressure_to_spells()`):
- An innings is "pressure" if >30% of balls faced were pressure OR it's a knockout match
- Same logic for bowling spells

**Step 3 — Compute Clutch Index** (`compute_clutch_index()`, `compute_bowling_clutch_index()`):
- Batting composite: 0.40×acc_overall_sr + 0.25×acc_impact + 0.20×ctrl_scoring_consistency + 0.15×ctrl_contribution
- Bowling composite: 0.35×acc_economy_vs_par + 0.30×acc_dot_pct + 0.35×wickets
- Uses `opp_quality_weight` for weighted means within each condition
- `clutch_index = pressure_composite − normal_composite` (positive = clutch)
- `clutch_sr_delta` — pure SR-based difference for easier interpretation
- Requires minimum pressure innings (configurable, default 5) to avoid small-sample noise

**Convenience wrapper:** `compute_all_clutch_metrics()` runs the full pipeline in one call.

### Integration in `main.py`

`compute_all_clutch_metrics()` is called in Step 7k. Batting clutch columns (`clutch_index`, `clutch_sr_delta`, `pressure_innings`) merged onto `bat_careers`; bowling clutch columns (`clutch_index_bowl`, `pressure_spells`) merged onto `bowl_careers`. Added to CSV output and spot-check printout. Return dict includes `batting_clutch` and `bowling_clutch` DataFrames.

### Expected Output

| Player | Pressure Inn | Clutch Index | Interpretation |
|--------|-------------|--------------|----------------|
| MS Dhoni | 34 | +0.42 | Significantly better under pressure |
| V Kohli | 41 | +0.28 | Elevates in clutch |
| RG Sharma| 22 | −0.15 | Slightly worse under pressure |

---

## 4. Head-to-Head & Matchup Analysis

> ✅ **IMPLEMENTED** — `src/matchups.py` created (754 lines). Delivery-level batter × bowler matchup aggregation with phase breakdowns and dominance index. Optional bowling-style matchups via external lookup. Player-centric views (nemeses, bunnies, dominant matchups), career diversity stats, bowler summary. Convenience `compute_all_matchup_metrics()` wrapper. Configurable via `matchups.*` config keys. Merged `avg_dominance`, `pct_dominant`, `matchup_consistency` onto `bat_careers`; `avg_dominance_bowl`, `pct_dominant_bowl` onto `bowl_careers`. Outputs `matchups.parquet`, `matchups_by_phase.parquet`. 81 tests in `tests/test_v02_phase5.py` (shared with Feature 10).

### The Concept

Generate a `matchups.parquet` output that groups by `batter_id` + `bowler_id` (and optionally by `bowling_style` or `phase`). This answers "How does Virat Kohli actually fare against left-arm spin in the middle overs?"

### Why Fans Care

Matchup analysis is one of the most common fan discussions. "Who is Bumrah's bunny?" and "Who dominates Rashid Khan?" are questions every fan asks.

### Where It Hooks In

The `Delivery DataFrame` already contains `batter_id`, `bowler_id`, and `phase` for every ball. The main gap is `bowling_style` — not currently parsed.


Output as `matchups.parquet` in the output directory.

### Enhancement: Adding Bowling Style

Cricsheet JSON contains player info in the `registry` or `players` section. If bowling style is available:

1. Add a `bowling_style` field to each delivery row in `parser.py`.
2. Group matchups by `batter_id × bowling_style × phase` for questions like "Kohli vs Left-Arm Orthodox in middle overs."

If Cricsheet doesn't include bowling style, join against an external lookup (ESPNCricinfo player IDs → bowling style). This is the only feature that requires an external data source.

### Phase-Specific Matchups

For an even richer analysis without bowling style:

```python
# Add phase dimension
phase_matchup = faced.groupby(
    ["batter_id", "batter", "bowler_id", "bowler", "phase"]
).agg(...)
```

This answers "Does Kohli struggle against Bumrah specifically in the death overs?"

---

## 5. Peak vs Current Ratings

> ✅ **IMPLEMENTED** — `src/peak_ratings.py` created (661 lines). Two approaches: (1) Simple recency-free career aggregate via `compute_peak_ratings()` / `compute_peak_ratings_bowl()` — divides out `recency_weight` from `opp_quality_weight`. (2) Sliding-window peak via `compute_sliding_peak()` / `compute_sliding_peak_bowl()` — two-pointer O(N) scan finds best 2-year window. Both bat + bowl. `peak_composite_batting`, `peak_window_composite`, `peak_composite_bowling` added to CSVs. 69 tests in `tests/test_v02_phase3.py`.

### The Concept

Output two distinct rating sets for players: **Current Rating** (with the existing strong recency decay) and **Peak Rating** (a rolling 2-year window of their highest-ever rating, without recency decay). This allows fans to compare "Peak AB de Villiers" against "Current Suryakumar Yadav."

### Why Fans Care

"All-Time Great" discussions require fair cross-era comparison. A retired player's "current" rating will naturally decay to nothing, but their *peak* tells you how dominant they were.

### Where It Hooks In

The recency weighting already exists in `extract_batting_innings` (around line 1296). The key is that `recency_weight` is a separate column that gets multiplied into `opp_quality_weight`.

### Implementation

**Approach 1 — Simple (Full-Career Non-Recency):**

```python
def compute_peak_ratings(bat_components: pd.DataFrame, min_innings: int = 10):
    """
    Re-aggregate career stats WITHOUT recency weighting to produce
    'all-time' or 'peak' ratings alongside the recency-weighted 'current' ratings.
    """
    bc = bat_components.copy()

    # Remove recency decay by dividing it out of the combined weight
    if "recency_weight" in bc.columns and "opp_quality_weight" in bc.columns:
        recency = bc["recency_weight"].clip(lower=0.001)
        bc["opp_quality_weight"] = bc["opp_quality_weight"] / recency

    # Re-aggregate with the recency-free weights
    peak_careers = aggregate_batting_careers(bc, min_innings=min_innings)

    # Rename columns to distinguish from current ratings
    for metric in ["raw_acceleration", "raw_power", "raw_control"]:
        peak_careers = peak_careers.rename(columns={metric: f"peak_{metric}"})

    return peak_careers[["batter_id", "batter", "peak_raw_acceleration",
                         "peak_raw_power", "peak_raw_control"]]
```

**Approach 2 — Sliding Window (True Peak):**

For each player, iterate over date-sorted innings and compute a rolling 2-year window aggregate. Find the window that produces the highest composite score. This is more computationally expensive but gives a true "peak."

```python
def compute_sliding_peak(
    bat_components: pd.DataFrame,
    window_days: int = 730,  # 2 years
) -> pd.DataFrame:
    """Find each player's best 2-year window."""
    bc = bat_components.sort_values(["batter_id", "date"])
    results = []

    for batter_id, player_df in bc.groupby("batter_id"):
        if len(player_df) < 10:
            continue

        dates = pd.to_datetime(player_df["date"])
        best_composite = -np.inf
        best_window_end = None

        for i in range(len(player_df)):
            end_date = dates.iloc[i]
            start_date = end_date - pd.Timedelta(days=window_days)
            window = player_df[(dates >= start_date) & (dates <= end_date)]

            if len(window) < 5:
                continue

            # Quick composite: mean of key components
            composite = (
                window["acc_overall_sr"].mean()
                + window["pow_boundary_pct"].mean()
                + window["ctrl_scoring_consistency"].mean()
            )
            if composite > best_composite:
                best_composite = composite
                best_window_end = end_date

        if best_window_end is not None:
            results.append({
                "batter_id": batter_id,
                "batter": player_df.iloc[0]["batter"],
                "peak_window_end": best_window_end,
                "peak_composite": best_composite,
            })

    return pd.DataFrame(results)
```

### Integration

Merge `peak_*` columns back onto `bat_careers`. Add `peak_acceleration`, `peak_power`, `peak_control` to the CSV output alongside the existing `score_acceleration`, etc.

---

## 6. Chase Master Index (Innings 1 vs 2 Splits)

> ✅ **IMPLEMENTED** — `compute_chase_splits()` in `src/batting.py`. Setting/chasing splits with `chase_master_index`, `bat_first_index`, `chase_master_full`. Min-innings filter. Merged onto `bat_careers` in `main.py`. 37 tests in `tests/test_v02_phase2.py`.

### The Concept

Cricket completely changes depending on whether a team is setting a target or chasing one. Fans constantly debate who the ultimate "Chase Master" is (e.g., Virat Kohli, MS Dhoni, Michael Bevan). A simple split of career stats by innings number tells the story.

### Why Fans Care

It settles the debate of who can handle scoreboard pressure versus who only scores freely when setting a target without a required run rate.

### Where It Hooks In

`extract_batting_innings` already groups by `innings_num`. Every row of `bat_components` already carries `innings_num`.

### Implementation

```python
def compute_chase_splits(bat_components: pd.DataFrame) -> pd.DataFrame:
    """Compute setting vs chasing career splits per batter."""
    bc = bat_components.copy()

    for c in ["batter_id", "batter"]:
        if hasattr(bc[c], "cat"):
            bc[c] = bc[c].astype(str)

    # Setting = innings_num 1, Chasing = innings_num 2
    setting = bc[bc["innings_num"] == 1]
    chasing = bc[bc["innings_num"] == 2]

    def _agg_composite(sub_df, prefix):
        """Quick SR-vs-par and impact composite for a subset."""
        grp = sub_df.groupby(["batter_id", "batter"]).agg(
            inn=("match_id", "nunique"),
            avg_sr_vs_par=("acc_overall_sr", "mean"),
            avg_impact=("acc_impact", "mean"),
            avg_runs=("runs", "mean"),
            avg_control=("ctrl_scoring_consistency", "mean"),
        ).reset_index()
        grp = grp.rename(columns={
            c: f"{prefix}_{c}" for c in ["inn", "avg_sr_vs_par", "avg_impact",
                                          "avg_runs", "avg_control"]
        })
        return grp

    set_agg = _agg_composite(setting, "setting")
    chase_agg = _agg_composite(chasing, "chasing")

    splits = set_agg.merge(chase_agg, on=["batter_id", "batter"], how="outer")

    # Chase Master Index = chasing composite - setting composite
    # Positive = better when chasing
    splits["chase_master_index"] = (
        splits["chasing_avg_sr_vs_par"].fillna(0)
        - splits["setting_avg_sr_vs_par"].fillna(0)
    )

    # Also compute a more nuanced version including control
    splits["chase_master_full"] = (
        (splits["chasing_avg_sr_vs_par"].fillna(0) - splits["setting_avg_sr_vs_par"].fillna(0))
        + 0.5 * (splits["chasing_avg_control"].fillna(0) - splits["setting_avg_control"].fillna(0))
    )

    return splits
```

### Integration

Merge `chase_master_index` back onto `bat_careers` as a single column. Add to CSV output. This is extremely lightweight because `innings_num` is already in the data — just a conditional split before aggregation. Include a bat first index as well, essentially the chase_master_index but for batting first innings.

### Expected Output

| Player | Setting Inn | Chasing Inn | Chase Master Index | Interpretation |
|--------|------------|-------------|-------------------|----------------|
| V Kohli | 52 | 47 | +0.18 | Better when chasing |
| RG Sharma | 48 | 43 | −0.05 | Roughly equal |
| MS Dhoni | 30 | 38 | +0.35 | Significantly better chasing |

---

## 7. Player Similarity Engine ("Comps")

> ✅ **IMPLEMENTED** — `src/similarity.py` created (548 lines). Cosine similarity on z-normalised career component vectors (17 batting features, 16 bowling features + optional supplementary cols like selfless/anchor/chase). Pure NumPy — no sklearn. `compute_batting_similarity()` / `compute_bowling_similarity()` return long-form top-K comps; `pivot_similarity_wide()` reshapes for CSV. Within-group filtering (`position_group` / `phase_group`) supported. Min-innings threshold for comp targets. Outputs `batting_similarities.parquet`, `bowling_similarities.parquet`, wide-form CSVs. 69 tests in `tests/test_v02_phase3.py`.

### The Concept

When a new prospect emerges or a team buys an unknown player in the IPL auction, fans immediately ask: "Who does he play like?" This engine calculates **Cosine Similarity** between players' normalised component vectors and outputs the Top 3 statistical matches. Consider things like how they pace their innings, shot slection, strike rate, etc. 

### Why Fans Care

It provides an immediate mental model for unknown players. "Statistically, his profile is a 92% match to a young Suryakumar Yadav" generates massive hype and context.

### Where It Hooks In

After `aggregate_batting_careers` produces the z-scored component means. The normalised component vectors already exist in the career DataFrame.



### Integration

Call from `main.py` after career aggregation. Output as `player_similarities.parquet` and optionally `player_similarities.csv`. The `sklearn` dependency is lightweight; alternatively, use `numpy` dot products directly if you want to avoid the dependency.

### Expected Output

| Player | Comp 1 | Similarity | Comp 2 | Similarity | Comp 3 | Similarity |
|--------|--------|-----------|--------|-----------|--------|-----------|
| SA Yadav | AB de Villiers | 91.2% | GJ Maxwell | 88.7% | DA Warner | 85.1% |

---

## 8. Selfless vs Stat-Padder Index (Milestone Context)

> ✅ **IMPLEMENTED** — Milestone approach zone SRs (40–49 for fifty, 90–99 for century) computed in `extract_batting_innings`. Career-level `selfless_fifty`, `selfless_century`, and combined `selfless_index` (0.7/0.3 weighting) in `aggregate_batting_careers`. 37 tests in `tests/test_v02_phase2.py`.

### The Concept

One of the most toxic but popular fan debates in modern T20s is whether a player slows down to achieve personal milestones (50s or 100s) to the detriment of the team. This metric tracks a batter's Strike Rate in specific run-brackets (40–49 approaching 50, 90–99 approaching 100) compared to their overall SR.

### Why Fans Care

Validating the "eye test" of players getting "bogged down in the 40s" is a highly viral, debate-sparking metric. It quantifies something fans *feel* but can't prove.

### Where It Hooks In

Requires ball-by-ball tracking of cumulative batter runs, which can be derived from the `Delivery DataFrame`. The parser already tracks `batter_runs` per delivery.

### Implementation

Inside `extract_batting_innings`, after computing phase splits:

```python
# Add cumulative batter score tracking
faced_sorted["cum_batter_runs"] = faced_sorted.groupby(
    ["match_id", "innings_num", "batter_id"], observed=True
)["batter_runs"].cumsum()

# The score BEFORE this delivery (for zone classification)
faced_sorted["score_before_ball"] = (
    faced_sorted["cum_batter_runs"] - faced_sorted["batter_runs"]
)

# Define milestone approach zones
for zone_name, zone_min, zone_max in [
    ("fifty_approach", 40, 49),
    ("century_approach", 90, 99),
]:
    zone_mask = (
        (faced_sorted["score_before_ball"] >= zone_min)
        & (faced_sorted["score_before_ball"] <= zone_max)
    )
    zone_df = faced_sorted[zone_mask]
    zone_agg = zone_df.groupby(
        ["match_id", "innings_num", "batter_id"], observed=True
    ).agg(
        **{
            f"{zone_name}_balls": ("batter_runs", "size"),
            f"{zone_name}_runs": ("batter_runs", "sum"),
        }
    ).reset_index()

    zone_agg[f"{zone_name}_sr"] = np.where(
        zone_agg[f"{zone_name}_balls"] >= 3,
        zone_agg[f"{zone_name}_runs"] / zone_agg[f"{zone_name}_balls"] * 100,
        np.nan,
    )
    agg = agg.merge(
        zone_agg, on=["match_id", "innings_num", "batter_id"], how="left"
    )
```

At the career level:

```python
# Selfless Index = milestone_approach_sr / career_overall_sr
# Ratio near 1.0 = consistent; below 0.8 = significant slowdown
career["fifty_approach_sr"] = grp["fifty_approach_sr"].mean()
career["selfless_index"] = career["fifty_approach_sr"] / career["career_sr"]
```

### Expected Output


## 9. Venue & Pitch Difficulty Adjustment ("Flat Track Bully" Check)

### The Concept

Fans often discount runs scored at high-altitude/small-boundary venues (like M. Chinnaswamy Stadium) or flat pitches compared to runs scored on turning/seaming tracks. A venue difficulty index normalises achievements.

### Why Fans Care

A 40(30) on a pitch where the average score is 120 is statistically more impressive than a 70(30) on a pitch where the average score is 220.

### Where It Hooks In

`parser.py` already parses `venue` into the delivery DataFrame. `context.py` computes `match_par_sr` per match. Aggregating `match_par_sr` by venue gives you venue baselines.

### Implementation

```python
def compute_venue_baselines(
    match_ctx: pd.DataFrame,
    min_matches: int = 5,
) -> pd.DataFrame:
    """
    Compute per-venue difficulty baselines from match context.

    venue_difficulty > 0 = harder than average (low-scoring venue)
    venue_difficulty < 0 = easier than average (high-scoring venue)
    """
    df = match_ctx.copy()
    df["year"] = pd.to_datetime(df["match_date"]).dt.year

    venue_stats = df.groupby("venue").agg(
        venue_matches=("match_id", "nunique"),
        venue_avg_par_sr=("match_par_sr", "mean"),
        venue_par_std=("match_par_sr", "std"),
        venue_avg_boundary_rate=("match_boundary_rate", "mean"),
    ).reset_index()

    # Global average for comparison
    global_avg_par = df["match_par_sr"].mean()

    # Difficulty: positive = harder than average, negative = easier
    venue_stats["venue_difficulty"] = (
        global_avg_par - venue_stats["venue_avg_par_sr"]
    ) / venue_stats["venue_par_std"].clip(lower=1)

    return venue_stats[venue_stats["venue_matches"] >= min_matches]
```

### Flat Track Bully Index

At the career level, correlate a batter's per-innings SR vs par with venue difficulty:

```python
def compute_flat_track_index(bat_innings, venue_baselines):
    """
    A batter who performs BETTER at harder venues gets a positive score.
    A batter who only excels at easy venues gets a negative score.
    """
    merged = bat_innings.merge(venue_baselines[["venue", "venue_difficulty"]], on="venue", how="left")
    merged["venue_difficulty"] = merged["venue_difficulty"].fillna(0)

    # Weight performances at difficult venues more
    career = merged.groupby(["batter_id", "batter"]).apply(
        lambda g: np.corrcoef(
            g["acc_overall_sr"].fillna(0),
            g["venue_difficulty"].fillna(0)
        )[0, 1] if len(g) > 5 else 0.0,
        include_groups=False,
    ).reset_index(name="flat_track_index")

    # Positive correlation = performs better at harder venues
    return career
```

---

## 10. Win Probability Added (WPA) / Leverage Multiplier

> ✅ **IMPLEMENTED** — `src/wpa.py` created (970 lines). Empirical WP models for both innings (2nd innings: score_ratio lookup with Laplace smoothing; 1st innings: run-rate ratio vs historical par scores). Delivery-level WPA scoring (row-by-row + vectorised). Terminal state handling (chase completion, all out). Career batting WPA (`career_wpa_bat`, `wpa_per_match_bat`, `clutch_wpa_pct_bat`), bowling WPA (sign-flipped; `career_wpa_bowl`, `wpa_per_match_bowl`). Match-level WPA summary with ball-by-ball timeline. Disabled by default (`wpa.enabled: false`). Convenience `compute_all_wpa_metrics()` wrapper. Outputs `wpa_batting.parquet`, `wpa_bowling.parquet`. 81 tests in `tests/test_v02_phase5.py` (shared with Feature 4).

### The Concept

Not all runs and wickets are created equal. A boundary hit when the required run rate is 12 RPO is vastly more valuable than a boundary hit when the required run rate is 4 RPO. WPA measures how much each event changes the game's outcome probability.

### Why Fans Care

It defines true "Match Winners." Fans know intuitively that a fast bowler taking 3 wickets in the death overs to win a tight game is better than taking 3 wickets when the opposition is already 8 down for nothing. WPA quantifies this precisely.

### Where It Hooks In

`parser.py` already captures everything needed: `team_score_before`, `team_wickets_before`, `over`, `ball_idx`, `target_runs`, `innings_num`, `legal_ball_seq`, and `winner`.

### Implementation Approach

**Step 1 — Build a win probability model from historical data:**

```python
def build_win_probability_model(df: pd.DataFrame) -> dict:
    """
    Build an empirical win probability lookup from the delivery-level data.

    For each game state (innings, over, wickets_fallen, runs_scored/target_ratio),
    compute the historical batting team win percentage.

    Returns a dict: (innings, over_bucket, wickets_bucket, score_ratio_bucket) → win_prob
    """
    d = df.copy()

    # Only 2nd innings is meaningful for direct WP calculation
    d2 = d[d["innings_num"] == 2].copy()

    # Game state features
    d2["over_bucket"] = d2["over"].clip(upper=19)
    d2["wickets_bucket"] = d2["team_wickets_before"].clip(upper=9)

    # Score ratio: runs_scored / target
    d2["score_ratio"] = np.where(
        d2["target_runs"] > 0,
        d2["team_score_before"] / d2["target_runs"],
        0.0,
    )
    d2["score_ratio_bucket"] = (d2["score_ratio"] * 10).round() / 10  # 0.0, 0.1, ..., 1.0+

    # Did the batting team win?
    d2["batting_won"] = d2["batting_team"] == d2["winner"]

    # Group and compute win %
    wp_table = d2.groupby(
        ["over_bucket", "wickets_bucket", "score_ratio_bucket"]
    )["batting_won"].mean().to_dict()

    return wp_table
```

**Step 2 — Compute WPA per delivery:**

```python
def compute_wpa(df: pd.DataFrame, wp_model: dict) -> pd.DataFrame:
    """Add a WPA column to the delivery DataFrame."""
    d = df.copy()

    # Compute win_prob_before and win_prob_after for each delivery
    # ... (lookup before and after states in wp_model)

    # WPA = win_prob_after - win_prob_before
    # Batter WPA: positive WPA credited to batter on runs scored
    # Bowler WPA: negative WPA (from batter's perspective) credited to bowler on dots/wickets
    d["wpa"] = d["win_prob_after"] - d["win_prob_before"]

    return d
```

**Step 3 — Aggregate:**

```python
# Career WPA = sum(WPA) per player
# This is additive — rewards both volume and quality
career_wpa = df.groupby(["batter_id", "batter"])["wpa"].sum().reset_index(name="career_wpa")
```

### Complexity Note

This is the most computationally expensive feature (~690K deliveries × state lookup). It's a one-pass operation per delivery, but building the model requires historical outcome data. For 1st innings, use an empirical "par score at this over/wicket" to estimate win probability. For 2nd innings, `target_runs` is directly available.

### Expected Output

| Player | Career WPA | Matches | WPA per Match | Interpretation |
|--------|-----------|---------|---------------|----------------|
| V Kohli | +4.82 | 99 | +0.049 | Top match-winner |
| MS Dhoni | +3.91 | 78 | +0.050 | Elite per-match WPA |
| JJ Bumrah | +3.44 | 65 | +0.053 | Best bowling match-winner |

---

## 11. Anchor Cost / Innings Trajectory Metric

> ✅ **IMPLEMENTED** — Per-delivery cumulative SR tracking and `balls_to_par` in `extract_batting_innings`. Career-level `avg_balls_to_par` and `anchor_cost_ratio` in `aggregate_batting_careers`. Added to CSV output and spot-checks. 37 tests in `tests/test_v02_phase2.py`.

### The Concept

In modern T20s, "Anchors" are heavily debated. How many balls does a batter consume at a sub-par strike rate before they finally "catch up" and accelerate? This metric quantifies the frustration of watching a player bat at a run-a-ball for 20 deliveries.

### Why Fans Care

It directly addresses the "intent" debate. Fans can see that Player A takes 3 balls to reach par SR (fast starter) while Player B takes 18 balls (slow starter who eventually catches up). Combined with `acc_sr_growth`, this tells a complete innings trajectory story.

### Where It Hooks In

Builds on the `faced_sorted` DataFrame inside `extract_batting_innings` (around line 1118), where `batter_ball_num` is already computed.

### Implementation

```python
# Inside extract_batting_innings, after computing batter_ball_num:

# Cumulative batter SR at each ball
faced_sorted["cum_batter_runs"] = faced_sorted.groupby(
    ["match_id", "innings_num", "batter_id"], observed=True
)["batter_runs"].cumsum()

faced_sorted["cum_batter_sr"] = np.where(
    faced_sorted["batter_ball_num"] + 1 > 0,
    faced_sorted["cum_batter_runs"]
    / (faced_sorted["batter_ball_num"] + 1)
    * 100,
    0.0,
)

# Join phase par from context
# For each delivery, get the par SR for the current phase
faced_sorted = faced_sorted.merge(
    phase_par[["match_id", "pp_par_sr", "middle_par_sr", "death_par_sr"]],
    on="match_id",
    how="left",
)
faced_sorted["current_par_sr"] = np.select(
    [
        faced_sorted["phase"] == "powerplay",
        faced_sorted["phase"] == "middle",
        faced_sorted["phase"] == "death",
    ],
    [
        faced_sorted["pp_par_sr"],
        faced_sorted["middle_par_sr"],
        faced_sorted["death_par_sr"],
    ],
    default=faced_sorted["pp_par_sr"],
)

# balls_to_par: first ball number where cumulative SR >= current phase par
reached_par = faced_sorted[
    faced_sorted["cum_batter_sr"] >= faced_sorted["current_par_sr"]
]
balls_to_par = (
    reached_par.groupby(
        ["match_id", "innings_num", "batter_id"], observed=True
    )["batter_ball_num"]
    .first()
    .reset_index(name="balls_to_par")
)

agg = agg.merge(
    balls_to_par,
    on=["match_id", "innings_num", "batter_id"],
    how="left",
)

# For batters who NEVER reached par (got out below par), set to balls_faced
agg["balls_to_par"] = agg["balls_to_par"].fillna(agg["balls_faced"])
```

### Career-Level Metric

```python
career["avg_balls_to_par"] = grp["balls_to_par"].mean()

# Anchor Cost: higher = slower to get going
# Could also express as a ratio: balls_to_par / balls_faced
career["anchor_cost_ratio"] = career["avg_balls_to_par"] / career["total_balls"] * career["innings_count"]
```

### Expected Output

| Player | Avg Balls to Par | Anchor Cost | Interpretation |
|--------|-----------------|-------------|----------------|
| SA Yadav | 2.3 | Very Low | Starts at par immediately |
| GJ Maxwell | 4.1 | Low | Quick to get going |
| V Kohli | 11.5 | Moderate | Takes time but catches up |
| KS Williamson | 18.2 | High | Classic slow anchor |

---

## 12. Explicit Wicket Value for Bowlers (Top-Order Menace)

> ✅ **IMPLEMENTED** — `avg_wicket_quality_mean` and `bowled_lbw_pct` added to `bowl_csv_cols` in `main.py`. Zero additional code — was already computed internally.

### The Concept

Does a bowler rely on cleaning up the tail to boost their stats, or do they consistently dismiss the opposition's best batters? Expose the **Average Wicket Quality (AWQ)** as a standalone, fan-visible metric.

### Why Fans Care

Fans highly respect bowlers who take the "big wickets" — Mitchell Starc trapping openers LBW, Bumrah dismissing Kohli. This metric validates that perception with data.

### Where It Hooks In

This is **already computed** in `bowling.py`'s `compute_wicket_quality()` function and flows into `aggregate_bowling_careers` as `avg_wicket_quality_mean`. But it's currently buried as an internal weight feeding into the Threat composite — not surfaced to fans.

### Implementation

Simply add `avg_wicket_quality_mean` to the `bowl_csv_cols` in `main.py`:

```python
# In main.py, update bowl_csv_cols:
bowl_csv_cols = [
    "bowler_id",
    "bowler",
    "country",
    "matches",
    "total_overs",
    "total_wickets",
    "career_economy",
    "career_sr_bowl",
    "phase_group",
    "score_accuracy",
    "score_control",
    "score_threat",
    "avg_wicket_quality_mean",   # ← ADD THIS
    "bowled_lbw_pct",            # ← ALSO SURFACE THIS
    "is_provisional_bowl",
]
```

Rename in the output to `avg_wicket_quality` for clarity.

### Cost

**Zero.** You've already done the work — it's just hidden. Surfacing it takes 2 lines of code.

### Expected Output

| Bowler | Wickets | AWQ | Interpretation |
|--------|---------|-----|----------------|
| JJ Bumrah | 89 | 1.38 | Consistently takes top-order wickets |
| R Ashwin | 72 | 1.22 | Good quality wickets |
| Generic Seamer | 45 | 0.85 | Relies on tail-end wickets |

---

## 13. Form Tracker & Rolling Averages (Time-Series Outputs)

> ✅ **IMPLEMENTED** — `src/form_tracker.py` created (444 lines). `compute_batting_form_series()` produces one row per (batter, match_date) with rolling-window Acceleration, Power, Control proxies + composite score. `compute_bowling_form_series()` does the same for bowlers (economy, dot%, wickets, accuracy/control/threat proxies). Configurable `window_matches` and `min_window`. Convenience `compute_form_series()` computes both at once. Outputs `batting_form_series.parquet` and `bowling_form_series.parquet`. 69 tests in `tests/test_v02_phase3.py`.

### The Concept

The system uses Bayesian Shrinkage and Recency Weighting for a single "current" rating. But fans love seeing *trajectories* — tracking a player's form slump or purple patch visually over a season. "Look at exactly when Maxwell's power numbers fell off a cliff."

### Why Fans Care

Line charts showing a player's rating climbing or falling over a tournament tell a story. Time-series data is essential for any frontend that wants to show player form over time.

### Where It Hooks In

The `bat_components` DataFrame already has `date` per innings. You need a rolling-window version of the career aggregation.

### Implementation

Create `src/form_tracker.py`:

```python
"""Rolling-window form tracker for time-series player ratings."""

import numpy as np
import pandas as pd


def compute_batting_form_series(
    bat_components: pd.DataFrame,
    window_matches: int = 10,
    min_window: int = 5,
) -> pd.DataFrame:
    """
    Compute a rolling-window rating snapshot for each player at each match.

    Returns one row per (player, match_date) with windowed metrics.
    This enables frontend sparklines and form-over-time charts.
    """
    bc = bat_components.sort_values(["batter_id", "date"]).copy()

    for c in ["batter_id", "batter"]:
        if hasattr(bc[c], "cat"):
            bc[c] = bc[c].astype(str)

    results = []

    for batter_id, player_df in bc.groupby("batter_id"):
        player_df = player_df.reset_index(drop=True)
        if len(player_df) < min_window:
            continue

        batter_name = player_df.iloc[-1]["batter"]

        for i in range(min_window, len(player_df) + 1):
            window = player_df.iloc[max(0, i - window_matches):i]

            row = {
                "batter_id": batter_id,
                "batter": batter_name,
                "date": window.iloc[-1]["date"],
                "window_innings": len(window),
                "cumulative_innings": i,
                # Acceleration proxy
                "window_sr_vs_par": window["acc_overall_sr"].mean(),
                "window_impact": window["acc_impact"].mean(),
                "window_xr": window["acc_runs_above_expected"].mean()
                    if "acc_runs_above_expected" in window.columns else np.nan,
                # Power proxy
                "window_boundary_pct": window["pow_boundary_pct"].mean(),
                "window_six_rate": window["pow_six_rate"].mean()
                    if "pow_six_rate" in window.columns else np.nan,
                "window_finishing_burst": window["pow_finishing_burst"].mean()
                    if "pow_finishing_burst" in window.columns else np.nan,
                # Control proxy
                "window_dot_control": window["ctrl_dot_pct_weighted"].mean()
                    if "ctrl_dot_pct_weighted" in window.columns else np.nan,
                "window_consistency": window["ctrl_scoring_consistency"].mean()
                    if "ctrl_scoring_consistency" in window.columns else np.nan,
                # Raw stats
                "window_avg_runs": window["runs"].mean(),
                "window_avg_sr": window["sr"].mean() if "sr" in window.columns else np.nan,
            }
            results.append(row)

    return pd.DataFrame(results)


def compute_bowling_form_series(
    bowl_components: pd.DataFrame,
    window_matches: int = 10,
    min_window: int = 5,
) -> pd.DataFrame:
    """Rolling-window form tracker for bowlers."""
    bc = bowl_components.sort_values(["bowler_id", "date"]).copy()

    for c in ["bowler_id", "bowler"]:
        if hasattr(bc[c], "cat"):
            bc[c] = bc[c].astype(str)

    results = []

    for bowler_id, player_df in bc.groupby("bowler_id"):
        player_df = player_df.reset_index(drop=True)
        if len(player_df) < min_window:
            continue

        bowler_name = player_df.iloc[-1]["bowler"]

        for i in range(min_window, len(player_df) + 1):
            window = player_df.iloc[max(0, i - window_matches):i]

            row = {
                "bowler_id": bowler_id,
                "bowler": bowler_name,
                "date": window.iloc[-1]["date"],
                "window_spells": len(window),
                "cumulative_spells": i,
                "window_economy": window["economy"].mean(),
                "window_dot_pct": window["dot_pct"].mean(),
                "window_wickets_per_spell": window["wickets"].mean(),
                "window_economy_vs_par": window["economy_ratio_par"].mean()
                    if "economy_ratio_par" in window.columns else np.nan,
            }
            results.append(row)

    return pd.DataFrame(results)
```

### Integration

Call from `main.py` and output as `batting_form_series.parquet` and `bowling_form_series.parquet`. This is O(N × window) per player, which on ~49K batting innings and ~36K bowling spells is manageable (~2–3 seconds total).

---

## 14. Positional WAR (Wins Above Replacement)

### The Concept

Inspired by baseball analytics, evaluate a player's worth compared to a "replacement-level" player (e.g., a generic domestic bench player) at their specific batting position. It answers: "How much is having an elite finisher worth compared to an elite opener?"

### Why Fans Care

It is the ultimate tool for fantasy cricket and auction analysis. The value of a position is baked in — a finisher who is +2.0 z-scores above replacement at a position where replacement level is poor is more valuable than an opener who is +1.5 at a position with a higher replacement floor.

### Where It Hooks In

The codebase already uses Position-Group Z-Scoring (Openers vs Openers, etc.) in `aggregate_batting_careers`. Z-score = 0 means "average for your position."

### Implementation

```python
def compute_batting_war(
    bat_careers: pd.DataFrame,
    replacement_percentile: float = 0.25,
) -> pd.DataFrame:
    """
    Compute WAR as cumulative z-score value above replacement level.

    Replacement level = 25th percentile of each position group's composite.
    WAR = value_above_replacement × volume_factor

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Output of the full batting pipeline (with raw_* columns).
    replacement_percentile : float
        What percentile defines "replacement level" within each position group.
    """
    df = bat_careers.copy()

    for metric in ["raw_acceleration", "raw_power", "raw_control"]:
        # Replacement level = 25th percentile within each position group
        replacement = df.groupby("position_group")[metric].transform(
            lambda x: x.quantile(replacement_percentile)
        )
        df[f"{metric}_above_replacement"] = (df[metric] - replacement).clip(lower=0)

    # WAR = sum of value above replacement, scaled by innings volume
    # More innings = more total value contributed to teams
    # Using log scaling so diminishing returns on extreme innings counts
    volume_factor = np.log1p(df["innings_count"]) / np.log1p(50)

    df["war_acceleration"] = df["raw_acceleration_above_replacement"] * volume_factor
    df["war_power"] = df["raw_power_above_replacement"] * volume_factor
    df["war_control"] = df["raw_control_above_replacement"] * volume_factor

    df["war_batting"] = (
        df["war_acceleration"]
        + df["war_power"]
        + df["war_control"]
    )

    return df
```

### Bowling WAR

Same approach, but using `phase_group` instead of `position_group`, and `raw_accuracy`, `raw_control`, `raw_threat`.

```python
def compute_bowling_war(
    bowl_careers: pd.DataFrame,
    replacement_percentile: float = 0.25,
) -> pd.DataFrame:
    df = bowl_careers.copy()

    for metric in ["raw_accuracy", "raw_control", "raw_threat"]:
        replacement = df.groupby("phase_group")[metric].transform(
            lambda x: x.quantile(replacement_percentile)
        )
        df[f"{metric}_above_replacement"] = (df[metric] - replacement).clip(lower=0)

    volume_factor = np.log1p(df["matches"]) / np.log1p(50)

    df["war_bowling"] = (
        df["raw_accuracy_above_replacement"]
        + df["raw_control_above_replacement"]
        + df["raw_threat_above_replacement"]
    ) * volume_factor

    return df
```

### Expected Output

| Player | Position | WAR Batting | Interpretation |
|--------|----------|-------------|----------------|
| V Kohli | Top Order | 8.42 | Massive cumulative value |
| SA Yadav | Upper Middle | 6.91 | Elite for position |
| MS Dhoni | Lower Middle | 7.15 | Irreplaceable finisher |
| Generic backup | Lower Middle | 0.00 | Replacement level |

---

## 15. Era-Adjusted Ratings (Cross-Generational Harmonization)

### The Concept

As T20 cricket evolves, average scores keep rising. A strike rate of 140 in 2012 was elite; in 2024, it is average. Era-adjusted ratings ensure a 2010 performance is mathematically adjusted to 2024 terms, enabling fair historical comparisons.

### Why Fans Care

"Was Chris Gayle in 2011 more dominant than Heinrich Klaasen in 2024?" is the kind of debate that needs era adjustment. Without it, recent players always look better because the game has inflated.

### Where It Hooks In

`context.py` computes `match_par_sr` per match. The batting components already use `sr / par - 1.0` (ratio-based context normalisation). This handles pitch differences but doesn't handle the *global* era shift in how extreme those ratios can get.

### The Gap

The current system normalises within a single match (match par). A 2012 match with par 120 and a 2024 match with par 155 both produce ratio-based scores. But the *population distribution* of those ratios may differ across eras — as T20 batting techniques evolve, the spread of SR/par ratios may widen.

### Implementation

```python
def compute_era_adjustment(match_ctx: pd.DataFrame) -> pd.DataFrame:
    """
    Compute yearly era baselines for cross-generational normalization.

    Returns a DataFrame with one row per year containing era statistics
    and a multiplier to adjust historical performances to "modern terms."
    """
    df = match_ctx.copy()
    df["year"] = pd.to_datetime(df["match_date"]).dt.year

    era_stats = df.groupby("year").agg(
        year_avg_par_sr=("match_par_sr", "mean"),
        year_std_par_sr=("match_par_sr", "std"),
        year_avg_boundary_rate=("match_boundary_rate", "mean"),
        year_avg_dot_pct=("match_dot_pct", "mean"),
        year_matches=("match_id", "nunique"),
    ).reset_index()

    # Rolling 3-year smoothed average to avoid single-year spikes
    era_stats["era_par_sr"] = era_stats["year_avg_par_sr"].rolling(
        3, min_periods=1, center=True
    ).mean()

    era_stats["era_boundary_rate"] = era_stats["year_avg_boundary_rate"].rolling(
        3, min_periods=1, center=True
    ).mean()

    # Global reference point: most recent year as the standard
    global_ref_sr = era_stats["era_par_sr"].iloc[-1]
    global_ref_br = era_stats["era_boundary_rate"].iloc[-1]

    # Era multiplier: adjusts historical performances to "modern terms"
    # A multiplier > 1.0 means that era was harder → historical performances
    # should be scaled up
    era_stats["era_sr_multiplier"] = global_ref_sr / era_stats["era_par_sr"].clip(lower=50)
    era_stats["era_boundary_multiplier"] = global_ref_br / era_stats["era_boundary_rate"].clip(lower=0.01)

    return era_stats[["year", "era_par_sr", "era_boundary_rate",
                       "era_sr_multiplier", "era_boundary_multiplier",
                       "year_matches"]]
```

### Integration

Merge `era_sr_multiplier` back onto innings data (via year of the match), and multiply the raw `acc_overall_sr` component by the era multiplier **before** z-scoring. This ensures that a player who had SR/par = 1.15 in 2012 (when the average SR/par distribution was tighter) gets appropriate credit compared to a 2024 player with the same ratio in a wider distribution.

```python
# In compute_batting_components, after computing acc_overall_sr:
if "era_sr_multiplier" in df.columns:
    df["acc_overall_sr"] = df["acc_overall_sr"] * df["era_sr_multiplier"]
```

### Expected Era Multiplier Table

| Year | Era Par SR | Era Multiplier | Effect |
|------|-----------|---------------|--------|
| 2008 | 118.5 | 1.31 | +31% boost to 2008 performances |
| 2012 | 124.3 | 1.25 | +25% boost |
| 2016 | 132.1 | 1.18 | +18% boost |
| 2020 | 141.8 | 1.10 | +10% boost |
| 2024 | 155.2 | 1.00 | Reference (no adjustment) |

---

## 16. Implementation Priority Matrix

| Priority | # | Feature | Effort | Fan Impact | Dependencies | Status |
|----------|---|---------|--------|-----------|--------------|--------|
| 🟢 **Do now** | 1 | Grades (Translation Layer) | ~1 hour | 🔥🔥🔥🔥🔥 Instant UX | None | ✅ Done |
| 🟢 **Do now** | 2 | Archetypes & Badges | ~1 hour | 🔥🔥🔥🔥🔥 Shareable | Feature 1 (optional) | ✅ Done |
| 🟢 **Do now** | 12 | Expose AWQ (Wicket Value) | ~10 min | 🔥🔥🔥 Free value | None — already computed | ✅ Done |
| 🟡 **Next sprint** | 6 | Chase Master Index | ~2 hours | 🔥🔥🔥🔥 Debate fuel | None | ✅ Done |
| 🟡 **Next sprint** | 8 | Selfless / Stat-Padder | ~3 hours | 🔥🔥🔥🔥🔥 Viral potential | Minor parser addition | ✅ Done |
| 🟡 **Next sprint** | 11 | Anchor Cost / Balls-to-Par | ~2 hours | 🔥🔥🔥🔥 Modern debate | None | ✅ Done |
| 🟡 **Next sprint** | 13 | Form Tracker (Time-Series) | ~3 hours | 🔥🔥🔥🔥 Visual storytelling | None | ✅ Done |
| 🔵 **Later** | 5 | Peak vs Current Ratings | ~4 hours | 🔥🔥🔥 Double aggregation | None | ✅ Done |
| 🔵 **Later** | 7 | Player Similarity Engine | ~2 hours | 🔥🔥🔥 Auction / prospect tool | sklearn (optional) | ✅ Done (pure NumPy) |
| 🔵 **Later** | 3 | Clutch / Pressure Index | ~4 hours | 🔥🔥🔥 Needs sample-size care | None | ✅ Done |
| 🔵 **Later** | 9 | Venue Difficulty / Flat Track | ~3 hours | 🔥🔥🔥 Needs min-match thresholds | None | ✅ Done |
| 🔵 **Later** | 14 | Positional WAR | ~3 hours | 🔥🔥🔥 Auction / fantasy tool | None | ✅ Done |
| 🔵 **Later** | 15 | Era-Adjusted Ratings | ~4 hours | 🔥🔥🔥 Cross-gen debates | None | ✅ Done |
| 🔴 **Biggest lift** | 10 | Win Probability Added (WPA) | ~8+ hours | 🔥🔥🔥🔥🔥 Ultimate metric | Historical outcome model | 🔲 |
| 🔴 **Biggest lift** | 4 | Head-to-Head Matchups | ~6 hours | 🔥🔥🔥🔥 If bowling-style added | External data (optional) | 🔲 |

### Recommended Implementation Order

**Phase 1 — Quick Wins (Day 1): ✅ COMPLETE**
1. ~~Feature 12: Expose AWQ (10 minutes — just add columns to CSV output)~~ ✅
2. ~~Feature 1: Grades / Translation Layer (1 hour — create `presentation.py`)~~ ✅
3. ~~Feature 2: Archetypes (1 hour — extend `presentation.py`)~~ ✅

**Phase 2 — Core Fan Features (Week 1): ✅ COMPLETE**
4. ~~Feature 6: Chase Master Index (2 hours — conditional split on `innings_num`)~~ ✅
5. ~~Feature 11: Anchor Cost (2 hours — cumulative SR tracking)~~ ✅
6. ~~Feature 8: Selfless Index (3 hours — milestone zone SR tracking)~~ ✅
7. ~~Feature 13: Form Tracker (3 hours — rolling window aggregation)~~ ✅

**Phase 3 — Advanced Analytics (Week 2–3): ✅ COMPLETE (6 of 6)**
8. ~~Feature 5: Peak vs Current (4 hours — dual aggregation pass)~~ ✅
9. ~~Feature 7: Similarity Engine (2 hours — cosine similarity on vectors)~~ ✅
10. ~~Feature 3: Clutch Index (4 hours — high-leverage delivery tagging)~~ ✅
11. ~~Feature 9: Venue Difficulty (3 hours — venue baseline computation)~~ ✅
12. ~~Feature 14: WAR (3 hours — replacement-level definition)~~ ✅
13. ~~Feature 15: Era Adjustment (4 hours — yearly multiplier table)~~ ✅

**Phase 4 — Flagship Features (Week 3–4):**
14. Feature 10: WPA (8+ hours — build empirical win probability model)
15. Feature 4: Matchups with bowling style (6 hours — parser enhancement + external data)

### New Files Created

| File | Features Served | Status |
|------|----------------|--------|
| `src/presentation.py` | 1 (Grades), 2 (Archetypes) | ✅ Created |
| `src/form_tracker.py` | 13 (Time-Series Ratings) | ✅ Created (444 lines) |
| `src/peak_ratings.py` | 5 (Peak vs Current) | ✅ Created (661 lines) |
| `src/similarity.py` | 7 (Player Comps) | ✅ Created (548 lines) |
| `tests/test_presentation.py` | 1 (Grades), 2 (Archetypes) | ✅ Created (49 tests) |
| `tests/test_v02_phase2.py` | 6 (Chase Master), 8 (Selfless), 11 (Anchor Cost) | ✅ Created (37 tests) |
| `tests/test_v02_phase3.py` | 13 (Form Tracker), 5 (Peak Ratings), 7 (Similarity) | ✅ Created (69 tests) |
| `src/venue.py` | 9 (Venue Difficulty / Flat Track Bully) | ✅ Created (710 lines) |
| `src/war.py` | 14 (Positional WAR) | ✅ Created (595 lines) |
| `src/era.py` | 15 (Era-Adjusted Ratings) | ✅ Created (758 lines) |
| `tests/test_v02_phase3b.py` | 9 (Venue), 14 (WAR), 15 (Era) | ✅ Created (93 tests) |
| `src/matchups.py` | 4 (Head-to-Head) | 🔲 |
| `src/clutch.py` | 3 (Clutch Index) | ✅ Created (932 lines, 66 tests) |
| `src/wpa.py` | 10 (Win Probability Added) | 🔲 |

### Existing Files Modified

| File | Features | Status |
|------|----------|--------|
| `src/main.py` | All features (integration point) | ✅ Modified (1, 2, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15) |
| `src/config.py` | All features (new config keys) | ✅ Modified (all v0.2 defaults) |
| `config.yaml` | All features (new tuning parameters) | ✅ Modified (all v0.2 sections) |
| `src/batting.py` | 5, 6, 8, 11, 14, 15 (innings extraction & aggregation) | ✅ Modified (6, 8, 11) |
| `src/bowling.py` | 12 (expose AWQ) | Partial (AWQ exposed; bowling WAR in `war.py`) |
| `src/context.py` | 9 (venue baselines), 15 (era stats) | ✅ Used as-is (venue + era modules consume `match_ctx` output) |
| `ARCHITECTURE.md` | All features (documentation) | 🔲 |

---

## Appendix: Config Keys to Add

> ✅ **ALL CONFIG KEYS BELOW HAVE BEEN ADDED** to both `config.yaml` and `src/config.py` `_DEFAULTS`.

```yaml
# version02 feature configuration

# Feature 1 & 2: Presentation layer
presentation:
  grade_boundaries:
    S: 95
    A_plus: 85
    A: 75
    B_plus: 60
    B: 45
    C_plus: 30
    C: 15
    D: 0
  archetypes_enabled: true

# Feature 3: Clutch index
clutch:
  enabled: true
  min_pressure_innings: 5
  high_rrr_threshold: 9.0    # required run rate threshold for 2nd innings
  collapse_wickets: 3         # wickets in PP to qualify as "collapse"

# Feature 6: Chase master
chase_master:
  enabled: true
  min_innings_per_type: 5     # minimum setting or chasing innings

# Feature 7: Similarity engine
similarity:
  enabled: true
  top_k: 3
  min_innings: 15

# Feature 8: Selfless index
selfless:
  enabled: true
  fifty_approach_range: [40, 49]
  century_approach_range: [90, 99]
  min_zone_balls: 3

# Feature 9: Venue difficulty
venue:
  enabled: true
  min_matches: 5

# Feature 10: WPA
wpa:
  enabled: false              # disabled by default (expensive)
  score_ratio_buckets: 10

# Feature 11: Anchor cost
anchor_cost:
  enabled: true

# Feature 13: Form tracker
form_tracker:
  enabled: true
  window_matches_bat: 10
  window_matches_bowl: 10
  min_window: 5

# Feature 14: WAR
war:
  enabled: true
  replacement_percentile: 0.25

# Feature 15: Era adjustment
era_adjustment:
  enabled: false              # disabled by default (experimental)
  rolling_years: 3
```

https://bestofcricket.substack.com/p/jios-skill-scale-advanced-stats-or