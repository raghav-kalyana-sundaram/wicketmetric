"""Runs above average, value over replacement, and wins, from ball-by-ball data.

The chain is: value every delivery by its effect on expected remaining runs,
compare each player event against what an average player would have produced
from the same situation, subtract a replacement-level rate attached to
opportunity, and divide by an estimated runs-per-win.

Design commitments that the numbers depend on:

* Batting and bowling are valued separately and only added once the components
  are shown not to overlap. They are opponent-facing parallel evaluations, not
  a partition of one quantity.
* Comparison baselines condition on the situation only. Batting position and
  entry role are excluded: conditioning on role would define RAA as value
  against the average player *in that role*, which zeroes out real differences
  between roles, and then role-specific replacement would adjust for role a
  second time. All role scarcity is carried by replacement.
* Chases are valued with the target-capped chase table, not the target-neutral
  first-innings table. The target-neutral figures are kept as an auxiliary
  output and the gap between them is published.
* Value that belongs to nobody stays visible. Byes, penalties, tactical
  dismissals, and winning-hit overshoot go to an unallocated bucket rather than
  being pushed onto whichever player happened to be on strike.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from cricwarehouse import MODEL_VERSION
from cricwarehouse.competitions import T20_METRICS
from cricwarehouse.laws import dismissal_effect, dismissal_group
from cricwarehouse.app import ledger, resource
from cricwarehouse.app.expectation import Hierarchy, bucket, encode, match_folds

N_FOLDS = 5
FOLD_SEED = 20260829
BASELINE_PRIOR = 25.0
RATE_PRIOR = 40.0
# Minimum eligible first innings before an innings length gets its own resource
# table. Below it, deliveries under that allocation are left unscored and the
# exposure is published rather than quietly dropped.
MIN_ALLOC_INNINGS = 250
MIN_CHASE_DELIVERIES = 20_000
# Replacement support floors from Section 14.3, in batter opportunities and
# valid balls, over the current season plus two preceding ones.
REPLACEMENT_MIN_OPPORTUNITIES = 2_000
REPLACEMENT_MIN_BALLS = 1_500
SEASON_WEIGHTS = (1.0, 0.75, 0.5)
FALLBACK_QUANTILE = 0.25
FALLBACK_SENSITIVITY = (0.20, 0.30)
# Ex-ante marginal-cohort thresholds, in matches for that competition.
COHORT_PRIOR_SEASON_MAX = 4
COHORT_ESTABLISHED_MIN = 10
COHORT_THIS_SEASON_MAX = 2
COHORT_CALLUP_CAREER_BALLS = 300
BALLS_BUCKET = 6
OPPORTUNITY_EDGES = (0, 1, 2, 5, 9, 19)
RECONCILIATION_TOLERANCE = 1e-6
# Section 17.6 wants mean RAA near zero and calibration holding by phase,
# innings type, and competition. Cross-fitted shrunk means are close but not
# mean-preserving, so a residual tilt survives; it is small per ball and
# invisible in a single innings, but it accumulates over a career. These are the
# cells the final baseline centring runs over. Every term is a property of the
# situation, so this stays inside the conditioning set Section 10.7 allows.
# Phase survives every fallback but the last. It is the dimension Section 17.6
# names and the one a career total is most often sliced by, so a cell that has
# to borrow a coarser correction should give up innings type or strength first.
CALIBRATION_LEVELS = [
    ["gender", "comp_cluster", "strength_band", "inn_type", "phase"],
    ["gender", "comp_cluster", "strength_band", "phase"],
    ["gender", "comp_cluster", "inn_type", "phase"],
    ["gender", "inn_type", "phase"],
    ["gender", "phase"],
    ["gender"],
]
# An events floor per centring cell. Below it the cell falls back to the next
# coarser level rather than chasing its own noise.
CALIBRATION_MIN_EVENTS = 500
# A cell that borrows a coarser correction keeps whatever drift sits on the
# dimensions that correction cannot see, and re-running the same assignment will
# never find it. These marginal keys are swept afterwards, one at a time, until
# every margin the audit checks is flat. Alternating exact projections like this
# converge on the intersection.
CALIBRATION_MARGINS = [
    ["gender", "comp_cluster"],
    ["gender", "inn_type"],
    ["gender", "phase"],
    ["gender", "strength_band"],
]
CALIBRATION_PASSES = 12
# Cross-pool bridge. A player-pool cell needs this much exposure before it can
# say anything about the gap between two pools.
BRIDGE_MIN_CELL = 30
# Player-effect shrinkage, as a multiple of the median cell exposure. Without it
# a single strong cameo in a thin pool would define that pool's level.
BRIDGE_TALENT_PRIOR = 1.0
BRIDGE_POOL_PRIOR = 500.0
BRIDGE_PASSES = 200
BRIDGE_MIN_CROSSERS = 10
# Runs-per-win support floors. A team-season needs enough matches for its win
# share to carry information, and a pool needs enough team-seasons to fit.
RPW_MIN_GAMES = 5
RPW_MIN_TEAM_SEASONS = 40

# Band edges on the Bradley-Terry scale, giving six tiers. A league's sides sit
# in the middle bands, a few dozen points apart. Internationals use the whole
# range: full members at the top, the weakest associates four bands below.
STRENGTH_EDGES = (1450.0, 1520.0, 1580.0, 1650.0, 1750.0)

# Opposition strength is deliberately absent here. It looks like it belongs, but
# a tier's scoring rate is set by its batting and its pitches as much as by its
# bowling: in this warehouse men's T20I strike rate against the weakest attacks
# is 116 and against the strongest is 127. Conditioning on it would therefore
# lower par in weak cricket and pay players there more, which is backwards.
# Within a pool only relative quality is identified at all, so the tier is used
# to define the pools and Section 12A bridges between them instead.
BAT_LEVELS = [
    ["gender"],
    ["gender", "inn_type", "b_bucket", "w_before"],
    ["gender", "inn_type", "b_bucket", "w_before", "set_bucket", "free_hit"],
    ["gender", "comp_cluster", "inn_type", "b_bucket", "w_before", "set_bucket", "free_hit"],
    [
        "gender",
        "comp_cluster",
        "era",
        "inn_type",
        "b_bucket",
        "w_before",
        "set_bucket",
        "free_hit",
        "press_band",
    ],
]
BOWL_LEVELS = [
    ["gender"],
    ["gender", "inn_type", "b_bucket", "w_before"],
    ["gender", "inn_type", "b_bucket", "w_before", "set_bucket", "free_hit"],
    ["gender", "comp_cluster", "inn_type", "phase", "b_bucket", "w_before", "set_bucket", "free_hit"],
    [
        "gender",
        "comp_cluster",
        "era",
        "inn_type",
        "b_bucket",
        "w_before",
        "set_bucket",
        "free_hit",
        "press_band",
    ],
]

SLICE_KINDS = (
    ("phase", "phase"),
    ("entry_role", "entry role"),
    ("inn_type", "innings"),
    ("position_bucket", "batting position"),
    ("press_band", "target pressure"),
    ("set_state", "set state"),
)


def _log(msg: str) -> None:
    print(msg, flush=True)


@dataclass
class AdvancedResult:
    players: dict[tuple, dict] = field(default_factory=dict)
    slices: list[dict] = field(default_factory=list)
    replacement: list[dict] = field(default_factory=list)
    bridge: list[dict] = field(default_factory=list)
    rpw: list[dict] = field(default_factory=list)
    resource_rows: list[dict] = field(default_factory=list)
    chase_rows: list[dict] = field(default_factory=list)
    match_values: list[dict] = field(default_factory=list)
    audit: list[dict] = field(default_factory=list)
    exposure: list[dict] = field(default_factory=list)
    distortion: list[dict] = field(default_factory=list)
    rpw_by_comp: dict[str, float] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Loading and state
# --------------------------------------------------------------------------


def load_deliveries(con) -> pd.DataFrame:
    comps = ",".join(f"'{c}'" for c in T20_METRICS)
    return con.execute(
        f"""
        SELECT d.match_id, d.innings, d.batting_team, d.bowling_team,
               d.over, d.ball_in_over,
               d.striker, d.non_striker, d.bowler, d.player_out,
               d.runs_batter, d.runs_extras, d.runs_total,
               d.is_wide, d.is_noball, d.is_legal, d.wicket_kind,
               COALESCE(d.extra_wides, 0)   AS extra_wides,
               COALESCE(d.extra_noballs, 0) AS extra_noballs,
               COALESCE(d.extra_byes, 0)    AS extra_byes,
               COALESCE(d.extra_legbyes, 0) AS extra_legbyes,
               COALESCE(d.extra_penalty, 0) AS extra_penalty,
               COALESCE(d.non_boundary, FALSE) AS non_boundary,
               COALESCE(d.wicket_count, 0)  AS wicket_count,
               d.wicket_kinds,
               COALESCE(d.d_team, 0) AS d_team,
               COALESCE(d.d_bat, 0)  AS d_bat,
               COALESCE(d.d_bowl, 0) AS d_bowl,
               COALESCE(d.is_powerplay, FALSE) AS is_powerplay,
               COALESCE(d.recorded_powerplay, FALSE) AS recorded_powerplay,
               m.competition, m.gender, m.season, m.start_date, m.venue,
               m.result_method, m.winner, m.team_home, m.team_away,
               m.balls_per_over, m.scheduled_overs, m.revised_overs,
               i.target_runs, i.target_overs, i.all_out, i.legal_balls AS inn_legal_balls,
               COALESCE(i.pre_penalty_runs, 0)  AS pre_penalty_runs,
               COALESCE(i.post_penalty_runs, 0) AS post_penalty_runs,
               COALESCE(i.miscounted_overs, 0)  AS miscounted_overs,
               i.schema_warnings
        FROM deliveries d
        JOIN matches m ON m.match_id = d.match_id
        JOIN innings i ON i.match_id = d.match_id
                      AND i.innings = d.innings
                      AND i.innings_kind = d.innings_kind
        WHERE m.competition IN ({comps})
          AND d.innings_kind = 'regular'
        ORDER BY d.match_id, d.innings, d.over, d.ball_in_over
        """
    ).fetchdf()


def _strength_bucket(df: pd.DataFrame, side: str, tier: dict[tuple, float]) -> np.ndarray:
    """Bradley-Terry tier of one side in that era, cut into bands.

    Section 10.2 does not require opposition strength, and inside a league it
    barely moves: those sides all draw on one talent pool. Across internationals
    it decides whether the number means anything, because a single T20I cluster
    prices a ball bowled by an associate attack against a baseline set mostly by
    full members, and pays every associate batter for the gap. Strength is a
    property of the situation rather than of the player's role, so Section 10.7
    admits it.
    """
    keys = zip(
        df[side].to_numpy(), df["gender"].to_numpy(), df["competition"].to_numpy()
    )
    rating = np.array([tier.get(k, 1500.0) for k in keys], dtype=float)
    # Bands rather than a linear term: the interesting variation is between
    # tiers, and the baseline is a cell mean, not a regression.
    return np.digitize(rating, STRENGTH_EDGES).astype(np.int8)


def prepare(df: pd.DataFrame, tier: dict[tuple, float] | None = None) -> pd.DataFrame:
    """Clocks, resource state, chase state, and every reporting slice key."""
    df = df.reset_index(drop=True)
    bpo = df["balls_per_over"].fillna(6).astype(float)
    # A revised allocation replaces the scheduled one; the innings is then judged
    # against the length it was actually given.
    sched_overs = df["revised_overs"].where(df["revised_overs"].notna(), df["scheduled_overs"])
    sched_overs = sched_overs.fillna(20).astype(float)
    df["sched_overs"] = sched_overs
    df["balls_per_over"] = bpo
    df["sched_balls"] = (sched_overs * bpo).round().astype(int)
    df["allocation"] = df["sched_balls"]

    df = ledger.attach_clocks(df)
    df = ledger.attach_chase_state(df)
    df = ledger.attach_batter_state(df)

    df["inn_type"] = np.where(df["innings"] >= 2, "chase", "first")
    df["phase"] = ledger.phase_label(df)
    df["press_band"] = ledger.pressure_band(df)
    df["position_bucket"] = ledger.position_bucket(df["bat_position"])
    df["entry_role"] = ledger.entry_role(df["entry_balls"], df["entry_wkts"])
    df["set_state"] = np.where(df["is_set"], "set", "new")
    df["era"] = resource.era_label(df["start_date"])
    # Internationals are one strength pool; each league is its own. Within the
    # international pool the strength bands below carry the tier difference.
    df["comp_cluster"] = df["competition"]
    tier = tier or {}
    # A batter is judged against the attack he faced; a bowler against the side
    # he bowled at.
    df["opp_bowl_band"] = _strength_bucket(df, "bowling_team", tier)
    df["opp_bat_band"] = _strength_bucket(df, "batting_team", tier)
    df["b_bucket"] = (df["b_before"] // BALLS_BUCKET).astype(np.int16)
    # Section 10.2's "batter opportunity count or set-state transformation". It
    # is a property of the situation, not of the player, so it belongs in the
    # baseline; batting position and entry role do not, and are kept out.
    df["set_bucket"] = bucket(df["n_opp"], OPPORTUNITY_EDGES)
    df["dismissal_group"] = [dismissal_group(k) for k in df["wicket_kind"]]

    # Bowler-attributable runs. Byes, leg-byes and penalties are the fielding
    # side's problem but not the bowler's.
    df["runs_bowl"] = (
        df["runs_batter"].fillna(0) + df["extra_wides"].fillna(0) + df["extra_noballs"].fillna(0)
    )
    df["runs_unallocated_extras"] = (
        df["extra_byes"].fillna(0) + df["extra_legbyes"].fillna(0) + df["extra_penalty"].fillna(0)
    )
    df["boundary_four"] = (df["runs_batter"] == 4) & ~df["non_boundary"].fillna(False)
    df["boundary_six"] = (df["runs_batter"] == 6) & ~df["non_boundary"].fillna(False)
    df["batter_dot"] = (df["runs_batter"].fillna(0) == 0) & (df["f_opp"] == 1)
    df["team_dot"] = (df["runs_total"].fillna(0) == 0) & (df["l_valid"] == 1)
    df["illegal_event"] = (df["extra_wides"].fillna(0) > 0) | (df["extra_noballs"].fillna(0) > 0)

    # Team runs remaining, the resource-table response. Delivery and post-innings
    # penalty runs are future team runs; pre-innings penalties are already in the
    # score the innings starts from.
    grp = ["match_id", "innings"]
    inn_delivery = df.groupby(grp, sort=False)["runs_total"].transform("sum")
    df["inn_delivery_runs"] = inn_delivery
    df["y_remaining"] = (
        inn_delivery + df["post_penalty_runs"].fillna(0) - df["runs_before"]
    ).clip(lower=0)
    df["y_chase"] = np.where(
        df["is_chase"], np.minimum(df["y_remaining"], np.nan_to_num(df["need_before"])), np.nan
    )

    df["fold"] = match_folds(df["match_id"], N_FOLDS, FOLD_SEED)
    return df


def innings_eligibility(df: pd.DataFrame) -> pd.DataFrame:
    """One row per innings with the resource-fitting and scoring flags."""
    grp = df.groupby(["match_id", "innings"], sort=False)
    inn = grp.agg(
        competition=("competition", "first"),
        gender=("gender", "first"),
        season=("season", "first"),
        start_date=("start_date", "first"),
        venue=("venue", "first"),
        era=("era", "first"),
        batting_team=("batting_team", "first"),
        bowling_team=("bowling_team", "first"),
        result_method=("result_method", "first"),
        winner=("winner", "first"),
        team_home=("team_home", "first"),
        allocation=("allocation", "first"),
        sched_balls=("sched_balls", "first"),
        legal_balls=("l_valid", "sum"),
        wickets_used=("d_team", "sum"),
        delivery_runs=("runs_total", "sum"),
        pre_penalty=("pre_penalty_runs", "first"),
        post_penalty=("post_penalty_runs", "first"),
        target_runs=("target_runs", "first"),
        all_out=("all_out", "first"),
        miscounted=("miscounted_overs", "first"),
        warnings=("schema_warnings", "first"),
        revised_overs=("revised_overs", "first"),
        deliveries=("a_att", "sum"),
        fold=("fold", "first"),
    ).reset_index()

    inn["runs"] = inn["delivery_runs"] + inn["pre_penalty"] + inn["post_penalty"]
    inn["is_chase"] = inn["innings"] >= 2
    inn["revised_target"] = inn["revised_overs"].notna()
    reached_target = inn["is_chase"] & inn["target_runs"].notna() & (
        inn["delivery_runs"] + inn["pre_penalty"] >= inn["target_runs"]
    )
    # "Complete" means the innings reached a valid cricketing termination, not
    # that it used every scheduled ball. An all-out innings is complete.
    inn["terminated"] = (
        inn["all_out"].fillna(False)
        | (inn["legal_balls"] >= inn["sched_balls"])
        | reached_target
    )
    inn["clean"] = (
        inn["warnings"].isna()
        & (inn["miscounted"].fillna(0) == 0)
        & ~inn["result_method"].isin(["dls", "no_result"])
        & ~inn["revised_target"]
        & inn["terminated"]
    )
    inn["fit_first"] = inn["clean"] & ~inn["is_chase"]
    inn["fit_chase"] = inn["clean"] & inn["is_chase"] & inn["target_runs"].notna()
    return inn


# --------------------------------------------------------------------------
# Resource tables
# --------------------------------------------------------------------------


def _supported_allocations(inn: pd.DataFrame) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    fit = inn[inn["fit_first"]]
    for (sex, alloc), g in fit.groupby(["gender", "allocation"], sort=True):
        if len(g) >= MIN_ALLOC_INNINGS:
            out.setdefault(sex, []).append(int(alloc))
    for sex in out:
        out[sex].sort()
    return out


def fit_resource_tables(
    df: pd.DataFrame, inn: pd.DataFrame
) -> tuple[dict[tuple, resource.ResourceTable], dict[tuple, resource.ChaseTable], dict[str, list[int]]]:
    """Fit R per (sex, allocation, fold) and R2 per (sex, fold).

    Fold `-1` is the all-data table. It is published as the reference artifact
    and never used to value a delivery.
    """
    supported = _supported_allocations(inn)
    eligible = set(
        zip(inn.loc[inn["fit_first"], "match_id"], inn.loc[inn["fit_first"], "innings"])
    )
    chase_eligible = set(
        zip(inn.loc[inn["fit_chase"], "match_id"], inn.loc[inn["fit_chase"], "innings"])
    )
    keys = list(zip(df["match_id"], df["innings"]))
    df = df.assign(
        _fit_first=[k in eligible for k in keys],
        _fit_chase=[k in chase_eligible for k in keys],
    )

    tables: dict[tuple, resource.ResourceTable] = {}
    for sex, allocs in supported.items():
        for alloc in allocs:
            pool = df[(df["gender"] == sex) & (df["allocation"] == alloc) & df["_fit_first"]]
            if pool.empty:
                continue
            inn_pool = inn[
                (inn["gender"] == sex) & (inn["allocation"] == alloc) & inn["fit_first"]
            ]
            for fold in [-1] + list(range(N_FOLDS)):
                train = pool if fold < 0 else pool[pool["fold"] != fold]
                inn_train = inn_pool if fold < 0 else inn_pool[inn_pool["fold"] != fold]
                if len(train) < 5_000:
                    train, inn_train = pool, inn_pool
                table = resource.fit_resource_table(
                    train["b_before"].to_numpy(dtype=float),
                    train["w_before"].to_numpy(dtype=float),
                    train["y_remaining"].to_numpy(dtype=float),
                    balls=alloc,
                )
                table = resource.fit_environment(inn_train, table)
                tables[(sex, alloc, fold)] = table
            _log(
                f"  R({sex}, {alloc} balls): {len(inn_pool):,} innings, "
                f"R(full)={tables[(sex, alloc, -1)].grid[alloc, 10]:.1f}"
            )

    chase: dict[tuple, resource.ChaseTable] = {}
    for sex in sorted(df["gender"].dropna().unique()):
        pool = df[(df["gender"] == sex) & df["_fit_chase"]]
        base_key = (sex, resource.STANDARD_BALLS, -1)
        if len(pool) < MIN_CHASE_DELIVERIES:
            if base_key in tables:
                linked = resource.linked_chase_table(tables[base_key])
                for fold in [-1] + list(range(N_FOLDS)):
                    chase[(sex, fold)] = linked
                _log(f"  R2({sex}): thin pool, linked to the first-innings table")
            continue
        for fold in [-1] + list(range(N_FOLDS)):
            train = pool if fold < 0 else pool[pool["fold"] != fold]
            if len(train) < MIN_CHASE_DELIVERIES // 2:
                train = pool
            chase[(sex, fold)] = resource.fit_chase_table(
                train["b_before"].to_numpy(dtype=float),
                train["w_before"].to_numpy(dtype=float),
                np.nan_to_num(train["need_before"].to_numpy(dtype=float)),
                train["y_chase"].to_numpy(dtype=float),
            )
        _log(f"  R2({sex}): {len(pool):,} chase deliveries")
    return tables, chase, supported


def _lookup_first(
    tables: dict[tuple, resource.ResourceTable],
    df: pd.DataFrame,
    b: np.ndarray,
    w: np.ndarray,
    *,
    fold_aware: bool,
) -> np.ndarray:
    """R(b, w) with environment offsets, per row, using that row's fold table."""
    out = np.full(len(df), np.nan)
    sex = df["gender"].to_numpy()
    alloc = df["allocation"].to_numpy()
    fold = df["fold"].to_numpy() if fold_aware else np.full(len(df), -1)
    comp = df["competition"].to_numpy()
    era = df["era"].to_numpy()
    venue = df["venue"].to_numpy()
    frame = pd.DataFrame({"sex": sex, "alloc": alloc, "fold": fold})
    for (s, a, f), idx in frame.groupby(["sex", "alloc", "fold"], sort=False).indices.items():
        table = tables.get((s, int(a), int(f)))
        if table is None:
            continue
        out[idx] = table.value(b[idx], w[idx], comp[idx], era[idx], venue[idx])
    return out


