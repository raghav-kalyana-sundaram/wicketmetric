from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

import duckdb
import numpy as np
import pandas as pd

from cricwarehouse import MODEL_VERSION
from cricwarehouse.competitions import T20_METRICS
from cricwarehouse.paths import WAREHOUSE
from cricwarehouse.app import advanced
from cricwarehouse.app.db import write_parquet
from cricwarehouse.app.resource import era_label

PRESSURE_K = 1.0
DLS_CONFIDENCE_THRESHOLD = 0.25
REPLACEMENT_PERCENTILE = 20
DEFAULT_WEIGHTS = {"rae": 0.45, "wpa": 0.35, "consistency": 0.20}
PERF_WEIGHTS = {"nrc": 0.55, "wpa": 0.35, "press": 0.10}
CONSISTENCY_MIN_INNINGS = 5
CONSISTENCY_MIN_BALLS = 100
LEAGUE_QUAL_BALLS = 60
INTL_TRAIL_BALLS = 60
INTL_CAREER_BALLS = 100
FALLBACK_RPW = {
    "ipl": 20.0,
    "bbl": 20.0,
    "wpl": 18.0,
    "wbbl": 18.0,
    "t20i": 22.0,
}


def _log(msg: str) -> None:
    print(msg, flush=True)


def rebuild_metrics() -> None:
    matches_p = WAREHOUSE / "matches.parquet"
    deliveries_p = WAREHOUSE / "deliveries.parquet"
    if not matches_p.exists() or not deliveries_p.exists():
        _log("Application not built yet — skip metrics.")
        return

    con = duckdb.connect(database=":memory:")
    con.execute(f"CREATE VIEW matches AS SELECT * FROM read_parquet('{matches_p}')")
    con.execute(f"CREATE VIEW deliveries AS SELECT * FROM read_parquet('{deliveries_p}')")
    con.execute(f"CREATE VIEW innings AS SELECT * FROM read_parquet('{(WAREHOUSE / 'innings.parquet')}')")
    con.execute(f"CREATE VIEW batting_lines AS SELECT * FROM read_parquet('{(WAREHOUSE / 'batting_lines.parquet')}')")
    con.execute(f"CREATE VIEW bowling_lines AS SELECT * FROM read_parquet('{(WAREHOUSE / 'bowling_lines.parquet')}')")

    t20 = con.execute(
        """
        SELECT match_id, start_date, gender, competition, season, winner,
               team_home, team_away, result_method, scheduled_overs,
               revised_overs, revised_target, balls_per_over
        FROM matches
        WHERE competition IN ('t20i','ipl','wpl','bbl','wbbl')
        """
    ).fetchdf()
    if t20.empty:
        _log("No T20 matches in the application.")
        write_parquet("metrics_t20", [])
        write_parquet("team_strength", [])
        write_parquet("super_over_stats", [])
        return

    t20 = t20.sort_values("start_date")
    strength_rows = _elo(t20)
    write_parquet("team_strength", strength_rows)
    # Two different questions. Elo tracks form going into a match and controls
    # the runs-per-win fit; the Bradley-Terry tier is comparable across the whole
    # fixture graph and is what the comparison baselines condition on.
    strength_asof = _strength_lookup(strength_rows)
    strength_tier = _bradley_terry(t20)

    balls = con.execute(
        """
        SELECT d.*, m.competition, m.gender, m.season, m.start_date,
               m.winner, m.result_method, m.scheduled_overs, m.revised_target,
               m.revised_overs, m.team_home, m.team_away, m.balls_per_over, m.venue
        FROM deliveries d
        JOIN matches m ON m.match_id = d.match_id
        WHERE m.competition IN ('t20i','ipl','wpl','bbl','wbbl')
          AND d.innings_kind = 'regular'
        ORDER BY d.match_id, d.innings, d.legal_ball_index, d.over, d.ball_in_over
        """
    ).fetchdf()

    # Super-over display stats (never enter metric inputs)
    so = con.execute(
        """
        SELECT d.striker AS person_id,
               COUNT(DISTINCT d.match_id) AS matches,
               SUM(CASE WHEN d.striker IS NOT NULL AND NOT d.is_wide THEN 1 ELSE 0 END) AS balls_faced,
               SUM(CASE WHEN d.striker IS NOT NULL THEN d.runs_batter ELSE 0 END) AS runs,
               SUM(CASE WHEN d.bowler IS NOT NULL AND d.is_legal THEN 1 ELSE 0 END) AS balls_bowled,
               SUM(CASE WHEN d.bowler IS NOT NULL THEN
                    d.runs_batter + CASE WHEN d.extra_type IN ('wides','noballs') THEN d.runs_extras ELSE 0 END
                   ELSE 0 END) AS runs_conceded,
               SUM(CASE WHEN d.bowler IS NOT NULL AND d.wicket_kind IN
                    ('bowled','caught','caught and bowled','lbw','stumped','hit wicket') THEN 1 ELSE 0 END) AS wickets
        FROM deliveries d
        JOIN matches m ON m.match_id = d.match_id
        WHERE d.innings_kind = 'super_over'
        GROUP BY d.striker
        """
    ).fetchdf()
    so_bowl = con.execute(
        """
        SELECT d.bowler AS person_id,
               COUNT(DISTINCT d.match_id) AS matches,
               SUM(CASE WHEN d.is_legal THEN 1 ELSE 0 END) AS balls_bowled,
               SUM(d.runs_batter + CASE WHEN d.extra_type IN ('wides','noballs') THEN d.runs_extras ELSE 0 END) AS runs_conceded,
               SUM(CASE WHEN d.wicket_kind IN
                    ('bowled','caught','caught and bowled','lbw','stumped','hit wicket') THEN 1 ELSE 0 END) AS wickets
        FROM deliveries d
        WHERE d.innings_kind = 'super_over' AND d.bowler IS NOT NULL
        GROUP BY d.bowler
        """
    ).fetchdf()
    so_rows = _merge_super_over(so, so_bowl)
    write_parquet("super_over_stats", so_rows)

    if balls.empty:
        write_parquet("metrics_t20", [])
        _write_meta({})
        return

    balls["over_bucket"] = (balls["over"].clip(lower=0) // 5).clip(upper=3).astype(int)
    balls["sched_bucket"] = balls["scheduled_overs"].fillna(20).astype(float).round().astype(int)

    balls = balls.copy()
    retired = {"retired hurt", "retired not out", "absent hurt", "absent ill"}
    wkt = balls["wicket_kind"].notna() & ~balls["wicket_kind"].isin(retired)
    grp = [balls["match_id"], balls["innings"]]
    balls["runs_before"] = balls.groupby(grp, sort=False)["runs_total"].cumsum() - balls["runs_total"].fillna(0)
    legal_i = balls["is_legal"].fillna(False).astype(int)
    balls["legal_before"] = balls.groupby(grp, sort=False)["is_legal"].transform(
        lambda s: s.fillna(False).astype(int).cumsum()
    ) - legal_i
    balls["wkts_before"] = balls.groupby(grp, sort=False)["wicket_kind"].transform(
        lambda s: (s.notna() & ~s.isin(retired)).astype(int).cumsum()
    ) - wkt.astype(int)

    balls["wkts_bucket"] = balls["wkts_before"].clip(upper=8)
    # opposition strength
    balls["opp_bowl_rating"] = [
        strength_asof.get((bt, g, c, d), 1500.0)
        for bt, g, c, d in zip(balls["bowling_team"], balls["gender"], balls["competition"], balls["start_date"])
    ]
    balls["own_bat_rating"] = [
        strength_asof.get((bt, g, c, d), 1500.0)
        for bt, g, c, d in zip(balls["batting_team"], balls["gender"], balls["competition"], balls["start_date"])
    ]

    # Empirical xR: mean batter runs by state, then opposition tilt
    grp_cols = ["competition", "gender", "over_bucket", "wkts_bucket", "innings", "sched_bucket"]
    means = balls.groupby(grp_cols, dropna=False)["runs_batter"].mean().rename("xr_base")
    balls = balls.join(means, on=grp_cols)
    global_mean = float(balls["runs_batter"].mean() or 0.8)
    balls["xr_base"] = balls["xr_base"].fillna(global_mean)
    balls["xr"] = balls["xr_base"] * (1.0 + 0.15 * (balls["opp_bowl_rating"] - 1500.0) / 400.0)
    balls["xr"] = balls["xr"].clip(lower=0.05, upper=3.5)

    balls["charged"] = balls["runs_batter"] + np.where(
        balls["extra_type"].isin(["wides", "noballs"]), balls["runs_extras"], 0
    )
    balls["rae_bat_ball"] = np.where(balls["striker"].notna() & ~balls["is_wide"], balls["runs_batter"] - balls["xr"], 0.0)
    balls["rae_bowl_ball"] = np.where(balls["bowler"].notna(), balls["xr"] - balls["charged"], 0.0)

    # WPA
    balls = _attach_wpa(balls)

    # Pressure
    sched_balls = (balls["scheduled_overs"].fillna(20) * balls["balls_per_over"].fillna(6)).astype(float)
    balls_left = (sched_balls - balls["legal_before"]).clip(lower=1)
    required = np.where(
        balls["innings"] == 2,
        np.maximum((balls["revised_target"].fillna(0) - balls["runs_before"]).clip(lower=0) / balls_left, 0),
        0,
    )
    expected_rem = balls["xr"].clip(lower=0.2)
    chase_p = np.clip((required - expected_rem) / 1.5, 0, 1)
    death_p = np.where((balls["innings"] == 1) & (balls["over"] >= 16), 0.6, 0.0)
    balls["pressure"] = np.where(balls["innings"] == 2, chase_p, death_p)
    balls["pressure_impact"] = balls["rae_bat_ball"] * (1 + PRESSURE_K * balls["pressure"])
    balls["pressure_bowl"] = balls["rae_bowl_ball"] * (1 + PRESSURE_K * balls["pressure"])

    # Aggregate player-season-competition
    metrics = _aggregate(balls)
    rpw = _fit_runs_per_win(t20, balls)
    metrics = _apply_war(metrics, rpw)

    # The resource-based engine. It supplies the published WAR; the descriptive
    # layer above stays as the utility index the sliders drive.
    _log("Building resource-based value model…")
    adv = advanced.build_advanced(con, strength_asof, strength_tier)
    metrics = _merge_advanced(metrics, adv)
    _write_advanced_tables(adv)

    write_parquet("metrics_t20", metrics)
    perfs = _score_performances(balls, rpw)
    write_parquet("performances_t20", perfs)
    _write_meta(rpw, adv)
    _log(
        f"metrics_t20 rows: {len(metrics):,}  performances: {len(perfs):,}  "
        f"model_version={MODEL_VERSION}"
    )


ADVANCED_FIELDS = (
    "bf",
    "lb",
    "raa_bat",
    "raa_bowl",
    "raa_bat_neutral",
    "raa100_bat",
    "raa_over_bowl",
    "vorp_bat",
    "vorp_bowl",
    "war_bat",
    "war_bowl",
    "war_total",
    "runs_per_win_v2",
    "tsr",
    "te",
    "twr_bat",
    "twr_bowl",
    "four_residual",
    "six_residual",
    "dot_residual_bat",
    "dot_residual_team",
    "xr_event",
    "xr_runs",
    "replacement_rate_bat",
    "replacement_rate_bowl",
    "bat_dismissals",
    "bowl_wickets",
)


def _merge_advanced(metrics: list[dict], adv) -> list[dict]:
    """Attach the resource-model numbers to each player-season row.

    `war` becomes the resource-model figure so every existing leaderboard reads
    from the same engine; the descriptive index keeps its own column so the two
    stay comparable rather than silently replaced.
    """
    if not adv.players:
        for row in metrics:
            row["war_v1"] = row.get("war")
            for field in ADVANCED_FIELDS:
                row.setdefault(field, None)
            row["war_label"] = "wins-equivalent"
        return metrics
    label = adv.meta.get("war_label", "WAR")
    for row in metrics:
        key = (str(row["person_id"]), row["competition"], str(row["season"]), row["gender"])
        found = adv.players.get(key) or {}
        row["war_v1"] = row.get("war")
        for field in ADVANCED_FIELDS:
            row[field] = found.get(field)
        row["war"] = found.get("war_total")
        row["war_label"] = label
    return metrics


def _write_advanced_tables(adv) -> None:
    write_parquet("resource_grid", adv.resource_rows)
    write_parquet("chase_grid", adv.chase_rows)
    write_parquet("raa_slices_t20", adv.slices)
    write_parquet("replacement_t20", adv.replacement)
    write_parquet("pool_bridge_t20", adv.bridge)
    write_parquet("runs_per_win_t20", adv.rpw)
    write_parquet("match_value_t20", adv.match_values)
    write_parquet("model_audit", adv.audit)
    write_parquet("unscored_exposure", adv.exposure)
    write_parquet("chase_distortion", adv.distortion)
    failures = [c for c in adv.audit if c["status"] == "fail"]
    if failures:
        _log(f"  audit: {len(failures)} failing check(s) — see the Model page")
        for c in failures[:8]:
            _log(f"    fail · {c['check_name']} · {c['scope']} · {c['value']}")
    else:
        _log(f"  audit: {len(adv.audit)} checks pass")


def _elo(t20) -> list[dict]:
    rating: dict[tuple[str, str, str], float] = defaultdict(lambda: 1500.0)
    history: list[dict] = []
    last_date: dict[tuple[str, str, str], str] = {}
    k = 20.0
    for row in t20.itertuples(index=False):
        if not row.winner or row.result_method == "no_result":
            continue
        family = row.competition
        g = row.gender
        home, away = row.team_home, row.team_away
        rh = rating[(home, g, family)]
        ra = rating[(away, g, family)]
        eh = 1 / (1 + 10 ** ((ra - rh) / 400))
        score_h = 1.0 if row.winner == home else 0.0
        if row.result_method == "tie":
            score_h = 0.5
        rating[(home, g, family)] = rh + k * (score_h - eh)
        rating[(away, g, family)] = ra + k * ((1 - score_h) - (1 - eh))
        last_date[(home, g, family)] = row.start_date
        last_date[(away, g, family)] = row.start_date
        for team, before, val in (
            (home, rh, rating[(home, g, family)]),
            (away, ra, rating[(away, g, family)]),
        ):
            history.append(
                {
                    "team": team,
                    "gender": g,
                    "competition_family": family,
                    "as_of_date": row.start_date,
                    "batting_rating": float(val),
                    "bowling_rating": float(val),
                    # The rating the side carried into this match. Anything that
                    # conditions on strength has to use this one, or the match
                    # result leaks into its own covariate.
                    "pre_rating": float(before),
                }
            )
    return history


BT_RIDGE = 3.0
BT_MIN_MATCHES = 60


def _bradley_terry(t20) -> dict[tuple, float]:
    """Team ratings on one comparable scale, solved globally per era.

    Sequential Elo answers "how well has this side done against the sides it
    happens to play", which is not the same question. Associate nations play
    mostly each other, so their ratings drift on a scale that never meets the
    full members': on this application Elo puts Uganda above Australia. Solving
    the whole fixture graph at once instead lets the handful of cross-tier games
    anchor everyone, and the ridge penalty pulls thinly connected sides toward
    the middle rather than letting them run away.

    The result is a tier, not form, which is what a comparison baseline needs.

    The fit pools every era. Cutting it by era would let a side's rating follow
    its rise or decline, but it also thins the cross-tier fixtures that hold the
    scale together, and the ordering collapses again: fitted per era, this data
    puts Uganda above Australia. One rating per side, coarsely banded, is the
    more robust read.
    """
    out: dict[tuple, float] = {}
    played = t20[t20["winner"].notna() & (t20["result_method"] != "no_result")]
    if played.empty:
        return out
    for pool, g in played.groupby(["competition", "gender"], sort=False):
        if len(g) < BT_MIN_MATCHES:
            continue
        teams = pd.Index(sorted(set(g["team_home"]) | set(g["team_away"])))
        pos = {t: i for i, t in enumerate(teams)}
        X = np.zeros((len(g), len(teams) + 1))
        X[:, 0] = 1.0
        for row, (h, a) in enumerate(zip(g["team_home"], g["team_away"])):
            X[row, 1 + pos[h]] += 1.0
            X[row, 1 + pos[a]] -= 1.0
        y = (g["winner"].to_numpy() == g["team_home"].to_numpy()).astype(float)
        y[g["result_method"].to_numpy() == "tie"] = 0.5

        penalty = np.eye(len(teams) + 1) * BT_RIDGE
        # The intercept is home advantage and is not shrunk.
        penalty[0, 0] = 0.0
        beta = np.zeros(len(teams) + 1)
        for _ in range(60):
            p = 1.0 / (1.0 + np.exp(-(X @ beta)))
            w = p * (1.0 - p) + 1e-9
            hess = X.T @ (X * w[:, None]) + penalty
            grad = X.T @ (y - p) - penalty @ beta
            try:
                step = np.linalg.solve(hess, grad)
            except np.linalg.LinAlgError:
                break
            beta += step
            if np.abs(step).max() < 1e-9:
                break
        # Back onto the familiar 1500-centred Elo scale so the two ratings read
        # against each other.
        comp, sex = pool
        for team, val in zip(teams, beta[1:]):
            out[(team, sex, comp)] = float(val * 400.0 / np.log(10.0) + 1500.0)
    return out


def _strength_lookup(rows: list[dict]) -> dict[tuple, float]:
    by_key: dict[tuple, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        by_key[(r["team"], r["gender"], r["competition_family"])].append(
            (r["as_of_date"], r["bowling_rating"])
        )
    for k in by_key:
        by_key[k].sort()

    cache: dict[tuple, float] = {}
    for r in rows:
        cache[(r["team"], r["gender"], r["competition_family"], r["as_of_date"])] = r["pre_rating"]
    return cache


def _attach_wpa(balls):
    # First-innings expected remaining runs by state → projected total → historical P(win)
    first = balls[balls["innings"] == 1]
    rem = first.groupby(["competition", "gender", "over_bucket", "wkts_bucket"], dropna=False)["runs_total"].mean()
    # Historical P(bat first wins | projected score bucket)
    finals = (
        first.groupby(["match_id", "competition", "gender", "winner", "batting_team"], dropna=False)["runs_total"]
        .sum()
        .reset_index()
        .rename(columns={"runs_total": "final_score"})
    )
    finals["won"] = finals["winner"] == finals["batting_team"]
    finals["score_bucket"] = (finals["final_score"] // 10 * 10).astype(int)
    pwin_lookup = finals.groupby(["competition", "gender", "score_bucket"])["won"].mean().to_dict()
    default_p = float(finals["won"].mean() or 0.5)

    # Second innings: logistic-style from empirical chase success
    second = balls[balls["innings"] == 2]
    # Use match-level chase result
    chase = (
        second.groupby(
            ["match_id", "competition", "gender", "winner", "batting_team", "revised_target"],
            dropna=False,
        )["runs_total"]
        .sum()
        .reset_index()
    )
    # We'll compute ball-level P from a simple logistic on (runs_needed, balls_left, wkts_left)
    # Fit on second-innings snapshots every 6 legal balls
    snaps = second.iloc[::6].copy()
    sched = (snaps["scheduled_overs"].fillna(20) * snaps["balls_per_over"].fillna(6)).astype(float)
    snaps["balls_left"] = (sched - snaps["legal_before"]).clip(lower=1)
    target = snaps["revised_target"].fillna(snaps.groupby("match_id")["runs_before"].transform("max") + 1)
    # fallback target: first innings score + 1 from match
    snaps["runs_needed"] = (target - snaps["runs_before"]).clip(lower=0)
    snaps["wkts_left"] = (10 - snaps["wkts_before"]).clip(lower=1)
    snaps["y"] = (snaps["winner"] == snaps["batting_team"]).astype(float)
    X = np.column_stack(
        [
            np.ones(len(snaps)),
            (snaps["runs_needed"] / snaps["balls_left"]).to_numpy(),
            snaps["wkts_left"].to_numpy(),
            (snaps["balls_left"] / 120.0).to_numpy(),
        ]
    )
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    y = snaps["y"].to_numpy()
    if len(snaps) > 50:
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            beta = np.array([0.5, -0.4, 0.05, 0.2])
    else:
        beta = np.array([0.5, -0.4, 0.05, 0.2])

    def sigmoid(z):
        return 1 / (1 + np.exp(-np.clip(z, -12, 12)))

    def _num(v, default=0.0):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return default
        try:
            if pd.isna(v):
                return default
        except Exception:
            pass
        return float(v)

    p_before = []
    for row in balls.itertuples(index=False):
        sched = _num(row.scheduled_overs, 20)
        bpo = _num(row.balls_per_over, 6)
        legal_before = _num(row.legal_before, 0)
        runs_before = _num(row.runs_before, 0)
        wkts_before = int(_num(row.wkts_before, 0))
        if row.innings == 1:
            rem_key = (row.competition, row.gender, row.over_bucket, min(wkts_before, 8))
            rem_rate = rem.get(rem_key, 1.0)
            if pd.isna(rem_rate):
                rem_rate = 1.0
            balls_left = max(sched * bpo - legal_before, 1)
            proj = runs_before + rem_rate * balls_left
            bucket = int(proj // 10 * 10)
            p = pwin_lookup.get((row.competition, row.gender, bucket), default_p)
            p_before.append(float(np.clip(p, 0.02, 0.98)))
        else:
            bl = max(sched * bpo - legal_before, 1)
            tgt = _num(row.revised_target, runs_before + 50)
            needed = max(tgt - runs_before, 0)
            wl = max(10 - wkts_before, 1)
            z = beta[0] + beta[1] * (needed / bl) + beta[2] * wl + beta[3] * (bl / 120.0)
            p_before.append(float(np.clip(z if 0 <= z <= 1 else sigmoid(z * 2 - 1), 0.02, 0.98)))

    balls = balls.copy()
    balls["p_before"] = p_before
    # p_after ≈ next ball's p_before; last ball of innings uses result
    p_after = balls.groupby(["match_id", "innings"])["p_before"].shift(-1)
    # fill last ball from actual result
    won = (balls["winner"] == balls["batting_team"]).astype(float)
    balls["p_after"] = p_after.fillna(won.clip(0.02, 0.98))
    balls["wpa_ball"] = balls["p_after"] - balls["p_before"]
    return balls


def _aggregate(balls) -> list[dict]:
    rows: list[dict] = []
    grouped = balls.groupby(["striker", "competition", "season", "gender"], dropna=False)
    bat = grouped.agg(
        balls_bat=("rae_bat_ball", "count"),
        rae_bat=("rae_bat_ball", "sum"),
        wpa_bat=("wpa_ball", "sum"),
        pressure_impact=("pressure_impact", "sum"),
        dls_balls=("result_method", lambda s: int((s == "dls").sum())),
        innings=("match_id", "nunique"),
        rae_mad=("rae_bat_ball", lambda s: float(np.mean(np.abs(s - s.mean()))) if len(s) else 0.0),
    ).reset_index().rename(columns={"striker": "person_id"})
    # recount balls faced properly
    bat_balls = balls.loc[balls["striker"].notna() & ~balls["is_wide"]].groupby(
        ["striker", "competition", "season", "gender"]
    ).size().rename("balls_bat")
    bat = bat.drop(columns=["balls_bat"]).join(bat_balls, on=["person_id", "competition", "season", "gender"])
    bat["balls_bat"] = bat["balls_bat"].fillna(0).astype(int)

    bowl = (
        balls.loc[balls["bowler"].notna()]
        .groupby(["bowler", "competition", "season", "gender"])
        .agg(
            balls_bowl=("is_legal", "sum"),
            rae_bowl=("rae_bowl_ball", "sum"),
            wpa_bowl=("wpa_ball", lambda s: float((-s).sum())),
            dls_balls=("result_method", lambda s: int((s == "dls").sum())),
        )
        .reset_index()
        .rename(columns={"bowler": "person_id"})
    )

    keys = ["person_id", "competition", "season", "gender"]
    merged = bat.merge(bowl, on=keys, how="outer", suffixes=("_b", "_o"))
    def _i(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return 0
        try:
            if pd.isna(v):
                return 0
        except Exception:
            pass
        return int(v)

    def _f(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return 0.0
        try:
            if pd.isna(v):
                return 0.0
        except Exception:
            pass
        return float(v)

    for _, r in merged.iterrows():
        pid = r["person_id"]
        if not pid or (isinstance(pid, float) and np.isnan(pid)):
            continue
        balls_bat = _i(r.get("balls_bat"))
        balls_bowl = _i(r.get("balls_bowl"))
        rae_bat = _f(r.get("rae_bat"))
        rae_bowl = _f(r.get("rae_bowl"))
        wpa = _f(r.get("wpa_bat")) + _f(r.get("wpa_bowl"))
        pressure = _f(r.get("pressure_impact"))
        dls_share_n = _i(r.get("dls_balls_b")) + _i(r.get("dls_balls_o"))
        total_b = max(balls_bat + balls_bowl, 1)
        dls_share = dls_share_n / total_b
        role = _role(balls_bat, balls_bowl)
        innings_n = _i(r.get("innings"))
        consistency = _f(r.get("rae_mad"))
        rows.append(
            {
                "person_id": pid,
                "competition": r["competition"],
                "season": str(r["season"]),
                "gender": r["gender"],
                "role": role,
                "balls_bat": balls_bat,
                "balls_bowl": balls_bowl,
                "rae_bat": round(rae_bat, 1),
                "rae_bowl": round(rae_bowl, 1),
                "wpa": round(wpa, 3),
                "pressure_impact": round(pressure, 2),
                "war": None,
                "overall_default": None,
                "confidence": "dls_affected" if dls_share >= DLS_CONFIDENCE_THRESHOLD else "normal",
                "dls_share": round(dls_share, 3),
                "innings": innings_n,
                "consistency_mad": round(consistency, 3),
                "model_version": MODEL_VERSION,
            }
        )
    return rows


def _role(balls_bat: int, balls_bowl: int) -> str:
    if balls_bat >= 60 and balls_bowl >= 60:
        return "allround"
    if balls_bowl > balls_bat:
        return "bowl_middle" if balls_bowl < 120 else "bowl_death"
    if balls_bat < 80:
        return "batter_finish"
    if balls_bat < 160:
        return "batter_middle"
    return "batter_open"


def _fit_runs_per_win(t20, balls) -> dict[str, float]:
    """Regression of team run differential on wins, per competition."""
    rpw = dict(FALLBACK_RPW)
    # team match run diff
    agg = (
        balls.groupby(["match_id", "batting_team", "competition", "gender", "winner"], dropna=False)["runs_total"]
        .sum()
        .reset_index()
    )
    for comp in T20_METRICS:
        sub = agg[agg["competition"] == comp]
        if sub.empty:
            continue
        diffs = []
        wins = []
        for mid, g in sub.groupby("match_id"):
            if len(g) < 2:
                continue
            teams = list(g.itertuples())
            a, b = teams[0], teams[1]
            diff = a.runs_total - b.runs_total
            win = 1.0 if a.winner == a.batting_team else 0.0
            diffs.append(diff)
            wins.append(win)
        if len(diffs) < 30:
            continue
        x = np.array(diffs)
        y = np.array(wins)
        # P(win) ≈ 0.5 + diff / (2 * rpw)  → rpw ≈ std-ish scale
        # Fit y = 0.5 + x / c
        c, *_ = np.linalg.lstsq(np.vstack([x, np.ones_like(x)]).T, y, rcond=None)
        slope = c[0]
        if slope != 0:
            est = abs(1.0 / (2 * slope))
            if 8 < est < 60:
                rpw[comp] = round(float(est), 1)
    return rpw


def _apply_war(metrics: list[dict], rpw: dict[str, float]) -> list[dict]:
    # replacement = 20th percentile of qualifier per-ball RAE
    by_pool: dict[tuple, list[tuple[float, int, str]]] = defaultdict(list)
    for row in metrics:
        pool = (row["competition"], row["season"], row["gender"])
        if row["balls_bat"] >= LEAGUE_QUAL_BALLS:
            by_pool[(*pool, "bat")].append((row["rae_bat"] / max(row["balls_bat"], 1), row["balls_bat"], row["person_id"]))
        if row["balls_bowl"] >= LEAGUE_QUAL_BALLS:
            by_pool[(*pool, "bowl")].append((row["rae_bowl"] / max(row["balls_bowl"], 1), row["balls_bowl"], row["person_id"]))

    repl: dict[tuple, float] = {}
    for key, vals in by_pool.items():
        rates = [v[0] for v in vals]
        repl[key] = float(np.percentile(rates, REPLACEMENT_PERCENTILE)) if rates else 0.0

    # z-score components among qualifiers
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in metrics:
        groups[(row["competition"], row["season"], row["gender"], row["role"])].append(row)

    for key, rows in groups.items():
        raes = [r["rae_bat"] + r["rae_bowl"] for r in rows]
        wpas = [r["wpa"] for r in rows]
        cons = [-(r["consistency_mad"] or 0) for r in rows]
        rae_mu, rae_sd = _mu_sd(raes)
        wpa_mu, wpa_sd = _mu_sd(wpas)
        con_mu, con_sd = _mu_sd(cons)
        for r in rows:
            z_rae = ((r["rae_bat"] + r["rae_bowl"]) - rae_mu) / rae_sd
            z_wpa = (r["wpa"] - wpa_mu) / wpa_sd
            use_cons = r["innings"] >= CONSISTENCY_MIN_INNINGS and (r["balls_bat"] + r["balls_bowl"]) >= CONSISTENCY_MIN_BALLS
            if use_cons:
                z_con = (-(r["consistency_mad"] or 0) - con_mu) / con_sd
                w = DEFAULT_WEIGHTS
                overall_z = w["rae"] * z_rae + w["wpa"] * z_wpa + w["consistency"] * z_con
            else:
                tot = DEFAULT_WEIGHTS["rae"] + DEFAULT_WEIGHTS["wpa"]
                overall_z = (DEFAULT_WEIGHTS["rae"] / tot) * z_rae + (DEFAULT_WEIGHTS["wpa"] / tot) * z_wpa
            r["overall_default"] = round(float(np.clip(70 + 8 * overall_z, 40, 99)), 1)

    for r in metrics:
        pool = (r["competition"], r["season"], r["gender"])
        rb = repl.get((*pool, "bat"), 0.0)
        ro = repl.get((*pool, "bowl"), 0.0)
        rar_bat = (r["rae_bat"] / max(r["balls_bat"], 1) - rb) * r["balls_bat"]
        rar_bowl = (r["rae_bowl"] / max(r["balls_bowl"], 1) - ro) * r["balls_bowl"]
        denom = rpw.get(r["competition"], 20.0) or 20.0
        r["war"] = round((rar_bat + rar_bowl) / denom, 2)
        r["runs_per_win"] = denom
    return metrics


BOWL_CREDITED = {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}
RETIRED = {"retired hurt", "retired not out", "absent hurt", "absent ill"}


def _score_performances(balls: pd.DataFrame, rpw: dict[str, float]) -> list[dict]:
    if balls.empty:
        return []
    df = balls.copy()
    sched_balls = (df["scheduled_overs"].fillna(20) * df["balls_per_over"].fillna(6)).astype(float)
    df["inn_final"] = df.groupby(["match_id", "innings"], sort=False)["runs_total"].transform("sum")
    df["rem_runs"] = (df["inn_final"] - df["runs_before"]).clip(lower=0)
    df["balls_left"] = (sched_balls - df["legal_before"]).clip(lower=1)
    df["bl_bucket"] = (df["balls_left"] // 6).clip(0, 20).astype(int)
    df["wkts_b"] = df["wkts_before"].clip(0, 9).fillna(0).astype(int)
    re_tbl = (
        df.groupby(["competition", "gender", "bl_bucket", "wkts_b"], dropna=False)["rem_runs"]
        .mean()
        .rename("re_now")
        .reset_index()
    )
    df = df.merge(re_tbl, on=["competition", "gender", "bl_bucket", "wkts_b"], how="left")
    nxt = re_tbl.rename(columns={"wkts_b": "wkts_next", "re_now": "re_next"})
    df["wkts_next"] = (df["wkts_b"] + 1).clip(0, 9)
    df = df.merge(nxt, on=["competition", "gender", "bl_bucket", "wkts_next"], how="left")
    df["re_now"] = df["re_now"].fillna(df["rem_runs"].median() if len(df) else 20)
    df["re_next"] = df["re_next"].fillna(0)
    df["wkt_value"] = (df["re_now"] - df["re_next"]).clip(lower=0, upper=40)

    bat_agg = {
        "rae_bat_ball": "sum",
        "wpa_ball": "sum",
        "pressure_impact": "sum",
        "runs_batter": "sum",
        "is_legal": "count",
        "competition": "first",
        "gender": "first",
        "season": "first",
        "start_date": "first",
        "winner": "first",
        "result_method": "first",
        "venue": "first",
        "batting_team": "first",
        "bowling_team": "first",
    }
    faced = df["striker"].notna() & ~df["is_wide"].fillna(False)
    bat = (
        df.loc[faced]
        .groupby(["match_id", "innings", "striker"], dropna=False)
        .agg(bat_agg)
        .reset_index()
        .rename(columns={
            "striker": "person_id",
            "rae_bat_ball": "nrc",
            "wpa_ball": "wpa",
            "pressure_impact": "press",
            "runs_batter": "runs",
            "is_legal": "balls",
        })
    )
    out_mask = df["player_out"].notna() & ~df["wicket_kind"].isin(RETIRED)
    debit = (
        df.loc[out_mask]
        .groupby(["match_id", "innings", "player_out"], dropna=False)["wkt_value"]
        .sum()
        .rename("debit")
        .reset_index()
        .rename(columns={"player_out": "person_id"})
    )
    if not bat.empty:
        bat = bat.merge(debit, on=["match_id", "innings", "person_id"], how="left")
        bat["nrc"] = bat["nrc"] - bat["debit"].fillna(0)
        bat["not_out"] = bat["debit"].fillna(0) <= 0
        bat["discipline"] = "bat"
        bat["team"] = bat["batting_team"]
        bat["wickets"] = 0

    bowl_agg = {
        "rae_bowl_ball": "sum",
        "wpa_ball": "sum",
        "pressure_bowl": "sum",
        "charged": "sum",
        "is_legal": "sum",
        "competition": "first",
        "gender": "first",
        "season": "first",
        "start_date": "first",
        "winner": "first",
        "result_method": "first",
        "venue": "first",
        "batting_team": "first",
        "bowling_team": "first",
    }
    bowled = df["bowler"].notna()
    bowl = (
        df.loc[bowled]
        .groupby(["match_id", "innings", "bowler"], dropna=False)
        .agg(bowl_agg)
        .reset_index()
        .rename(columns={
            "bowler": "person_id",
            "rae_bowl_ball": "nrc",
            "wpa_ball": "wpa",
            "pressure_bowl": "press",
            "charged": "runs",
            "is_legal": "balls",
        })
    )
    cred_mask = df["wicket_kind"].isin(BOWL_CREDITED) & df["bowler"].notna()
    credit = (
        df.loc[cred_mask]
        .groupby(["match_id", "innings", "bowler"], dropna=False)["wkt_value"]
        .sum()
        .rename("credit")
        .reset_index()
        .rename(columns={"bowler": "person_id"})
    )
    wk_n = (
        df.loc[cred_mask]
        .groupby(["match_id", "innings", "bowler"], dropna=False)
        .size()
        .rename("wickets")
        .reset_index()
        .rename(columns={"bowler": "person_id"})
    )
    if not bowl.empty:
        bowl = bowl.merge(credit, on=["match_id", "innings", "person_id"], how="left")
        bowl = bowl.merge(wk_n, on=["match_id", "innings", "person_id"], how="left")
        bowl["nrc"] = bowl["nrc"] + bowl["credit"].fillna(0)
        bowl["wpa"] = -bowl["wpa"]
        bowl["wickets"] = bowl["wickets"].fillna(0).astype(int)
        bowl["discipline"] = "bowl"
        bowl["team"] = bowl["bowling_team"]
        bowl["not_out"] = False

    frames = [x for x in (bat, bowl) if x is not None and not x.empty]
    if not frames:
        return []
    allp = pd.concat(frames, ignore_index=True)
    allp["person_id"] = allp["person_id"].astype(str)
    allp = allp[allp["person_id"].notna() & (allp["person_id"] != "nan")]
    allp["rpw"] = allp["competition"].map(lambda c: rpw.get(c, FALLBACK_RPW.get(c, 20.0)))
    allp["wpa_runs"] = allp["wpa"] * allp["rpw"]
    allp["dls"] = allp["result_method"] == "dls"

    allp["blend"] = np.nan
    allp["score"] = 50.0
    for _, gix in allp.groupby(["competition", "gender", "discipline"], sort=False).groups.items():
        g = allp.loc[gix]
        def _z(s):
            sd = float(s.std() or 0)
            return (s - s.mean()) / (sd if sd > 1e-6 else 1.0)
        blend = PERF_WEIGHTS["nrc"] * _z(g["nrc"]) + PERF_WEIGHTS["wpa"] * _z(g["wpa_runs"]) + PERF_WEIGHTS["press"] * _z(g["press"])
        allp.loc[gix, "blend"] = blend
        allp.loc[gix, "score"] = blend.rank(method="average", pct=True) * 100

    rows = []
    for r in allp.itertuples(index=False):
        pid = r.person_id
        if not pid or pid == "nan":
            continue
        balls_n = int(_safe_int(r.balls))
        runs_n = int(_safe_int(r.runs))
        wk = int(_safe_int(getattr(r, "wickets", 0)))
        if r.discipline == "bat":
            no = bool(getattr(r, "not_out", False))
            line = f"{runs_n}{'*' if no else ''} off {balls_n}"
        else:
            ov = f"{balls_n // 6}.{balls_n % 6}"
            line = f"{wk}-{runs_n} off {ov}"
        rows.append(
            {
                "match_id": r.match_id,
                "person_id": pid,
                "innings": int(_safe_int(r.innings)),
                "discipline": r.discipline,
                "competition": r.competition,
                "gender": r.gender,
                "season": str(r.season),
                "team": r.team,
                "nrc": round(float(r.nrc or 0), 2),
                "wpa": round(float(r.wpa or 0), 4),
                "wpa_runs": round(float(r.wpa_runs or 0), 2),
                "press": round(float(r.press or 0), 2),
                "blend": float(r.blend),
                "score": round(float(r.score or 50), 1),
                "balls": balls_n,
                "runs": runs_n,
                "wickets": wk,
                "not_out": bool(getattr(r, "not_out", False)),
                "line": line,
                "confidence": "dls_affected" if r.dls else "normal",
                "model_version": MODEL_VERSION,
            }
        )
    return rows


def _safe_int(v) -> int:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return 0
    try:
        if pd.isna(v):
            return 0
    except Exception:
        pass
    return int(v)


def _mu_sd(vals: list[float]) -> tuple[float, float]:
    if not vals:
        return 0.0, 1.0
    arr = np.array(vals, dtype=float)
    sd = float(arr.std())
    return float(arr.mean()), sd if sd > 1e-6 else 1.0


def _merge_super_over(bat, bowl) -> list[dict]:
    rows = {}
    if bat is not None and not bat.empty:
        for r in bat.itertuples(index=False):
            if r.person_id is None or (isinstance(r.person_id, float) and np.isnan(r.person_id)):
                continue
            rows[r.person_id] = {
                "person_id": r.person_id,
                "matches": int(r.matches or 0),
                "balls_faced": int(r.balls_faced or 0),
                "runs": int(r.runs or 0),
                "balls_bowled": 0,
                "runs_conceded": 0,
                "wickets": 0,
            }
    if bowl is not None and not bowl.empty:
        for r in bowl.itertuples(index=False):
            if r.person_id is None or (isinstance(r.person_id, float) and np.isnan(r.person_id)):
                continue
            rec = rows.setdefault(
                r.person_id,
                {
                    "person_id": r.person_id,
                    "matches": 0,
                    "balls_faced": 0,
                    "runs": 0,
                    "balls_bowled": 0,
                    "runs_conceded": 0,
                    "wickets": 0,
                },
            )
            rec["balls_bowled"] = int(r.balls_bowled or 0)
            rec["runs_conceded"] = int(r.runs_conceded or 0)
            rec["wickets"] = int(r.wickets or 0)
            rec["matches"] = max(rec["matches"], int(r.matches or 0))
    return list(rows.values())


def _write_meta(rpw: dict, adv=None) -> None:
    meta = {
        "model_version": MODEL_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "replacement_percentile": REPLACEMENT_PERCENTILE,
        "pressure_k": PRESSURE_K,
        "dls_confidence_threshold": DLS_CONFIDENCE_THRESHOLD,
        "default_weights": DEFAULT_WEIGHTS,
        "runs_per_win": rpw or FALLBACK_RPW,
        "qualifier": {
            "leagues_balls": LEAGUE_QUAL_BALLS,
            "t20i_trailing_balls": INTL_TRAIL_BALLS,
            "t20i_career_balls": INTL_CAREER_BALLS,
        },
        "resource_model": (adv.meta if adv else {}),
    }
    write_parquet("model_meta", [meta])
    (WAREHOUSE / "model_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def is_qualifier(row: dict, *, career_balls: int = 0) -> bool:
    comp = row.get("competition")
    balls = max(int(row.get("balls_bat") or 0), int(row.get("balls_bowl") or 0))
    if comp == "t20i":
        return balls >= INTL_TRAIL_BALLS or career_balls >= INTL_CAREER_BALLS
    return balls >= LEAGUE_QUAL_BALLS