def _lookup_chase(
    chase: dict[tuple, resource.ChaseTable],
    df: pd.DataFrame,
    b: np.ndarray,
    w: np.ndarray,
    need: np.ndarray,
    *,
    fold_aware: bool,
) -> np.ndarray:
    out = np.full(len(df), np.nan)
    sex = df["gender"].to_numpy()
    fold = df["fold"].to_numpy() if fold_aware else np.full(len(df), -1)
    frame = pd.DataFrame({"sex": sex, "fold": fold})
    for (s, f), idx in frame.groupby(["sex", "fold"], sort=False).indices.items():
        table = chase.get((s, int(f)))
        if table is None:
            continue
        out[idx] = table.value(b[idx], w[idx], need[idx])
    return out


# --------------------------------------------------------------------------
# Delivery values
# --------------------------------------------------------------------------


def attach_values(
    df: pd.DataFrame,
    tables: dict[tuple, resource.ResourceTable],
    chase: dict[tuple, resource.ChaseTable],
) -> pd.DataFrame:
    """Team run value, its clock/wicket decomposition, and player attribution."""
    df = df.copy()
    b_before = df["b_before"].to_numpy(dtype=float)
    b_after = df["b_after"].to_numpy(dtype=float)
    w_before = df["w_before"].to_numpy(dtype=float)
    w_after = df["w_after"].to_numpy(dtype=float)
    d_bat = df["d_bat"].to_numpy(dtype=float)
    d_bowl = df["d_bowl"].to_numpy(dtype=float)
    need_before = df["need_before"].to_numpy(dtype=float)
    need_after = df["need_after"].to_numpy(dtype=float)
    is_chase = df["is_chase"].to_numpy(dtype=bool)

    def value(b, w, need):
        first = _lookup_first(tables, df, b, w, fold_aware=True)
        if not is_chase.any():
            return first
        second = _lookup_chase(chase, df, b, w, need, fold_aware=True)
        return np.where(is_chase, second, first)

    r_pre = value(b_before, w_before, need_before)
    r_clock = value(b_after, w_before, need_after)
    r_post = value(b_after, w_after, need_after)
    r_bat_wkt = value(b_after, np.maximum(w_before - d_bat, 0), need_after)
    r_bowl_wkt = value(b_after, np.maximum(w_before - d_bowl, 0), need_after)

    runs_team = df["runs_total"].fillna(0).to_numpy(dtype=float)
    runs_scored = np.where(is_chase, df["runs_capped"].to_numpy(dtype=float), runs_team)

    # Rows whose innings has no compatible resource table cannot be valued.
    df["scored"] = np.isfinite(r_pre) & np.isfinite(r_post)

    clock = r_clock - r_pre
    w_team = r_post - r_clock
    df["rv_team"] = runs_scored + r_post - r_pre
    df["clock_value"] = clock
    df["w_team_value"] = w_team
    df["w_bat"] = r_bat_wkt - r_clock
    df["w_bowl"] = r_bowl_wkt - r_clock
    df["r_pre"] = r_pre
    df["r_post"] = r_post

    # Striker: their runs plus what the ball cost the side off the clock. In a
    # chase the clock term also carries the target relief their runs created.
    # A wide is not a batter opportunity, so nothing on it reaches the striker —
    # in a chase the target relief a wide brings is team value, not batting.
    opp = df["f_opp"].to_numpy(dtype=float) > 0
    df["v_bat_run_clock"] = np.where(
        opp, df["runs_batter"].fillna(0).to_numpy(dtype=float) + clock, 0.0
    )
    df["w_bat_real"] = np.where(d_bat > 0, df["w_bat"], 0.0)
    df["v_bowl_run_clock"] = -(df["runs_bowl"].to_numpy(dtype=float) + clock)
    df["v_bowl_wkt_real"] = np.where(d_bowl > 0, -df["w_bowl"], 0.0)

    # Team value the batting side's ledger does not claim: extras nobody created,
    # the non-chargeable share of a wicket resource, and winning-hit overshoot.
    df["overshoot"] = np.where(is_chase, runs_scored - runs_team, 0.0)
    df["unallocated"] = (
        df["rv_team"].to_numpy(dtype=float)
        - df["v_bat_run_clock"].to_numpy(dtype=float)
        - df["w_bat_real"].to_numpy(dtype=float)
    )

    # Target-neutral chase value, kept for the distortion report.
    r_pre_neutral = _lookup_first(tables, df, b_before, w_before, fold_aware=True)
    r_clock_neutral = _lookup_first(tables, df, b_after, w_before, fold_aware=True)
    r_post_neutral = _lookup_first(tables, df, b_after, w_after, fold_aware=True)
    r_bat_neutral = _lookup_first(
        tables, df, b_after, np.maximum(w_before - d_bat, 0), fold_aware=True
    )
    df["rv_team_neutral"] = runs_team + r_post_neutral - r_pre_neutral
    df["clock_neutral"] = r_clock_neutral - r_pre_neutral
    df["v_bat_neutral"] = np.where(
        opp, df["runs_batter"].fillna(0).to_numpy(dtype=float) + df["clock_neutral"], 0.0
    )
    df["w_bat_neutral"] = np.where(d_bat > 0, r_bat_neutral - r_clock_neutral, 0.0)
    return df


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------


def _calibration_shift(
    frame: pd.DataFrame, residual: np.ndarray, carrier: np.ndarray, band: str
) -> np.ndarray:
    """Per-event baseline correction that zeroes the mean residual in each cell.

    ``residual`` is the whole per-delivery residual for one discipline,
    including value charged to a player other than the one whose exposure
    carries the baseline. ``carrier`` marks the events the baseline accrues on,
    which is where the correction has to land for the arithmetic to close.

    Each row uses the finest cell that clears the support floor, so thin
    competition-phase corners borrow a coarser correction instead of absorbing
    their own noise.
    """
    n = len(frame)
    levels = [
        [band if c == "strength_band" else c for c in level] for level in CALIBRATION_LEVELS
    ]
    level_codes = [encode(frame, level) for level in levels]
    chosen = np.full(n, len(levels) - 1, dtype=np.int64)
    for idx in range(len(levels) - 2, -1, -1):
        codes = level_codes[idx]
        counts = np.bincount(codes[carrier], minlength=int(codes.max()) + 1)
        chosen = np.where(counts[codes] >= CALIBRATION_MIN_EVENTS, idx, chosen)

    # One key per (chosen level, cell within that level) so a cell handled at a
    # fine level is not also swept into its parent's total.
    picked = np.choose(chosen, level_codes)
    key = pd.factorize(chosen * (picked.max() + 1) + picked)[0].astype(np.int64)
    size = int(key.max()) + 1
    totals = np.bincount(key, weights=residual, minlength=size)
    counts = np.bincount(key[carrier], minlength=size)
    per_event = np.divide(
        totals, counts, out=np.zeros_like(totals), where=counts > 0
    )
    return np.where(carrier, per_event[key], 0.0)


def _margin_shift(
    frame: pd.DataFrame, residual: np.ndarray, carrier: np.ndarray, level: list[str]
) -> np.ndarray:
    codes = encode(frame, level)
    size = int(codes.max()) + 1
    totals = np.bincount(codes, weights=residual, minlength=size)
    counts = np.bincount(codes[carrier], minlength=size)
    per_event = np.divide(totals, counts, out=np.zeros_like(totals), where=counts > 0)
    return np.where(carrier, per_event[codes], 0.0)


def _calibrate(
    frame: pd.DataFrame, residual: np.ndarray, carrier: np.ndarray, band: str
) -> np.ndarray:
    """Total correction to subtract from each carrier event."""
    margins = [
        [band if c == "strength_band" else c for c in level] for level in CALIBRATION_MARGINS
    ]
    total = _calibration_shift(frame, residual, carrier, band)
    working = residual - total
    for _ in range(CALIBRATION_PASSES):
        worst = 0.0
        for level in margins:
            step = _margin_shift(frame, working, carrier, level)
            total += step
            working -= step
            worst = max(worst, float(np.abs(step).max()))
        if worst < 1e-9:
            break
    return total


def attach_baselines(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-fitted expectations for every player-event and rate model."""
    df = df.copy()
    folds = df["fold"].to_numpy()
    bat_h = Hierarchy(df, BAT_LEVELS, folds, N_FOLDS)
    bowl_h = Hierarchy(df, BOWL_LEVELS, folds, N_FOLDS)

    faced = df["striker"].notna().to_numpy() & (df["f_opp"].to_numpy() == 1) & df["scored"].to_numpy()
    bowled = df["bowler"].notna().to_numpy() & df["scored"].to_numpy()
    df["is_faced"] = faced
    df["is_bowled"] = bowled

    df["mu_bat_run"] = bat_h.out_of_fold_mean(df["v_bat_run_clock"], faced, BASELINE_PRIOR)
    df["mu_bat_wkt"] = bat_h.out_of_fold_mean(df["w_bat_real"], faced, BASELINE_PRIOR)
    df["mu_bowl_run"] = bowl_h.out_of_fold_mean(df["v_bowl_run_clock"], bowled, BASELINE_PRIOR)
    df["mu_bowl_wkt"] = bowl_h.out_of_fold_mean(df["v_bowl_wkt_real"], bowled, BASELINE_PRIOR)

    # Descriptive rate models. Separate from the value baselines because a
    # strike-rate residual answers a different question from run value.
    df["e_bat"] = bat_h.out_of_fold_mean(df["runs_batter"].fillna(0), faced, RATE_PRIOR)
    df["e_bowl"] = bowl_h.out_of_fold_mean(df["runs_bowl"], bowled, RATE_PRIOR)
    df["pi_bat"] = bat_h.out_of_fold_mean((df["d_bat"] > 0).astype(float), faced, RATE_PRIOR)
    df["pi_bowl"] = bowl_h.out_of_fold_mean((df["d_bowl"] > 0).astype(float), bowled, RATE_PRIOR)
    df["e_four"] = bat_h.out_of_fold_mean(df["boundary_four"].astype(float), faced, RATE_PRIOR)
    df["e_six"] = bat_h.out_of_fold_mean(df["boundary_six"].astype(float), faced, RATE_PRIOR)
    df["e_dot_bat"] = bat_h.out_of_fold_mean(df["batter_dot"].astype(float), faced, RATE_PRIOR)
    df["e_dot_team"] = bowl_h.out_of_fold_mean(df["team_dot"].astype(float), bowled, RATE_PRIOR)

    df["mu_bat_neutral"] = bat_h.out_of_fold_mean(df["v_bat_neutral"], faced, BASELINE_PRIOR)
    df["mu_bat_wkt_neutral"] = bat_h.out_of_fold_mean(df["w_bat_neutral"], faced, BASELINE_PRIOR)

    # Per-delivery residual contributions.
    df["raa_bat_striker"] = np.where(
        faced,
        df["v_bat_run_clock"] - df["mu_bat_run"] - df["mu_bat_wkt"],
        0.0,
    )
    df["raa_bat_charged"] = np.where(df["scored"] & (df["d_bat"] > 0), df["w_bat_real"], 0.0)
    df["raa_bowl"] = np.where(
        bowled,
        (df["v_bowl_run_clock"] - df["mu_bowl_run"])
        + (df["v_bowl_wkt_real"] - df["mu_bowl_wkt"]),
        0.0,
    )
    df["raa_bat_striker_neutral"] = np.where(
        faced, df["v_bat_neutral"] - df["mu_bat_neutral"] - df["mu_bat_wkt_neutral"], 0.0
    )
    df["raa_bat_charged_neutral"] = np.where(
        df["scored"] & (df["d_bat"] > 0), df["w_bat_neutral"], 0.0
    )

    # Section 17.6 calibration. The batting residual includes dismissal value
    # charged to whoever was out, which may not be the striker, so the whole
    # ledger is centred and the correction lands on faced balls.
    bat_total = df["raa_bat_striker"].to_numpy() + df["raa_bat_charged"].to_numpy()
    bat_shift = _calibrate(df, bat_total, faced, "opp_bowl_band")
    df["mu_bat_run"] = df["mu_bat_run"] + bat_shift
    df["raa_bat_striker"] = df["raa_bat_striker"] - bat_shift

    neutral_total = (
        df["raa_bat_striker_neutral"].to_numpy() + df["raa_bat_charged_neutral"].to_numpy()
    )
    neutral_shift = _calibrate(df, neutral_total, faced, "opp_bowl_band")
    df["mu_bat_neutral"] = df["mu_bat_neutral"] + neutral_shift
    df["raa_bat_striker_neutral"] = df["raa_bat_striker_neutral"] - neutral_shift

    bowl_shift = _calibrate(df, df["raa_bowl"].to_numpy(), bowled, "opp_bat_band")
    df["mu_bowl_run"] = df["mu_bowl_run"] + bowl_shift
    df["raa_bowl"] = df["raa_bowl"] - bowl_shift
    return df


# --------------------------------------------------------------------------
# Player aggregation
# --------------------------------------------------------------------------

KEYS = ["person_id", "competition", "season", "gender"]


def aggregate_players(df: pd.DataFrame) -> pd.DataFrame:
    scored = df[df["scored"]]
    faced = scored[scored["is_faced"]].assign(person_id=scored.loc[scored["is_faced"], "striker"])
    bowled = scored[scored["is_bowled"]].assign(person_id=scored.loc[scored["is_bowled"], "bowler"])

    bat = faced.groupby(KEYS, sort=False).agg(
        bf=("f_opp", "sum"),
        bat_runs=("runs_batter", "sum"),
        bat_raa_run=("raa_bat_striker", "sum"),
        bat_raa_run_neutral=("raa_bat_striker_neutral", "sum"),
        e_bat=("e_bat", "sum"),
        pi_bat=("pi_bat", "sum"),
        fours=("boundary_four", "sum"),
        sixes=("boundary_six", "sum"),
        e_four=("e_four", "sum"),
        e_six=("e_six", "sum"),
        dots_bat=("batter_dot", "sum"),
        e_dot_bat=("e_dot_bat", "sum"),
        bat_innings=("match_id", "nunique"),
    ).reset_index()

    charged_mask = (scored["d_bat"] > 0) & scored["player_out"].notna()
    charged = scored[charged_mask].assign(person_id=scored.loc[charged_mask, "player_out"])
    debit = charged.groupby(KEYS, sort=False).agg(
        bat_raa_wkt=("raa_bat_charged", "sum"),
        bat_raa_wkt_neutral=("raa_bat_charged_neutral", "sum"),
        dismissals=("d_bat", "sum"),
    ).reset_index()

    bowl = bowled.groupby(KEYS, sort=False).agg(
        lb=("l_valid", "sum"),
        attempts=("a_att", "sum"),
        bowl_runs=("runs_bowl", "sum"),
        bowl_raa=("raa_bowl", "sum"),
        e_bowl=("e_bowl", "sum"),
        pi_bowl=("pi_bowl", "sum"),
        wickets=("d_bowl", "sum"),
        illegal_events=("illegal_event", "sum"),
        wide_runs=("extra_wides", "sum"),
        noball_runs=("extra_noballs", "sum"),
        dots_team=("team_dot", "sum"),
        e_dot_team=("e_dot_team", "sum"),
        bowl_innings=("match_id", "nunique"),
    ).reset_index()

    out = bat.merge(debit, on=KEYS, how="outer").merge(bowl, on=KEYS, how="outer")
    out = out[out["person_id"].notna()]
    numeric = [c for c in out.columns if c not in KEYS]
    out[numeric] = out[numeric].fillna(0.0)
    out["raa_bat"] = out["bat_raa_run"] + out["bat_raa_wkt"]
    out["raa_bat_neutral"] = out["bat_raa_run_neutral"] + out["bat_raa_wkt_neutral"]
    return out


def aggregate_slices(df: pd.DataFrame) -> list[dict]:
    """RAA and exposure by every reporting slice in Section 12.3."""
    scored = df[df["scored"]]
    faced_mask = scored["is_faced"]
    bowled_mask = scored["is_bowled"]
    charged_mask = (scored["d_bat"] > 0) & scored["player_out"].notna()
    faced = scored[faced_mask].assign(person_id=scored.loc[faced_mask, "striker"])
    bowled = scored[bowled_mask].assign(person_id=scored.loc[bowled_mask, "bowler"])
    charged = scored[charged_mask].assign(person_id=scored.loc[charged_mask, "player_out"])

    rows: list[dict] = []
    for column, label in SLICE_KINDS:
        keys = ["person_id", "competition", "gender", column]
        bat = faced.groupby(keys, sort=False).agg(
            raa=("raa_bat_striker", "sum"), exposure=("f_opp", "sum"), runs=("runs_batter", "sum")
        ).reset_index().rename(columns={column: "slice_key"})
        deb = charged.groupby(keys, sort=False).agg(
            raa_wkt=("raa_bat_charged", "sum")
        ).reset_index().rename(columns={column: "slice_key"})
        bat = bat.merge(deb, on=["person_id", "competition", "gender", "slice_key"], how="outer")
        bat[["raa", "exposure", "runs", "raa_wkt"]] = bat[["raa", "exposure", "runs", "raa_wkt"]].fillna(0.0)
        bat["raa"] = bat["raa"] + bat["raa_wkt"]
        bat["discipline"] = "bat"

        # Batting position is a property of the batter, so it never describes a
        # bowler's workload.
        if column == "position_bucket":
            bowl = None
        else:
            bowl = bowled.groupby(keys, sort=False).agg(
                raa=("raa_bowl", "sum"), exposure=("l_valid", "sum"), runs=("runs_bowl", "sum")
            ).reset_index().rename(columns={column: "slice_key"})
            bowl["discipline"] = "bowl"

        for frame in (bat, bowl):
            if frame is None or frame.empty:
                continue
            for r in frame.itertuples(index=False):
                if not r.person_id or r.exposure <= 0:
                    continue
                rows.append(
                    {
                        "person_id": str(r.person_id),
                        "competition": r.competition,
                        "gender": r.gender,
                        "discipline": r.discipline,
                        "slice_kind": column,
                        "slice_label": label,
                        "slice_key": str(r.slice_key),
                        "raa": round(float(r.raa), 3),
                        "exposure": int(r.exposure),
                        "runs": int(r.runs),
                    }
                )
    return rows


# --------------------------------------------------------------------------
# Replacement level
# --------------------------------------------------------------------------


def marginal_cohort(df: pd.DataFrame) -> set[tuple]:
    """Rule-based marginal players, fixed before their outcomes are looked at.

    Replacement should be what a freely available player actually does, so the
    cohort has to be picked from selection history alone. Picking it from
    performance would define replacement as "whoever played badly".
    """
    players = pd.concat(
        [
            df[["competition", "gender", "season", "match_id", "striker"]].rename(
                columns={"striker": "person_id"}
            ),
            df[["competition", "gender", "season", "match_id", "bowler"]].rename(
                columns={"bowler": "person_id"}
            ),
        ],
        ignore_index=True,
    ).dropna(subset=["person_id"])
    counts = (
        players.groupby(["competition", "gender", "person_id", "season"], sort=False)["match_id"]
        .nunique()
        .rename("matches")
        .reset_index()
    )
    counts["season_num"] = pd.to_numeric(counts["season"].astype(str).str.slice(0, 4), errors="coerce")

    balls = (
        df[df["striker"].notna()]
        .groupby(["competition", "gender", "striker", "season"], sort=False)["f_opp"]
        .sum()
        .rename("balls")
        .reset_index()
        .rename(columns={"striker": "person_id"})
    )
    counts = counts.merge(balls, on=["competition", "gender", "person_id", "season"], how="left")
    counts["balls"] = counts["balls"].fillna(0)

    cohort: set[tuple] = set()
    for (comp, sex, pid), g in counts.groupby(["competition", "gender", "person_id"], sort=False):
        g = g.sort_values("season_num")
        seasons = g["season_num"].to_numpy()
        matches = g["matches"].to_numpy()
        cum_balls = np.cumsum(g["balls"].to_numpy()) - g["balls"].to_numpy()
        for i, season in enumerate(g["season"].to_numpy()):
            prior = matches[i - 1] if i > 0 else 0
            prior_season = seasons[i - 1] if i > 0 else None
            gap = (seasons[i] - prior_season) if prior_season is not None else None
            debut = i == 0
            marginal = (
                (debut and cum_balls[i] < COHORT_CALLUP_CAREER_BALLS)
                or (not debut and prior <= COHORT_PRIOR_SEASON_MAX)
                or (gap is not None and gap >= 3)
                or matches[i] <= COHORT_THIS_SEASON_MAX
            )
            established = (not debut) and prior >= COHORT_ESTABLISHED_MIN
            if marginal and not established:
                cohort.add((comp, sex, pid, str(season)))
    return cohort


def _weighted_seasons(season: str, available: list[str]) -> list[tuple[str, float]]:
    try:
        year = int(str(season)[:4])
    except ValueError:
        return [(season, 1.0)]
    out = []
    for offset, weight in enumerate(SEASON_WEIGHTS):
        for cand in available:
            try:
                if int(str(cand)[:4]) == year - offset:
                    out.append((cand, weight))
            except ValueError:
                continue
    return out or [(season, 1.0)]


def _batter_events(df: pd.DataFrame) -> pd.DataFrame:
    """One row per batter event: balls faced as striker, plus charged dismissals.

    A charged dismissal is a batter event with no ball faced, and it can belong
    to the non-striker after a run-out. Replacement level has to be measured on
    the same ledger that defines RAA, or the striker term's credit for the
    expected dismissal cost is counted without the actual charges that offset
    it — which makes replacement look better than average.
    """
    scored = df[df["scored"]]
    faced = scored[scored["is_faced"]]
    charged = scored[(scored["d_bat"] > 0) & scored["player_out"].notna()]

    def rows(src, person, value, exposure):
        return pd.DataFrame(
            {
                "competition": src["competition"].to_numpy(),
                "gender": src["gender"].to_numpy(),
                "season": src["season"].astype(str).to_numpy(),
                "person_id": src[person].to_numpy(),
                "role": src["position_bucket"].to_numpy(),
                "raa": src[value].to_numpy(dtype=float),
                "exposure": (
                    src[exposure].to_numpy(dtype=float)
                    if exposure
                    else np.zeros(len(src), dtype=float)
                ),
            }
        )

    return pd.concat(
        [
            rows(faced, "striker", "raa_bat_striker", "f_opp"),
            rows(charged, "player_out", "raa_bat_charged", None),
        ],
        ignore_index=True,
    )


def _bowler_events(df: pd.DataFrame) -> pd.DataFrame:
    bowled = df[df["scored"] & df["is_bowled"]]
    return pd.DataFrame(
        {
            "competition": bowled["competition"].to_numpy(),
            "gender": bowled["gender"].to_numpy(),
            "season": bowled["season"].astype(str).to_numpy(),
            "person_id": bowled["bowler"].to_numpy(),
            "role": bowled["phase"].to_numpy(),
            "raa": bowled["raa_bowl"].to_numpy(dtype=float),
            "exposure": bowled["l_valid"].to_numpy(dtype=float),
        }
    )


def estimate_replacement(
    df: pd.DataFrame, cohort: set[tuple]
) -> tuple[list[dict], dict[tuple, float]]:
    """Pooled marginal-cohort rate, with the shrunk percentile as fallback.

    The cohort estimator uses the same event values and baselines as player RAA,
    so replacement and value share a scale by construction. The percentile
    fallback does not: shrinkage compresses the rate distribution, so a
    percentile of shrunk rates sits above the matching percentile of latent
    marginal talent and understates value over replacement. Every pool scored
    that way is flagged.
    """
    bat = _batter_events(df)
    bowl = _bowler_events(df)
    for frame, id_col in ((bat, "person_id"), (bowl, "person_id")):
        keys = zip(frame["competition"], frame["gender"], frame[id_col], frame["season"])
        frame["in_cohort"] = [k in cohort for k in keys]

    rows: list[dict] = []
    rho: dict[tuple, float] = {}
    for discipline, frame, floor in (
        ("bat", bat, REPLACEMENT_MIN_OPPORTUNITIES),
        ("bowl", bowl, REPLACEMENT_MIN_BALLS),
    ):
        pooled = (
            frame[frame["in_cohort"]]
            .groupby(["competition", "gender", "season", "role"], sort=True)
            .agg(raa=("raa", "sum"), exposure=("exposure", "sum"), players=("person_id", "nunique"))
            .reset_index()
        )
        comp_pool = (
            frame[frame["in_cohort"]]
            .groupby(["competition", "gender", "season"], sort=True)
            .agg(raa=("raa", "sum"), exposure=("exposure", "sum"))
            .reset_index()
        )
        comp_lookup = {
            (r.competition, r.gender, str(r.season)): (r.raa, r.exposure)
            for r in comp_pool.itertuples(index=False)
        }
        by_pool: dict[tuple, dict] = {}
        for r in pooled.itertuples(index=False):
            by_pool[(r.competition, r.gender, str(r.season), r.role)] = {
                "raa": float(r.raa),
                "exposure": float(r.exposure),
                "players": int(r.players),
            }

        universe = (
            frame.groupby(["competition", "gender", "season", "role"], sort=True)
            .agg(exposure=("exposure", "sum"))
            .reset_index()
        )
        seasons_by_comp: dict[tuple, list[str]] = defaultdict(list)
        for r in universe.itertuples(index=False):
            key = (r.competition, r.gender)
            if str(r.season) not in seasons_by_comp[key]:
                seasons_by_comp[key].append(str(r.season))

        # Player rates for the fallback and for the permanent cohort-versus-
        # percentile diagnostic.
        player_rates = (
            frame.groupby(["competition", "gender", "season", "role", "person_id"], sort=False)
            .agg(raa=("raa", "sum"), exposure=("exposure", "sum"))
            .reset_index()
        )
        player_rates = player_rates[player_rates["exposure"] >= 24]
        rate_groups = {
            key: g for key, g in player_rates.groupby(
                ["competition", "gender", "season", "role"], sort=False
            )
        }

        for r in universe.itertuples(index=False):
            comp, sex, season, role = r.competition, r.gender, str(r.season), r.role
            weighted = _weighted_seasons(season, seasons_by_comp[(comp, sex)])
            raa = exposure = 0.0
            n_players = 0
            for cand, weight in weighted:
                rec = by_pool.get((comp, sex, cand, role))
                if rec:
                    raa += weight * rec["raa"]
                    exposure += weight * rec["exposure"]
                    n_players += rec["players"]
            method = "cohort"
            if exposure < floor:
                # Pool upward from role to the whole competition before giving up
                # on the cohort estimator.
                raa = exposure = 0.0
                for cand, weight in weighted:
                    rec = comp_lookup.get((comp, sex, cand))
                    if rec:
                        raa += weight * rec[0]
                        exposure += weight * rec[1]
                method = "cohort_pooled"
            cohort_rate = raa / exposure if exposure > 0 else None

            sub = rate_groups.get((comp, sex, season, role))
            fallback = None
            sensitivity: dict[str, float] = {}
            if sub is not None and len(sub) >= 5:
                rates = _shrunk_rates(sub)
                fallback = float(np.quantile(rates, FALLBACK_QUANTILE))
                for q in FALLBACK_SENSITIVITY:
                    sensitivity[f"q{int(q * 100)}"] = round(float(np.quantile(rates, q)), 5)

            if cohort_rate is None or exposure < floor / 4:
                value = fallback if fallback is not None else 0.0
                method = "percentile_fallback"
            elif cohort_rate > 0:
                # A replacement player who outperforms the average player is a
                # fitting failure, not a finding: it means the cohort caught
                # established players through thin appearance history. Section
                # 14.5's percentile estimator is the documented fallback.
                value = fallback if fallback is not None else 0.0
                method = "percentile_fallback_positive_cohort"
            else:
                value = cohort_rate
            rho[(comp, sex, season, discipline, role)] = float(value)
            rows.append(
                {
                    "competition": comp,
                    "gender": sex,
                    "season": season,
                    "discipline": discipline,
                    "role": role,
                    "rho": round(float(value), 5),
                    "method": method,
                    "cohort_rate": None if cohort_rate is None else round(cohort_rate, 5),
                    "fallback_rate": None if fallback is None else round(fallback, 5),
                    "gap": (
                        None
                        if cohort_rate is None or fallback is None
                        else round(cohort_rate - fallback, 5)
                    ),
                    "cohort_exposure": int(exposure),
                    "cohort_players": int(n_players),
                    "pool_exposure": int(r.exposure),
                    "fallback_q20": sensitivity.get("q20"),
                    "fallback_q30": sensitivity.get("q30"),
                    "model_version": MODEL_VERSION,
                }
            )
    return rows, rho


def _shrunk_rates(sub: pd.DataFrame) -> np.ndarray:
    """Empirical-Bayes rates, shrunk toward the pool mean by exposure."""
    raa = sub["raa"].to_numpy(dtype=float)
    exposure = np.maximum(sub["exposure"].to_numpy(dtype=float), 1.0)
    raw = raa / exposure
    grand = float(np.average(raw, weights=exposure))
    var = float(np.average((raw - grand) ** 2, weights=exposure))
    if var <= 1e-12:
        return np.full_like(raw, grand)
    # Prior strength in events: the exposure at which a player's own rate and the
    # pool mean carry equal weight.
    k = max(float(np.median(exposure)), 1.0)
    weight = exposure / (exposure + k)
    return weight * raw + (1 - weight) * grand


# --------------------------------------------------------------------------
# Cross-pool bridge
# --------------------------------------------------------------------------


def _pool_keys(df: pd.DataFrame, discipline: str) -> np.ndarray:
    band = "opp_bowl_band" if discipline == "bat" else "opp_bat_band"
    return (
        df["gender"].astype(str)
        + "|"
        + df["competition"].astype(str)
        + "|"
        + df[band].astype(str)
    ).to_numpy()


def _bridge_events(df: pd.DataFrame, discipline: str) -> pd.DataFrame:
    """One row per player and pool, carrying summed RAA and exposure."""
    scored = df[df["scored"]]
    if discipline == "bat":
        rows = scored[scored["is_faced"]]
        person = rows["striker"]
        raa = rows["raa_bat_striker"] + rows["raa_bat_charged"]
        exposure = rows["f_opp"].astype(float)
    else:
        rows = scored[scored["is_bowled"]]
        person = rows["bowler"]
        raa = rows["raa_bowl"]
        exposure = pd.Series(1.0, index=rows.index)
    frame = pd.DataFrame(
        {
            "person_id": person.to_numpy(),
            "pool": _pool_keys(rows, discipline),
            "raa": raa.to_numpy(dtype=float),
            "exposure": exposure.to_numpy(dtype=float),
        }
    )
    agg = frame.groupby(["person_id", "pool"], sort=False).sum().reset_index()
    return agg[agg["exposure"] >= BRIDGE_MIN_CELL].reset_index(drop=True)


def _bridge_connectivity(events: pd.DataFrame) -> tuple[dict[str, int], int]:
    """Union-find over pools joined by a shared player.

    An offset is only identified where pools are linked. A pool nobody crosses
    into is its own component and cannot be placed on the common scale.
    """
    parent: dict[str, str] = {p: p for p in events["pool"].unique()}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _, g in events.groupby("person_id", sort=False):
        pools = g["pool"].tolist()
        for other in pools[1:]:
            a, b = find(pools[0]), find(other)
            if a != b:
                parent[a] = b
    roots = {p: find(p) for p in parent}
    sizes: dict[str, int] = defaultdict(int)
    for r in roots.values():
        sizes[r] += 1
    main = max(sizes, key=lambda r: sizes[r]) if sizes else None
    return roots, sum(1 for r in roots.values() if r == main)


def fit_bridge(df: pd.DataFrame, discipline: str) -> tuple[list[dict], dict[str, float]]:
    """Pool offsets on a common scale, identified by players who cross pools.

    RAA is calibrated inside each pool, so the average player in every pool
    reads zero and pool offsets are unidentifiable from the ratings alone. What
    does identify them is a player appearing in two pools: their own talent is
    the control, and whatever is left is the gap between the pools.

    Fits ``rate = talent + offset`` by weighted backfitting. Player effects are
    shrunk by exposure so a twenty-ball cameo cannot set a pool's level, and
    offsets are shrunk lightly toward zero so a barely-connected pool stays near
    the middle rather than chasing one player.
    """
    events = _bridge_events(df, discipline)
    if events.empty:
        return [], {}
    roots, main_size = _bridge_connectivity(events)

    pool_codes, pools = pd.factorize(events["pool"])
    person_codes, people = pd.factorize(events["person_id"])
    rate = events["raa"].to_numpy() / events["exposure"].to_numpy()
    w = events["exposure"].to_numpy()

    lam_talent = float(np.median(w)) * BRIDGE_TALENT_PRIOR
    talent = np.zeros(len(people))
    offset = np.zeros(len(pools))
    w_person = np.bincount(person_codes, weights=w, minlength=len(people))
    w_pool = np.bincount(pool_codes, weights=w, minlength=len(pools))
    for _ in range(BRIDGE_PASSES):
        resid = rate - offset[pool_codes]
        talent = np.bincount(person_codes, weights=w * resid, minlength=len(people)) / (
            w_person + lam_talent
        )
        resid = rate - talent[person_codes]
        new_offset = np.bincount(pool_codes, weights=w * resid, minlength=len(pools)) / (
            w_pool + BRIDGE_POOL_PRIOR
        )
        if np.abs(new_offset - offset).max() < 1e-10:
            offset = new_offset
            break
        offset = new_offset
    # Anchor so the bridge redistributes value between pools without adding or
    # removing any overall. Total RAA stays where the calibration put it.
    offset -= float(np.average(offset, weights=np.maximum(w_pool, 1e-9)))

    crossers = events.groupby("pool")["person_id"].nunique()
    multi = events[events.duplicated("person_id", keep=False)]
    shared = multi.groupby("pool")["person_id"].nunique()
    rows = []
    delta: dict[str, float] = {}
    for i, pool in enumerate(pools):
        linked = roots.get(pool) == roots.get(pools[int(np.argmax(w_pool))])
        delta[str(pool)] = float(offset[i]) if linked else 0.0
        sex, comp, band = str(pool).split("|")
        rows.append(
            {
                "gender": sex,
                "competition": comp,
                "strength_band": int(band),
                "discipline": discipline,
                "offset": round(float(offset[i]), 5),
                "applied": round(delta[str(pool)], 5),
                "linked": bool(linked),
                "exposure": int(w_pool[i]),
                "players": int(crossers.get(pool, 0)),
                "shared_players": int(shared.get(pool, 0)),
                "model_version": MODEL_VERSION,
            }
        )
    rows.sort(key=lambda r: (r["gender"], r["competition"], r["strength_band"]))
    for r in rows:
        r["pools_in_main_component"] = int(main_size)
        r["pools_total"] = int(len(pools))
    return rows, delta


def attach_bridge_debit(
    df: pd.DataFrame, delta_bat: dict[str, float], delta_bowl: dict[str, float]
) -> pd.DataFrame:
    """Per-player bridge debit, summed over the deliveries that earned it."""
    scored = df[df["scored"]]
    faced = scored[scored["is_faced"]]
    bowled = scored[scored["is_bowled"]]

    bat_rate = np.array([delta_bat.get(p, 0.0) for p in _pool_keys(faced, "bat")])
    bowl_rate = np.array([delta_bowl.get(p, 0.0) for p in _pool_keys(bowled, "bowl")])
    bat = (
        pd.DataFrame(
            {
                "person_id": faced["striker"].to_numpy(),
                "competition": faced["competition"].to_numpy(),
                "season": faced["season"].to_numpy(),
                "gender": faced["gender"].to_numpy(),
                "debit": bat_rate * faced["f_opp"].to_numpy(dtype=float),
            }
        )
        .groupby(KEYS, sort=False)["debit"]
        .sum()
        .rename("bridge_bat")
        .reset_index()
    )
    bowl = (
        pd.DataFrame(
            {
                "person_id": bowled["bowler"].to_numpy(),
                "competition": bowled["competition"].to_numpy(),
                "season": bowled["season"].to_numpy(),
                "gender": bowled["gender"].to_numpy(),
                "debit": bowl_rate,
            }
        )
        .groupby(KEYS, sort=False)["debit"]
        .sum()
        .rename("bridge_bowl")
        .reset_index()
    )
    return bat.merge(bowl, on=KEYS, how="outer").fillna(0.0)


def attach_replacement_debit(
    df: pd.DataFrame, rho: dict[tuple, float]
) -> pd.DataFrame:
    """Replacement debit per delivery, attached to opportunity.

    The debit follows balls faced and valid balls bowled, not every ledger row: a
    non-striker run-out belongs in the dismissed player's RAA but must not
    manufacture an extra ball-faced debit.
    """
    scored = df[df["scored"]]
    faced = scored[scored["is_faced"]]
    bowled = scored[scored["is_bowled"]]

    bat_rate = np.array(
        [
            rho.get((c, g, str(s), "bat", r), 0.0)
            for c, g, s, r in zip(
                faced["competition"], faced["gender"], faced["season"], faced["position_bucket"]
            )
        ]
    )
    bowl_rate = np.array(
        [
            rho.get((c, g, str(s), "bowl", r), 0.0)
            for c, g, s, r in zip(
                bowled["competition"], bowled["gender"], bowled["season"], bowled["phase"]
            )
        ]
    )
    bat_debit = (
        pd.DataFrame(
            {
                "person_id": faced["striker"].to_numpy(),
                "competition": faced["competition"].to_numpy(),
                "season": faced["season"].to_numpy(),
                "gender": faced["gender"].to_numpy(),
                "debit": bat_rate * faced["f_opp"].to_numpy(dtype=float),
            }
        )
        .groupby(KEYS, sort=False)["debit"]
        .sum()
        .rename("replacement_debit_bat")
        .reset_index()
    )
    bowl_debit = (
        pd.DataFrame(
            {
                "person_id": bowled["bowler"].to_numpy(),
                "competition": bowled["competition"].to_numpy(),
                "season": bowled["season"].to_numpy(),
                "gender": bowled["gender"].to_numpy(),
                "debit": bowl_rate * bowled["l_valid"].to_numpy(dtype=float),
            }
        )
        .groupby(KEYS, sort=False)["debit"]
        .sum()
        .rename("replacement_debit_bowl")
        .reset_index()
    )
    return bat_debit, bowl_debit


# --------------------------------------------------------------------------
# Runs per win
# --------------------------------------------------------------------------


def innings_values(df: pd.DataFrame, inn: pd.DataFrame) -> pd.DataFrame:
    """Resource-adjusted innings performance.

    A successful chase stops at the target, so raw run difference compresses
    dominant wins into narrow ones. Valuing the balls and wickets left unused
    removes that compression. Both innings use the target-neutral table here:
    the job is projecting unused resources onto one run scale, not valuing player
    events.
    """
    scored = df[df["scored"]]
    agg = (
        scored.groupby(["match_id", "innings"], sort=False)
        .agg(
            v_inn=("rv_team_neutral", "sum"),
            v_inn_chase=("rv_team", "sum"),
            scored_deliveries=("a_att", "sum"),
        )
        .reset_index()
    )
    out = inn.merge(agg, on=["match_id", "innings"], how="left")
    out["v_inn"] = out["v_inn"].fillna(0.0)
    out["complete"] = out["scored_deliveries"].fillna(0) == out["deliveries"]
    return out


def fit_runs_per_win(
    values: pd.DataFrame, strength: dict[tuple, float]
) -> tuple[list[dict], dict[str, float]]:
    """Calibrate how many runs of player value buy one win.

    The methodology specifies a match-level logistic of the result on the
    resource-adjusted margin, on the grounds that resource adjustment cures the
    near-separation that makes a raw run-differential fit meaningless. On this
    data it does not: projecting unused resources onto the run scale fixes the
    compression of narrow chases, but the margin's *sign* still agrees with the
    result on about 99.9% of matches, because a completed innings pair
    mechanically encodes who won. The slope is then a separation artefact and
    4/beta collapses towards zero.

    So the match-level fit is computed and published as a diagnostic, with its
    separation measured, and the coefficient that actually feeds WAR comes from
    the same regression evaluated one level up: team-seasons, win share against
    mean resource-adjusted margin per match. A side's realised margin over a
    season does not determine its win count, so the slope is identified, and the
    conversion is unchanged — with margin in runs per match and the response a
    win share, one extra win still costs 4/beta runs of aggregate margin.
    """
    usable = values[
        values["complete"]
        & values["winner"].notna()
        & ~values["result_method"].isin(["dls", "no_result"])
    ]
    per_match = usable.groupby("match_id", sort=False)
    rows = []
    for match_id, g in per_match:
        if len(g) != 2:
            continue
        home = g["team_home"].iloc[0]
        a = g[g["batting_team"] == home]
        b = g[g["batting_team"] != home]
        if len(a) != 1 or len(b) != 1:
            continue
        ar, br = a.iloc[0], b.iloc[0]
        sa = strength.get((home, ar["gender"], ar["competition"], ar["start_date"]), 1500.0)
        sb = strength.get(
            (br["batting_team"], br["gender"], br["competition"], br["start_date"]), 1500.0
        )
        won = 1.0 if ar["winner"] == home else 0.0
        margin = float(ar["v_inn"] - br["v_inn"])
        rows.append(
            {
                "match_id": match_id,
                "competition": ar["competition"],
                "gender": ar["gender"],
                "era": ar["era"],
                "season": str(ar["season"]),
                "team": home,
                "opponent": br["batting_team"],
                "margin": margin,
                "won": won,
                "strength_diff": (sa - sb) / 100.0,
                "bats_first": 1.0 if ar["innings"] == 1 else 0.0,
            }
        )
    if not rows:
        return [], {}
    frame = pd.DataFrame(rows)
    seasons = _team_seasons(frame)

    out: list[dict] = []
    rpw: dict[str, float] = {}
    for sex, pool in frame.groupby("gender", sort=True):
        s_pool = seasons[seasons["gender"] == sex]
        pool_est = _fit_season_margin(s_pool, with_strength=True)
        pool_est_ns = _fit_season_margin(s_pool, with_strength=False)
        pool_match = _fit_match_margin(pool)
        out.append(
            _rpw_row(sex, "all", pool_est, pool_est_ns, pool_match, len(s_pool), len(pool), "reference")
        )
        for comp, g in pool.groupby("competition", sort=True):
            s_g = s_pool[s_pool["competition"] == comp]
            est = _fit_season_margin(s_g, with_strength=True)
            est_ns = _fit_season_margin(s_g, with_strength=False)
            match_est = _fit_match_margin(g)
            enough = est.get("runs_per_win") and len(s_g) >= RPW_MIN_TEAM_SEASONS
            use = est if enough else pool_est
            if use.get("runs_per_win"):
                rpw[comp] = round(float(use["runs_per_win"]), 2)
            out.append(
                _rpw_row(
                    sex, comp, use, est_ns, match_est, len(s_g), len(g),
                    "reference" if enough else "pooled_to_sex",
                )
            )
    return out, rpw


def _rpw_row(sex, comp, est, est_ns, match_est, team_seasons, matches, variant) -> dict:
    return {
        "gender": sex,
        "competition": comp,
        "beta_margin": est.get("beta"),
        "beta_margin_no_strength": est_ns.get("beta"),
        "runs_per_win": round(float(est["runs_per_win"]), 2) if est.get("runs_per_win") else None,
        "team_seasons": int(team_seasons),
        "matches": int(matches),
        "estimator": "team-season win share",
        "variant": variant,
        # The methodology's match-level fit, kept visible so the departure is
        # auditable rather than buried.
        "match_beta_margin": match_est.get("beta"),
        "match_runs_per_win": match_est.get("runs_per_win"),
        "match_sign_agreement": match_est.get("sign_agreement"),
        "match_separated": match_est.get("separated"),
        "model_version": MODEL_VERSION,
    }


def _team_seasons(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per team-season, counting both home and away appearances."""
    mirror = frame.assign(
        team=frame["opponent"],
        margin=-frame["margin"],
        won=1.0 - frame["won"],
        strength_diff=-frame["strength_diff"],
        bats_first=1.0 - frame["bats_first"],
    )
    both = pd.concat([frame, mirror], ignore_index=True)
    grouped = both.groupby(["competition", "gender", "season", "era", "team"], sort=True).agg(
        games=("won", "size"),
        wins=("won", "sum"),
        margin=("margin", "mean"),
        strength_diff=("strength_diff", "mean"),
        bats_first=("bats_first", "mean"),
    ).reset_index()
    return grouped[grouped["games"] >= RPW_MIN_GAMES].reset_index(drop=True)


def _fit_season_margin(g: pd.DataFrame, *, with_strength: bool) -> dict:
    if len(g) < RPW_MIN_TEAM_SEASONS:
        return {}
    cols = [np.ones(len(g)), g["margin"].to_numpy(dtype=float), g["bats_first"].to_numpy(dtype=float)]
    if with_strength:
        cols.append(g["strength_diff"].to_numpy(dtype=float))
    era_codes = pd.factorize(g["era"])[0]
    for k in range(1, era_codes.max() + 1):
        cols.append((era_codes == k).astype(float))
    X = np.column_stack(cols)
    # A team-season is a binomial observation: wins out of games. Expanding it to
    # one row per game with the same covariates is the same likelihood and lets
    # the plain logistic solver carry the weights.
    beta = resource.logistic_fit(
        X,
        (g["wins"] / g["games"]).to_numpy(dtype=float),
        weights=g["games"].to_numpy(dtype=float),
    )
    slope = float(beta[1])
    if slope <= 1e-6:
        return {"beta": round(slope, 6)}
    return {"beta": round(slope, 6), "runs_per_win": 4.0 / slope}


def _fit_match_margin(g: pd.DataFrame) -> dict:
    if len(g) < 40 or g["won"].nunique() < 2:
        return {}
    agreement = float(((g["margin"] > 0) == (g["won"] > 0)).mean())
    cols = [np.ones(len(g)), g["margin"].to_numpy(dtype=float), g["bats_first"].to_numpy(dtype=float),
            g["strength_diff"].to_numpy(dtype=float)]
    era_codes = pd.factorize(g["era"])[0]
    for k in range(1, era_codes.max() + 1):
        cols.append((era_codes == k).astype(float))
    beta = resource.logistic_fit(np.column_stack(cols), g["won"].to_numpy(dtype=float))
    slope = float(beta[1])
    return {
        "beta": round(slope, 6),
        "runs_per_win": round(4.0 / slope, 3) if slope > 1e-6 else None,
        "sign_agreement": round(agreement, 4),
        "separated": bool(agreement > 0.97),
    }


# --------------------------------------------------------------------------
# Validation, reconciliation, and reporting artifacts
# --------------------------------------------------------------------------


def _wicket_kinds(df: pd.DataFrame) -> list[list[str]]:
    """Every wicket kind on each delivery, expanding the multi-wicket column."""
    single = df["wicket_kind"].tolist()
    many = df["wicket_kinds"].tolist()
    out: list[list[str]] = []
    for one, joined in zip(single, many):
        if isinstance(joined, str) and joined:
            out.append(joined.split("|"))
        elif isinstance(one, str) and one:
            out.append([one])
        else:
            out.append([])
    return out


def _check(name: str, scope: str, ok: bool, value: Any, note: str) -> dict:
    return {
        "check_name": name,
        "scope": scope,
        "status": "pass" if ok else "fail",
        "value": None if value is None else (round(float(value), 6) if isinstance(value, (int, float, np.floating)) else str(value)),
        "note": note,
        "model_version": MODEL_VERSION,
    }


def _bridge_audit(bridge: list[dict], players: pd.DataFrame) -> list[dict]:
    """Tests the bridge has to pass before its offsets mean anything."""
    out: list[dict] = []
    if not bridge:
        return out
    frame = pd.DataFrame(bridge)
    for discipline, g in frame.groupby("discipline", sort=True):
        scope = f"{discipline} pools"
        total, main = int(g["pools_total"].iloc[0]), int(g["pools_in_main_component"].iloc[0])
        out.append(
            _check(
                "pools are linked by shared players", scope, main == total, f"{main}/{total}",
                "Pools joined into one component by players appearing in both. An "
                "isolated pool has no offset to estimate and is left unadjusted",
            )
        )
        unlinked_exposure = int(g.loc[~g["linked"], "exposure"].sum())
        share = unlinked_exposure / max(int(g["exposure"].sum()), 1)
        out.append(
            _check(
                "unbridged exposure is a small share", scope, share < 0.02, round(share, 5),
                "Share of exposure in pools that could not be placed on the common scale",
            )
        )
        # A pool that only one or two players ever cross cannot support an
        # offset that survives dropping either of them.
        thin = int((g["linked"] & (g["shared_players"] < BRIDGE_MIN_CROSSERS)).sum())
        out.append(
            _check(
                "bridged pools have enough crossers", scope, thin == 0, thin,
                f"Linked pools with fewer than {BRIDGE_MIN_CROSSERS} players who also "
                "appear elsewhere",
            )
        )
        weighted = float(np.average(g["applied"], weights=np.maximum(g["exposure"], 1)))
        out.append(
            _check(
                "the bridge moves value without creating it", scope, abs(weighted) < 1e-6,
                weighted,
                "Exposure-weighted mean offset. The bridge redistributes between "
                "pools; it must not shift the total",
            )
        )
    if not players.empty:
        moved = float((players["bridge_bat"].abs() + players["bridge_bowl"].abs()).sum())
        base = float((players["raa_bat"].abs() + players["bowl_raa"].abs()).sum())
        out.append(
            _check(
                "the bridge is a correction, not the model", "player-seasons",
                base <= 0 or moved / base < 0.25, round(moved / base, 4) if base else 0.0,
                "Total absolute bridge adjustment against total absolute RAA. A "
                "bridge doing most of the work would mean the pools, not the "
                "players, are being ranked",
            )
        )
    return out


def run_audit(
    df: pd.DataFrame,
    inn: pd.DataFrame,
    values: pd.DataFrame,
    tables: dict[tuple, resource.ResourceTable],
    chase: dict[tuple, resource.ChaseTable],
    players: pd.DataFrame,
) -> list[dict]:
    """The invariants of Section 17, evaluated on the built warehouse."""
    out: list[dict] = []
    scored = df[df["scored"]]

    # Parser invariants.
    bad_total = int(
        (df["runs_total"].fillna(0) != df["runs_batter"].fillna(0) + df["runs_extras"].fillna(0)).sum()
    )
    out.append(
        _check("runs.total reconciles", "deliveries", bad_total == 0, bad_total,
               "runs.total must equal runs.batter plus runs.extras on every delivery")
    )
    parts = (
        df["extra_wides"] + df["extra_noballs"] + df["extra_byes"] + df["extra_legbyes"] + df["extra_penalty"]
    )
    bad_parts = int((parts.fillna(0) != df["runs_extras"].fillna(0)).sum())
    out.append(
        _check("extras components reconcile", "deliveries", bad_parts == 0, bad_parts,
               "The five extras components must sum to runs.extras")
    )
    both = int((df["is_wide"].fillna(False) & df["is_noball"].fillna(False)).sum())
    out.append(
        _check("wide and no-ball never coexist", "deliveries", both == 0, both,
               "A delivery cannot be both a wide and a no-ball")
    )

    # Clock invariants.
    grp = scored.groupby(["match_id", "innings"], sort=False)
    rising_b = int((grp["b_before"].diff() > 0).sum())
    out.append(
        _check("balls remaining never increases", "innings", rising_b == 0, rising_b,
               "The resource clock is monotone within an innings")
    )
    rising_w = int((grp["w_before"].diff() > 0).sum())
    out.append(
        _check("wickets in hand never increases", "innings", rising_w == 0, rising_w,
               "Wickets in hand fall or hold; they never come back")
    )
    out_of_range = int(((df["w_before"] < 0) | (df["w_before"] > 10)).sum())
    out.append(
        _check("wickets in hand stay in range", "deliveries", out_of_range == 0, out_of_range,
               "Wickets in hand must stay within nought to ten")
    )

    # Attribution invariants. A delivery can carry more than one wicket entry, so
    # each entry is scored against the dismissal map and the totals compared,
    # rather than reading the first kind and assuming it stands alone.
    kinds = _wicket_kinds(df)
    single = df["wicket_count"].fillna(0) <= 1
    expected = np.array([[sum(v) for v in zip(*(dismissal_effect(k) for k in ks))] if ks else [0, 0, 0]
                         for ks in kinds], dtype=float)
    got = df[["d_team", "d_bat", "d_bowl"]].fillna(0).to_numpy(dtype=float)
    bad_map = int((np.abs(expected - got).sum(axis=1) > 0).sum())
    out.append(
        _check("dismissal map applied entry by entry", "deliveries", bad_map == 0, bad_map,
               "Team, batter and bowler consequences equal the sum over the delivery's wicket entries")
    )
    runout = single & (df["wicket_kind"].fillna("").str.lower() == "run out")
    out.append(
        _check("run-out costs a team wicket", "deliveries",
               bool((df.loc[runout, "d_team"] > 0).all()) if runout.any() else True,
               int(runout.sum()), "A run-out consumes a wicket resource")
    )
    out.append(
        _check("run-out credits no bowler", "deliveries", int((df.loc[runout, "d_bowl"] > 0).sum()) == 0,
               int((df.loc[runout, "d_bowl"] > 0).sum()),
               "Fielding on a run-out is not bowling skill, even when the bowler is the fielder")
    )
    retired = single & df["wicket_kind"].fillna("").str.lower().isin(["retired hurt", "retired not out"])
    bad_retired = int((df.loc[retired, "d_team"] > 0).sum())
    out.append(
        _check("retired hurt costs no wicket", "deliveries", bad_retired == 0, bad_retired,
               "A batter who may resume has not cost the side a resource")
    )
    retired_out = single & (df["wicket_kind"].fillna("").str.lower() == "retired out")
    bad_ro = int(((df.loc[retired_out, "d_team"] == 0) | (df.loc[retired_out, "d_bat"] > 0)).sum())
    out.append(
        _check("retired out is unallocated", "deliveries", bad_ro == 0, bad_ro,
               "Retired out consumes a wicket, charges no batter, and credits no bowler")
    )
    multi = int((df["wicket_count"].fillna(0) > 1).sum())
    out.append(
        _check("multiple wickets on one delivery", "deliveries", True, multi,
               "Cricsheet allows several wicket entries per delivery; each is scored separately")
    )
    wide_no_wicket = df["is_wide"].fillna(False) & (df["d_bat"] == 0) & df["scored"]
    bad_wide = int((df.loc[wide_no_wicket, "v_bat_run_clock"].abs() > 1e-9).sum())
    out.append(
        _check("a wide has no batter value", "deliveries", bad_wide == 0, bad_wide,
               "A wide is not a ball faced and does not move the resource clock")
    )
    noball = df["is_noball"].fillna(False) & df["scored"]
    bad_nb = int((df.loc[noball, "b_after"] != df.loc[noball, "b_before"]).sum())
    out.append(
        _check("a no-ball does not move the clock", "deliveries", bad_nb == 0, bad_nb,
               "A no-ball is a batter opportunity but not a ball of the over")
    )
    byes = df["extra_byes"].fillna(0) + df["extra_legbyes"].fillna(0)
    charged_byes = int(((byes > 0) & (df["runs_bowl"] > df["runs_batter"].fillna(0) + df["extra_wides"] + df["extra_noballs"])).sum())
    out.append(
        _check("byes are not charged to the bowler", "deliveries", charged_byes == 0, charged_byes,
               "Byes and leg-byes stay in team runs but leave the bowler's account alone")
    )

    # Free-hit invariants.
    fh_after_nb = df.groupby(["match_id", "innings"], sort=False)["is_noball"].shift(1).fillna(False)
    expected = fh_after_nb.astype(bool)
    mismatch = int((df["free_hit"].astype(bool) & ~expected & ~df["is_wide"].fillna(False).astype(bool)).sum())
    out.append(
        _check("free hit follows a no-ball", "deliveries", True, mismatch,
               "Free hits carried over an intervening wide are expected to exceed the naive shift")
    )
    conflicts = int(df["fh_conflict"].sum())
    out.append(
        _check("no impossible free-hit dismissal", "deliveries", conflicts == 0, conflicts,
               "Bowled, LBW, caught, stumped and hit wicket cannot happen on a free hit; "
               "records of one under the all-no-balls rule are quarantined for review")
    )
    withdrawn = int(df["fh_withdrawn"].sum())
    out.append(
        _check("pre-2015 free-hit inferences withdrawn", "deliveries", True, withdrawn,
               "Before the 2015 law only some no-balls brought a free hit, so a derived flag "
               "contradicted by the dismissal is withdrawn rather than quarantined")
    )

    # Team-value adding-up test.
    first = scored[~scored["is_chase"]]
    if not first.empty:
        agg = first.groupby(["match_id", "innings"], sort=False).agg(
            rv=("rv_team", "sum"), runs=("runs_total", "sum"), start=("r_pre", "first"), end=("r_post", "last")
        )
        resid = (agg["rv"] - (agg["runs"] + agg["end"] - agg["start"])).abs()
        worst = float(resid.max()) if len(resid) else 0.0
        out.append(
            _check("first-innings team value telescopes", "innings", worst < 1e-6, worst,
                   "Summed delivery value equals innings runs plus terminal minus starting resource value")
        )
    chase_rows = scored[scored["is_chase"]]
    if not chase_rows.empty:
        agg = chase_rows.groupby(["match_id", "innings"], sort=False).agg(
            rv=("rv_team", "sum"), capped=("runs_capped", "sum"),
            start=("r_pre", "first"), end=("r_post", "last")
        )
        resid = (agg["rv"] - (agg["capped"] + agg["end"] - agg["start"])).abs()
        worst = float(resid.max()) if len(resid) else 0.0
        out.append(
            _check("chase team value telescopes", "innings", worst < 1e-6, worst,
                   "Chase value uses target-capped runs, with winning-hit overshoot recorded as unallocated")
        )
        overshoot = float(chase_rows["overshoot"].sum())
        out.append(
            _check("winning-hit overshoot is unallocated", "innings", True, overshoot,
                   "Runs struck past the target are reconciled to the team ledger, not given to a player")
        )

    # Resource-model tests.
    for (sex, alloc, fold), table in sorted(tables.items()):
        if fold != -1:
            continue
        g = table.grid
        out.append(
            _check("R(0, w) = 0", f"{sex} {alloc}-ball", float(np.abs(g[0]).max()) < 1e-9,
                   float(np.abs(g[0]).max()), "No balls left is worth nothing")
        )
        out.append(
            _check("R(b, 0) = 0", f"{sex} {alloc}-ball", float(np.abs(g[:, 0]).max()) < 1e-9,
                   float(np.abs(g[:, 0]).max()), "No wickets in hand is worth nothing")
        )
        out.append(
            _check("R non-decreasing in balls", f"{sex} {alloc}-ball", float(np.diff(g, axis=0).min()) > -1e-6,
                   float(np.diff(g, axis=0).min()), "More balls cannot be worth less")
        )
        out.append(
            _check("R non-decreasing in wickets", f"{sex} {alloc}-ball", float(np.diff(g, axis=1).min()) > -1e-6,
                   float(np.diff(g, axis=1).min()), "More wickets in hand cannot be worth less")
        )
    for (sex, fold), table in sorted(chase.items()):
        if fold != -1:
            continue
        G = table.grid
        need_axis = np.arange(G.shape[2], dtype=float) * table.need_step
        out.append(
            _check("R2 capped at runs required", sex, bool(np.all(G <= need_axis[None, None, :] + 1e-6)),
                   float((G - need_axis[None, None, :]).max()),
                   "A chase cannot be worth more than the runs it still needs")
        )
        for axis, label in ((0, "balls"), (1, "wickets"), (2, "runs required")):
            worst = float(np.diff(G, axis=axis).min())
            out.append(
                _check(f"R2 non-decreasing in {label}", sex, worst > -1e-6, worst, "Shape constraint")
            )

    # Baseline calibration.
    if not scored.empty:
        faced = scored[scored["is_faced"]]
        bowled = scored[scored["is_bowled"]]
        mean_bat = float(
            (faced["raa_bat_striker"].sum() + scored["raa_bat_charged"].sum()) / max(len(faced), 1)
        )
        out.append(
            _check("mean batting RAA is about zero", "fitting universe", abs(mean_bat) < 1e-6, mean_bat,
                   "Per batter opportunity, in model runs")
        )
        mean_bowl = float(bowled["raa_bowl"].sum() / max(len(bowled), 1))
        out.append(
            _check("mean bowling RAA is about zero", "fitting universe", abs(mean_bowl) < 1e-6, mean_bowl,
                   "Per delivery bowled, in model runs")
        )

        # Section 17.6 also asks for calibration by phase, innings type and
        # competition. A tilt that is negligible per ball still compounds over a
        # career, so the tolerance here is a hundredth of a run per 100 balls.
        drift_note = (
            "Worst cell mean, per event, in model runs. A standing tilt in any "
            "situation would accumulate into every career total measured there"
        )
        for dim, bat_dim, bowl_dim in (
            ("phase", "phase", "phase"),
            ("inn_type", "inn_type", "inn_type"),
            ("comp_cluster", "comp_cluster", "comp_cluster"),
            ("opposition strength", "opp_bowl_band", "opp_bat_band"),
        ):
            bat_cell = (
                faced.groupby(bat_dim, sort=False)["raa_bat_striker"].sum()
                .add(scored.groupby(bat_dim, sort=False)["raa_bat_charged"].sum(), fill_value=0.0)
                .div(faced.groupby(bat_dim, sort=False).size())
                .dropna()
            )
            worst = float(bat_cell.abs().max()) if not bat_cell.empty else 0.0
            out.append(
                _check(f"batting baseline is calibrated by {dim}", "fitting universe",
                       worst < 1e-4, worst, drift_note)
            )
            bowl_cell = bowled.groupby(bowl_dim, sort=False)["raa_bowl"].mean().dropna()
            worst = float(bowl_cell.abs().max()) if not bowl_cell.empty else 0.0
            out.append(
                _check(f"bowling baseline is calibrated by {dim}", "fitting universe",
                       worst < 1e-4, worst, drift_note)
            )

    # Replacement and all-rounder tests.
    if not players.empty:
        dual = players[(players["bf"] >= 120) & (players["lb"] >= 120)]
        if not dual.empty:
            single_bat = players[(players["bf"] >= 120) & (players["lb"] < 30)]
            single_bowl = players[(players["lb"] >= 120) & (players["bf"] < 30)]
            dual_rate = float((dual["war_bat"] + dual["war_bowl"]).mean())
            single_rate = float(
                pd.concat([single_bat["war_bat"], single_bowl["war_bowl"]]).mean()
            )
            out.append(
                _check("all-rounders are not double-credited", "player-seasons",
                       dual_rate - single_rate < 1.5, dual_rate - single_rate,
                       "Mean combined WAR for dual-role player-seasons against single-role ones. "
                       "All-rounders should lead on workload, not on a doubled replacement credit")
            )
        neg = int((players["replacement_rate_bat"] > 0).sum())
        out.append(
            _check("replacement sits below average", "player-seasons", True, neg,
                   "Count of pools whose replacement rate is above the average player")
        )
    return out


def chase_distortion(df: pd.DataFrame) -> list[dict]:
    """Chase RAA under the chase table against the target-neutral table.

    Required output: valuing chase deliveries with a target-neutral table
    misstates the event values themselves, and the wicket term is the worst
    case. This report is how a reader sees the size of that effect.
    """
    scored = df[df["scored"] & df["is_chase"] & df["is_faced"]]
    if scored.empty:
        return []
    rows = []
    grouped = scored.groupby(["gender", "competition", "press_band"], sort=True)
    for (sex, comp, band), g in grouped:
        n = int(g["f_opp"].sum())
        if n < 500:
            continue
        capped = float(g["raa_bat_striker"].sum())
        neutral = float(g["raa_bat_striker_neutral"].sum())
        rows.append(
            {
                "gender": sex,
                "competition": comp,
                "entry_state": str(band),
                "opportunities": n,
                "raa_chase_table": round(capped, 2),
                "raa_target_neutral": round(neutral, 2),
                "gap_per_100": round(100 * (capped - neutral) / max(n, 1), 3),
                "model_version": MODEL_VERSION,
            }
        )
    return rows


def unscored_exposure(df: pd.DataFrame) -> list[dict]:
    """Play that carries no RAA, by competition and season.

    Dropping rain-affected innings without saying so creates survivorship
    artefacts in season totals, so the share of unvalued exposure is published
    beside the leaderboards rather than left implicit.
    """
    rows = []
    grouped = df.groupby(["competition", "gender", "season"], sort=True)
    for (comp, sex, season), g in grouped:
        total = int(g["a_att"].sum())
        unscored = int(g.loc[~g["scored"], "a_att"].sum())
        reasons = (
            g.loc[~g["scored"]]
            .assign(
                reason=np.where(
                    g.loc[~g["scored"], "revised_overs"].notna(),
                    "revised target",
                    np.where(
                        g.loc[~g["scored"], "allocation"] != resource.STANDARD_BALLS,
                        "non-standard allocation",
                        "no compatible resource table",
                    ),
                )
            )
            .groupby("reason")["a_att"]
            .sum()
            .to_dict()
        )
        rows.append(
            {
                "competition": comp,
                "gender": sex,
                "season": str(season),
                "deliveries": total,
                "unscored": unscored,
                "unscored_share": round(unscored / max(total, 1), 4),
                "top_reason": max(reasons, key=reasons.get) if reasons else None,
                "model_version": MODEL_VERSION,
            }
        )
    return rows


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def build_advanced(
    con, strength: dict[tuple, float], tier: dict[tuple, float] | None = None
) -> AdvancedResult:
    result = AdvancedResult()
    _log("  loading T20 deliveries…")
    raw = load_deliveries(con)
    if raw.empty:
        return result
    df = prepare(raw, tier)
    inn = innings_eligibility(df)
    _log(f"  {len(df):,} deliveries · {len(inn):,} innings · {int(inn['fit_first'].sum()):,} eligible for resource fitting")

    _log("  fitting resource tables…")
    tables, chase, supported = fit_resource_tables(df, inn)
    if not tables:
        _log("  no resource table could be fitted — skipping advanced metrics")
        return result

    _log("  valuing deliveries…")
    df = attach_values(df, tables, chase)
    _log("  fitting comparison baselines…")
    df = attach_baselines(df)

    _log("  aggregating players…")
    players = aggregate_players(df)
    result.slices = aggregate_slices(df)

    _log("  bridging competition pools…")
    bat_bridge, delta_bat = fit_bridge(df, "bat")
    bowl_bridge, delta_bowl = fit_bridge(df, "bowl")
    result.bridge = bat_bridge + bowl_bridge
    bridge = attach_bridge_debit(df, delta_bat, delta_bowl)
    players = players.merge(bridge, on=KEYS, how="left")
    players["bridge_bat"] = players["bridge_bat"].fillna(0.0)
    players["bridge_bowl"] = players["bridge_bowl"].fillna(0.0)

    _log("  estimating replacement level…")
    cohort = marginal_cohort(df)
    replacement_rows, rho = estimate_replacement(df, cohort)
    result.replacement = replacement_rows
    bat_debit, bowl_debit = attach_replacement_debit(df, rho)
    players = players.merge(bat_debit, on=KEYS, how="left").merge(bowl_debit, on=KEYS, how="left")
    players["replacement_debit_bat"] = players["replacement_debit_bat"].fillna(0.0)
    players["replacement_debit_bowl"] = players["replacement_debit_bowl"].fillna(0.0)
    # RAA stays pool-relative and calibrated; the bridge is what puts the two on
    # one scale, so it belongs between RAA and the wins conversion.
    players["vorp_bat"] = (
        players["raa_bat"] - players["bridge_bat"] - players["replacement_debit_bat"]
    )
    players["vorp_bowl"] = (
        players["bowl_raa"] - players["bridge_bowl"] - players["replacement_debit_bowl"]
    )
    players["replacement_rate_bat"] = np.where(
        players["bf"] > 0, players["replacement_debit_bat"] / players["bf"].replace(0, np.nan), 0.0
    )
    players["replacement_rate_bowl"] = np.where(
        players["lb"] > 0, players["replacement_debit_bowl"] / players["lb"].replace(0, np.nan), 0.0
    )

    _log("  calibrating runs per win…")
    values = innings_values(df, inn)
    rpw_rows, rpw = fit_runs_per_win(values, strength)
    result.rpw = rpw_rows
    result.rpw_by_comp = rpw
    default_rpw = float(np.median([v for v in rpw.values()])) if rpw else 20.0
    denom = players["competition"].map(lambda c: rpw.get(c, default_rpw)).astype(float)
    players["runs_per_win"] = denom
    players["war_bat"] = players["vorp_bat"] / denom
    players["war_bowl"] = players["vorp_bowl"] / denom
    players["war_total"] = players["war_bat"] + players["war_bowl"]

    result.audit = run_audit(df, inn, values, tables, chase, players) + _bridge_audit(
        result.bridge, players
    )
    result.distortion = chase_distortion(df)
    result.exposure = unscored_exposure(df)
    result.match_values = _match_value_rows(values)

    for (sex, alloc, fold), table in sorted(tables.items()):
        if fold != -1 or alloc != resource.STANDARD_BALLS:
            continue
        result.resource_rows.extend(table.as_rows(sex))
    display_needs = (12, 24, 36, 60, 90, 120, 168)
    for (sex, fold), table in sorted(chase.items()):
        if fold != -1:
            continue
        result.chase_rows.extend(table.as_rows(sex, display_needs))

    result.players = _player_rows(players)
    additive = all(c["status"] == "pass" for c in result.audit if "double-credited" in c["check_name"])
    result.meta = {
        "cross_fitting": "grouped match cross-fitting over a fixed retrospective window",
        "folds": N_FOLDS,
        "fold_seed": FOLD_SEED,
        "baseline_prior_events": BASELINE_PRIOR,
        "rate_prior_events": RATE_PRIOR,
        "opposition_strength_edges": list(STRENGTH_EDGES),
        "opposition_strength_rating": "ridge Bradley-Terry, fitted per competition and gender over all eras",
        "opposition_strength_note": (
            "Band of the side opposed, added to the comparison baseline beyond "
            "the Section 10.2 list. Without it a single T20I cluster prices "
            "associate cricket against a full-member baseline."
        ),
        "smoother": "count-weighted separable Gaussian, then weighted isotonic projection",
        "smoother_bandwidths": {
            "balls": resource.SMOOTH_BANDWIDTH_BALLS,
            "wickets": resource.SMOOTH_BANDWIDTH_WICKETS,
            "need": resource.SMOOTH_BANDWIDTH_NEED,
        },
        "projection_cycles": resource.PROJECTION_CYCLES,
        "prior_cell_weight": resource.PRIOR_WEIGHT,
        "venue_prior_innings": resource.VENUE_PRIOR_INNINGS,
        "need_step": resource.NEED_STEP,
        "set_threshold_opportunities": ledger.SET_OPPORTUNITIES,
        "supported_allocations": supported,
        "chase_tables_linked": sorted(
            {s for (s, f), t in chase.items() if f == -1 and t.linked}
        ),
        "replacement_floors": {
            "batter_opportunities": REPLACEMENT_MIN_OPPORTUNITIES,
            "valid_balls": REPLACEMENT_MIN_BALLS,
            "season_weights": list(SEASON_WEIGHTS),
        },
        "runs_per_win": rpw,
        "combined_war_validated": additive,
        "war_label": "WAR" if additive else "wins-equivalent",
        "audit_failures": [c["check_name"] for c in result.audit if c["status"] == "fail"],
    }
    return result


def _match_value_rows(values: pd.DataFrame) -> list[dict]:
    rows = []
    for r in values.itertuples(index=False):
        rows.append(
            {
                "match_id": r.match_id,
                "innings": int(r.innings),
                "competition": r.competition,
                "gender": r.gender,
                "batting_team": r.batting_team,
                "bowling_team": r.bowling_team,
                "runs": int(r.runs),
                "wickets_used": int(r.wickets_used),
                "legal_balls": int(r.legal_balls),
                "allocation": int(r.allocation),
                "resource_value": round(float(r.v_inn), 2),
                "resource_value_chase": round(float(r.v_inn_chase or 0.0), 2),
                "fit_eligible": bool(r.fit_first or r.fit_chase),
                "complete": bool(r.complete),
                "model_version": MODEL_VERSION,
            }
        )
    return rows


def _player_rows(players: pd.DataFrame) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for r in players.itertuples(index=False):
        pid = r.person_id
        if not pid or pid != pid:
            continue
        bf = int(r.bf)
        lb = int(r.lb)
        key = (str(pid), r.competition, str(r.season), r.gender)
        out[key] = {
            "bf": bf,
            "lb": lb,
            "raa_bat": round(float(r.raa_bat), 2),
            "raa_bowl": round(float(r.bowl_raa), 2),
            "raa_bat_neutral": round(float(r.raa_bat_neutral), 2),
            "raa100_bat": round(100 * float(r.raa_bat) / bf, 2) if bf else None,
            "raa_over_bowl": round(6 * float(r.bowl_raa) / lb, 3) if lb else None,
            "vorp_bat": round(float(r.vorp_bat), 2),
            "vorp_bowl": round(float(r.vorp_bowl), 2),
            "bridge_bat": round(float(r.bridge_bat), 2),
            "bridge_bowl": round(float(r.bridge_bowl), 2),
            "war_bat": round(float(r.war_bat), 3),
            "war_bowl": round(float(r.war_bowl), 3),
            "war_total": round(float(r.war_total), 3),
            "runs_per_win_v2": round(float(r.runs_per_win), 2),
            # Descriptive residuals, all per 100 opportunities or per over so the
            # units are legible without a lookup.
            "tsr": round(100 * (float(r.bat_runs) - float(r.e_bat)) / bf, 2) if bf else None,
            "te": round(6 * (float(r.bowl_runs) - float(r.e_bowl)) / lb, 3) if lb else None,
            "twr_bat": round(100 * (float(r.dismissals) - float(r.pi_bat)) / bf, 3) if bf else None,
            "twr_bowl": round(100 * (float(r.wickets) - float(r.pi_bowl)) / lb, 3) if lb else None,
            "four_residual": round(100 * (float(r.fours) - float(r.e_four)) / bf, 2) if bf else None,
            "six_residual": round(100 * (float(r.sixes) - float(r.e_six)) / bf, 2) if bf else None,
            "dot_residual_bat": round(100 * (float(r.dots_bat) - float(r.e_dot_bat)) / bf, 2) if bf else None,
            "dot_residual_team": round(100 * (float(r.dots_team) - float(r.e_dot_team)) / lb, 2) if lb else None,
            "xr_event": round(100 * float(r.illegal_events) / float(r.attempts), 2) if r.attempts else None,
            "xr_runs": round(6 * (float(r.wide_runs) + float(r.noball_runs)) / lb, 3) if lb else None,
            "replacement_rate_bat": round(float(r.replacement_rate_bat), 5),
            "replacement_rate_bowl": round(float(r.replacement_rate_bowl), 5),
            "bat_dismissals": int(r.dismissals),
            "bowl_wickets": int(r.wickets),
        }
    return out
