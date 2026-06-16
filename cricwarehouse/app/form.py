"""Rolling cross-format form ratings, 2K-style.

Published form is a 40–99 integer on an absolute all-time scale: the best of
recent Test, ODI, and T20I counting stats against full-member sides. It is not
a blend, not a percentile, and it does not use the T20 resource model (RAA,
WAR, TSR, TE). Tests and ODIs have no advanced inputs at all. A Test
specialist is scored as a Test player. Franchise T20 (IPL/WPL/BBL/WBBL) is
scored on its own line and never feeds the international overall.

Published form is one decimal on that scale, with a small lift so Bradman's
peak Test window prints 99.0. Retired profiles show peak form.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from cricwarehouse.app.db import connect, warehouse_ready, write_parquet
from cricwarehouse.competitions import GENDER_LABEL
from cricwarehouse.paths import WAREHOUSE
from cricwarehouse.teams import WTC_TEAMS, WOMEN_TEST_TEAMS

FORM_VERSION = "form-v1.3.0"
# Families scored. `t20` is franchise leagues (IPL/WPL/BBL/WBBL), separate from T20I.
FAMILIES = ("test", "odi", "t20i", "t20")
INTL_FAMILIES = ("test", "odi", "t20i")
LEAGUES = ("ipl", "wpl", "bbl", "wbbl")
FAMILY = {
    "test": "test",
    "odi": "odi",
    "t20i": "t20i",
    "ipl": "t20",
    "wpl": "t20",
    "bbl": "t20",
    "wbbl": "t20",
}
FORMATS = FAMILIES
# Add this after scoring so Don Bradman's peak raw (~97.67) publishes as 99.0.
# Anyone above that (Imran's all-rounder bump) can print 99.1–99.9.
FORM_LIFT = 1.332
ACTIVE_DAYS = 270
RETIRED_AFTER = 365
PRIOR_OVR = 74.0
# Full-member internationals only. Associate T20Is mint fake 90s. Leagues pass through.
FORM_TEAMS = {
    "male": WTC_TEAMS + ("Afghanistan", "Ireland", "Zimbabwe"),
    "female": WOMEN_TEST_TEAMS,
}

# Lookback and half-life in days. Tests are sparse, so they keep older knocks.
WINDOW = {"test": 730, "odi": 540, "t20i": 365, "t20": 365}
HALF_LIFE = {"test": 400, "odi": 280, "t20i": 180, "t20": 180}
# A format drops out of the overall if they have not played it recently.
# Stale Test residue should not keep a retired-from-Tests white-ball player
# pinned to an old Test number — and the reverse.
FRESH = {"test": 450, "odi": 300, "t20i": 200, "t20": 200}

MIN_BAT_INNS = {"test": 5.0, "odi": 6.0, "t20i": 6.0, "t20": 6.0}
MIN_BAT_RUNS = {"test": 100.0, "odi": 150.0, "t20i": 120.0, "t20": 120.0}
MIN_BOWL_INNS = {"test": 6.0, "odi": 8.0, "t20i": 8.0, "t20": 8.0}
MIN_BOWL_WKTS = {"test": 10.0, "odi": 10.0, "t20i": 8.0, "t20": 8.0}
MIN_BOWL_BALLS = {"test": 240.0, "odi": 180.0, "t20i": 96.0, "t20": 96.0}
SHRINK_INNS = 4.0
SHRINK_UNTIL = 8.0

LN2 = np.log(2.0)

# Piecewise control points: the value on the left maps to the rating on the right.
# Higher is better except where invert=True (bowling average, strike rate, economy).
BAT_AVG = {
    "test": ((15, 48), (25, 64), (40, 80), (50, 88), (60, 94), (75, 98), (90, 99)),
    "odi": ((15, 48), (25, 62), (35, 74), (45, 84), (55, 91), (70, 96), (95, 99)),
    "t20i": ((12, 48), (20, 62), (28, 74), (36, 84), (45, 91), (55, 96), (72, 99)),
}
BAT_SR = {
    "test": ((30, 50), (40, 62), (50, 72), (60, 80), (75, 88), (90, 94), (115, 98)),
    "odi": ((60, 50), (75, 62), (85, 72), (95, 80), (110, 88), (125, 94), (155, 98)),
    "t20i": ((100, 50), (115, 62), (130, 72), (145, 80), (160, 88), (180, 94), (215, 98)),
}
BAT_RUNS = {
    "test": ((150, 58), (400, 74), (800, 86), (1200, 93), (1800, 97), (2600, 99)),
    "odi": ((200, 55), (500, 70), (900, 82), (1400, 90), (2000, 95), (2800, 98)),
    "t20i": ((140, 55), (350, 70), (600, 82), (900, 90), (1300, 95), (1800, 98)),
}
# Hundreds per 10 innings (Tests/ODI). T20 uses fifty-plus per 10 innings.
BAT_HUNDRED_RATE = {
    "test": ((0.0, 58), (1.0, 78), (2.0, 88), (3.5, 94), (5.5, 98), (8.0, 99)),
    "odi": ((0.0, 58), (0.6, 72), (1.2, 82), (2.0, 90), (3.2, 95), (5.0, 98)),
}
BAT_FIFTY_RATE = {
    "t20i": ((0.0, 55), (1.5, 70), (3.0, 80), (4.5, 88), (6.0, 94), (8.0, 98)),
}

BOWL_AVG = {
    "test": ((40, 50), (32, 68), (28, 80), (25, 90), (22, 94), (18, 97), (14, 99)),
    "odi": ((40, 52), (33, 68), (27, 78), (23, 87), (19, 93), (16, 97), (13, 99)),
    "t20i": ((34, 52), (28, 68), (23, 78), (19, 87), (16, 93), (13, 97), (11, 99)),
}
BOWL_SR = {
    "test": ((80, 52), (68, 74), (58, 88), (50, 93), (42, 96), (34, 98), (27, 99)),
    "odi": ((52, 52), (42, 68), (35, 78), (29, 87), (25, 93), (21, 97), (18, 99)),
    "t20i": ((26, 52), (21, 68), (18, 78), (16, 87), (14, 93), (12, 97), (10, 99)),
}
BOWL_ECON = {
    "test": ((4.4, 52), (3.6, 70), (3.1, 82), (2.7, 90), (2.3, 94), (1.9, 97), (1.5, 99)),
    "odi": ((6.4, 52), (5.6, 68), (5.0, 78), (4.5, 87), (4.1, 93), (3.6, 97), (3.2, 99)),
    "t20i": ((9.0, 52), (8.0, 68), (7.3, 78), (6.7, 87), (6.2, 93), (5.7, 97), (5.2, 99)),
}
BOWL_WKTS = {
    "test": ((12, 58), (30, 75), (50, 86), (75, 93), (100, 97), (140, 99)),
    "odi": ((12, 55), (28, 70), (45, 82), (65, 90), (85, 95), (110, 98)),
    "t20i": ((8, 55), (18, 70), (28, 82), (40, 90), (55, 95), (75, 98)),
}

BAT_WEIGHTS = {
    "test": {"avg": 0.48, "runs": 0.22, "impact": 0.22, "sr": 0.08},
    "odi": {"avg": 0.38, "runs": 0.22, "impact": 0.18, "sr": 0.22},
    "t20i": {"avg": 0.30, "runs": 0.22, "impact": 0.18, "sr": 0.30},
}
BOWL_WEIGHTS = {
    "test": {"avg": 0.32, "sr": 0.22, "econ": 0.08, "wkts": 0.38},
    "odi": {"avg": 0.32, "sr": 0.24, "econ": 0.28, "wkts": 0.16},
    "t20i": {"avg": 0.28, "sr": 0.22, "econ": 0.36, "wkts": 0.14},
}

for _table in (BAT_AVG, BAT_SR, BAT_RUNS, BOWL_AVG, BOWL_SR, BOWL_ECON, BOWL_WKTS, BAT_WEIGHTS, BOWL_WEIGHTS):
    _table["t20"] = _table["t20i"]
BAT_FIFTY_RATE["t20"] = BAT_FIFTY_RATE["t20i"]


def piecewise(x: float | None, points: tuple[tuple[float, float], ...], *, invert: bool = False) -> float | None:
    """Map a raw stat onto 40–99 through linear segments."""
    if x is None or not np.isfinite(x):
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if invert:
        if x >= xs[0]:
            return float(ys[0])
        if x <= xs[-1]:
            return float(ys[-1])
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if x0 >= x >= x1:
                if x0 == x1:
                    return float(y1)
                t = (x0 - x) / (x0 - x1)
                return float(y0 + t * (y1 - y0))
        return float(ys[-1])
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return float(y1)
            t = (x - x0) / (x1 - x0)
            return float(y0 + t * (y1 - y0))
    return float(ys[-1])


def shrink(value: float, n: float, *, prior: float = PRIOR_OVR, prior_n: float = SHRINK_INNS) -> float:
    """Pull a thin sample toward a competent international. Full trust after SHRINK_UNTIL."""
    n = max(float(n), 0.0)
    if n >= SHRINK_UNTIL:
        return float(value)
    return (n * value + prior_n * prior) / (n + prior_n)


def score_batting_window(
    *,
    fmt: str,
    inns: float,
    runs: float,
    outs: float,
    balls: float,
    hundreds: float,
    fifties: float,
) -> dict[str, float] | None:
    """Turn one format's decay-weighted batting pile into a 40–99 rating."""
    if fmt not in FORMATS:
        return None
    if inns < MIN_BAT_INNS[fmt] or runs < MIN_BAT_RUNS[fmt]:
        return None
    avg = runs / max(outs, 0.35)
    sr = (100.0 * runs / balls) if balls >= 20 else None
    per10 = 10.0 / max(inns, 1.0)
    hundred_rate = hundreds * per10
    fifty_plus_rate = (hundreds + fifties) * per10
    attrs = {
        "avg": piecewise(avg, BAT_AVG[fmt]),
        "runs": piecewise(runs, BAT_RUNS[fmt]),
        "sr": piecewise(sr, BAT_SR[fmt]) if sr is not None else None,
    }
    if fmt in ("t20i", "t20"):
        attrs["impact"] = piecewise(fifty_plus_rate, BAT_FIFTY_RATE[fmt])
    else:
        attrs["impact"] = piecewise(hundred_rate, BAT_HUNDRED_RATE[fmt])
    weights = BAT_WEIGHTS[fmt]
    used = {k: v for k, v in attrs.items() if v is not None}
    wsum = sum(weights[k] for k in used)
    if wsum <= 0:
        return None
    raw = sum(used[k] * weights[k] for k in used) / wsum
    rating = shrink(raw, inns)
    return {
        "rating": rating,
        "avg": avg,
        "sr": sr,
        "runs": runs,
        "inns": inns,
        "hundreds": hundreds,
        "fifties": fifties,
        **{f"attr_{k}": v for k, v in attrs.items() if v is not None},
    }


def score_bowling_window(
    *,
    fmt: str,
    inns: float,
    wickets: float,
    runs: float,
    balls: float,
) -> dict[str, float] | None:
    """Turn one format's decay-weighted bowling pile into a 40–99 rating."""
    if fmt not in FORMATS:
        return None
    if inns < MIN_BOWL_INNS[fmt]:
        return None
    if wickets < MIN_BOWL_WKTS[fmt] and balls < MIN_BOWL_BALLS[fmt]:
        return None
    if wickets < 6:
        return None
    avg = runs / wickets
    sr = balls / wickets
    econ = (6.0 * runs / balls) if balls >= 30 else None
    attrs = {
        "avg": piecewise(avg, BOWL_AVG[fmt], invert=True),
        "sr": piecewise(sr, BOWL_SR[fmt], invert=True),
        "econ": piecewise(econ, BOWL_ECON[fmt], invert=True) if econ is not None else None,
        "wkts": piecewise(wickets, BOWL_WKTS[fmt]),
    }
    weights = BOWL_WEIGHTS[fmt]
    used = {k: v for k, v in attrs.items() if v is not None}
    wsum = sum(weights[k] for k in used)
    if wsum <= 0:
        return None
    raw = sum(used[k] * weights[k] for k in used) / wsum
    rating = shrink(raw, inns)
    return {
        "rating": rating,
        "avg": avg,
        "sr": sr,
        "econ": econ,
        "wickets": wickets,
        "inns": inns,
        "balls": balls,
        **{f"attr_{k}": v for k, v in attrs.items() if v is not None},
    }


def best_format(
    parts: dict[str, float],
    families: tuple[str, ...] = INTL_FAMILIES,
) -> tuple[float | None, str | None]:
    """Highest rating among the given families. Ties keep the earlier family.

    Default families are internationals only — franchise T20 stays off the overall.
    A Test goat is not averaged down by weaker ODI or T20I form.
    """
    best_r: float | None = None
    best_f: str | None = None
    for fmt in families:
        rating = parts.get(fmt)
        if rating is None:
            continue
        n = float(rating)
        if best_r is None or n > best_r:
            best_r = n
            best_f = fmt
    return best_r, best_f


def player_overall(bat: float | None, bowl: float | None) -> tuple[float | None, str | None]:
    """Primary overall. A genuine two-way player gets a small bump, never a free 99."""
    if bat is None and bowl is None:
        return None, None
    if bat is None:
        return bowl, "bowl"
    if bowl is None:
        return bat, "bat"
    primary = "bowl" if bowl >= bat else "bat"
    overall = max(bat, bowl)
    lesser = min(bat, bowl)
    if lesser >= 75:
        overall = min(98.4, overall + 1.0)
    if lesser >= 82:
        overall = min(98.4, overall + 1.0)
    return overall, primary


RATING_KEYS = (
    "bat",
    "bowl",
    "test",
    "odi",
    "t20i",
    "t20",
    "bat_test",
    "bat_odi",
    "bat_t20i",
    "bat_t20",
    "bowl_test",
    "bowl_odi",
    "bowl_t20i",
    "bowl_t20",
)


def publish_score(raw: float | None) -> float | None:
    """One decimal, 40.0–99.9, with the Bradman lift applied."""
    if raw is None:
        return None
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return round(min(99.9, max(40.0, n + FORM_LIFT)), 1)


def apply_nines(rows: list[dict], **_unused) -> list[dict]:
    """Publish lifted one-decimal scores. Kept the name; there is no 99 club."""
    for row in rows:
        row["is_99"] = False
        raw = row.get("raw_overall")
        row["form"] = publish_score(raw)
        row["overall"] = row["form"]
        for key in RATING_KEYS:
            if row.get(key) is not None:
                row[key] = publish_score(row[key])
    return rows


def _decay_weight(days: np.ndarray, half_life: np.ndarray) -> np.ndarray:
    return np.exp(-LN2 * days / np.maximum(half_life, 1.0))


def _prepare_lines(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["start_date"], errors="coerce")
    out["family"] = out["competition"].map(FAMILY)
    out = out[out["date"].notna() & out["family"].isin(FAMILIES)]
    out = out[out["gender"].isin(["male", "female"])]
    out["half_life"] = out["family"].map(HALF_LIFE).astype(float)
    out["window"] = out["family"].map(WINDOW).astype(float)
    if kind == "bat":
        out["runs"] = pd.to_numeric(out["runs"], errors="coerce").fillna(0.0)
        out["balls"] = pd.to_numeric(out["balls"], errors="coerce").fillna(0.0)
        out["not_out"] = out["not_out"].fillna(False).astype(bool)
        out["outs"] = np.where(out["not_out"], 0.0, 1.0)
        out["hundreds"] = np.where(out["runs"] >= 100, 1.0, 0.0)
        out["fifties"] = np.where((out["runs"] >= 50) & (out["runs"] < 100), 1.0, 0.0)
        out["inns"] = 1.0
    else:
        out["runs"] = pd.to_numeric(out["runs"], errors="coerce").fillna(0.0)
        out["legal_balls"] = pd.to_numeric(out["legal_balls"], errors="coerce").fillna(0.0)
        out["wickets"] = pd.to_numeric(out["wickets"], errors="coerce").fillna(0.0)
        out["inns"] = 1.0
    return out.reset_index(drop=True)


def _slice_as_of(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Rows dated on or before as_of and inside the longest format window."""
    if df.empty:
        return df
    dates = df["date"]
    hi = int(dates.searchsorted(as_of, side="right"))
    lo = int(dates.searchsorted(as_of - pd.Timedelta(days=int(max(WINDOW.values()))), side="left"))
    sub = df.iloc[lo:hi]
    if sub.empty:
        return sub
    days = (as_of - sub["date"]).dt.days
    return sub.loc[(days >= 0) & (days <= sub["window"])]


def _weighted_bat(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    sub = _slice_as_of(df, as_of)
    if sub.empty:
        return pd.DataFrame()
    days = (as_of - sub["date"]).dt.days.to_numpy(dtype=float)
    w = _decay_weight(days, sub["half_life"].to_numpy(dtype=float))
    keyed = sub.assign(
        w=w,
        w_inns=sub["inns"].to_numpy(dtype=float) * w,
        w_runs=sub["runs"].to_numpy(dtype=float) * w,
        w_outs=sub["outs"].to_numpy(dtype=float) * w,
        w_balls=sub["balls"].to_numpy(dtype=float) * w,
        w_hundreds=sub["hundreds"].to_numpy(dtype=float) * w,
        w_fifties=sub["fifties"].to_numpy(dtype=float) * w,
    )
    return keyed.groupby(["person_id", "gender", "family"], sort=False, as_index=False).agg(
        inns=("w_inns", "sum"),
        runs=("w_runs", "sum"),
        outs=("w_outs", "sum"),
        balls=("w_balls", "sum"),
        hundreds=("w_hundreds", "sum"),
        fifties=("w_fifties", "sum"),
        last_date=("date", "max"),
    )


def _weighted_bowl(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    sub = _slice_as_of(df, as_of)
    if sub.empty:
        return pd.DataFrame()
    days = (as_of - sub["date"]).dt.days.to_numpy(dtype=float)
    w = _decay_weight(days, sub["half_life"].to_numpy(dtype=float))
    keyed = sub.assign(
        w=w,
        w_inns=sub["inns"].to_numpy(dtype=float) * w,
        w_wkts=sub["wickets"].to_numpy(dtype=float) * w,
        w_runs=sub["runs"].to_numpy(dtype=float) * w,
        w_balls=sub["legal_balls"].to_numpy(dtype=float) * w,
    )
    return keyed.groupby(["person_id", "gender", "family"], sort=False, as_index=False).agg(
        inns=("w_inns", "sum"),
        wickets=("w_wkts", "sum"),
        runs=("w_runs", "sum"),
        balls=("w_balls", "sum"),
        last_date=("date", "max"),
    )


def score_snapshot(bat: pd.DataFrame, bowl: pd.DataFrame, as_of) -> list[dict]:
    """Score every qualified player as of one date. `bat`/`bowl` are raw innings frames."""
    as_of_ts = pd.Timestamp(as_of)
    if not bat.empty and not bat["date"].is_monotonic_increasing:
        bat = bat.sort_values("date")
    if not bowl.empty and not bowl["date"].is_monotonic_increasing:
        bowl = bowl.sort_values("date")
    bat_w = _weighted_bat(bat, as_of_ts)
    bowl_w = _weighted_bowl(bowl, as_of_ts)
    players: dict[tuple[str, str], dict] = {}

    def slot(pid: str, gender: str) -> dict:
        key = (pid, gender)
        rec = players.get(key)
        if rec is None:
            rec = {
                "person_id": pid,
                "gender": gender,
                "as_of": as_of_ts.date().isoformat(),
                "bat_parts": {},
                "bowl_parts": {},
                "bat_inns": {},
                "bowl_inns": {},
                "bat_avg": {},
                "bat_sr": {},
                "bat_runs": {},
                "bowl_avg": {},
                "bowl_sr": {},
                "bowl_wkts": {},
                "last_date": None,
                "runs": 0.0,
                "wickets": 0.0,
                "bat_n": 0.0,
                "bowl_n": 0.0,
            }
            players[key] = rec
        return rec

    for row in bat_w.itertuples(index=False):
        scored = score_batting_window(
            fmt=row.family,
            inns=float(row.inns),
            runs=float(row.runs),
            outs=float(row.outs),
            balls=float(row.balls),
            hundreds=float(row.hundreds),
            fifties=float(row.fifties),
        )
        if not scored:
            continue
        last = pd.Timestamp(row.last_date)
        if (as_of_ts - last).days > FRESH[row.family]:
            continue
        rec = slot(row.person_id, row.gender)
        rec["bat_parts"][row.family] = scored["rating"]
        rec["bat_inns"][row.family] = scored["inns"]
        rec["bat_avg"][row.family] = scored["avg"]
        rec["bat_sr"][row.family] = scored["sr"]
        rec["bat_runs"][row.family] = scored["runs"]
        rec["runs"] += float(row.runs)
        rec["bat_n"] += scored["inns"]
        if rec["last_date"] is None or last > rec["last_date"]:
            rec["last_date"] = last

    for row in bowl_w.itertuples(index=False):
        scored = score_bowling_window(
            fmt=row.family,
            inns=float(row.inns),
            wickets=float(row.wickets),
            runs=float(row.runs),
            balls=float(row.balls),
        )
        if not scored:
            continue
        last = pd.Timestamp(row.last_date)
        if (as_of_ts - last).days > FRESH[row.family]:
            continue
        rec = slot(row.person_id, row.gender)
        rec["bowl_parts"][row.family] = scored["rating"]
        rec["bowl_inns"][row.family] = scored["inns"]
        rec["bowl_avg"][row.family] = scored["avg"]
        rec["bowl_sr"][row.family] = scored["sr"]
        rec["bowl_wkts"][row.family] = scored["wickets"]
        rec["wickets"] += float(row.wickets)
        rec["bowl_n"] += scored["inns"]
        if rec["last_date"] is None or last > rec["last_date"]:
            rec["last_date"] = last

    out = []
    for rec in players.values():
        fmt_ovr = {
            fam: player_overall(rec["bat_parts"].get(fam), rec["bowl_parts"].get(fam))[0]
            for fam in FAMILIES
        }
        _, best_fam = best_format(fmt_ovr, INTL_FAMILIES)
        if best_fam is None:
            bat_r = None
            bowl_r = None
            raw, primary = None, None
        else:
            bat_r = rec["bat_parts"].get(best_fam)
            bowl_r = rec["bowl_parts"].get(best_fam)
            raw, primary = player_overall(bat_r, bowl_r)
        if raw is None and all(v is None for v in fmt_ovr.values()):
            continue
        if primary is None:
            best = max(
                (fam for fam in FAMILIES if fmt_ovr[fam] is not None),
                key=lambda fam: float(fmt_ovr[fam]),
            )
            primary = "bowl" if (rec["bowl_parts"].get(best) or 0) >= (rec["bat_parts"].get(best) or 0) else "bat"
        last = rec["last_date"]
        active = last is not None and (as_of_ts - last).days <= ACTIVE_DAYS
        out.append(
            {
                "as_of": rec["as_of"],
                "person_id": rec["person_id"],
                "gender": rec["gender"],
                "raw_overall": None if raw is None else float(raw),
                "bat": None if bat_r is None else float(bat_r),
                "bowl": None if bowl_r is None else float(bowl_r),
                "test": fmt_ovr["test"],
                "odi": fmt_ovr["odi"],
                "t20i": fmt_ovr["t20i"],
                "t20": fmt_ovr["t20"],
                "bat_test": rec["bat_parts"].get("test"),
                "bat_odi": rec["bat_parts"].get("odi"),
                "bat_t20i": rec["bat_parts"].get("t20i"),
                "bat_t20": rec["bat_parts"].get("t20"),
                "bowl_test": rec["bowl_parts"].get("test"),
                "bowl_odi": rec["bowl_parts"].get("odi"),
                "bowl_t20i": rec["bowl_parts"].get("t20i"),
                "bowl_t20": rec["bowl_parts"].get("t20"),
                "primary": primary,
                "active": bool(active),
                "bat_inns": float(rec["bat_n"]),
                "bowl_inns": float(rec["bowl_n"]),
                "runs": float(rec["runs"]),
                "wickets": float(rec["wickets"]),
                **{
                    f"bat_avg_{fam}": rec["bat_avg"].get(fam)
                    for fam in FAMILIES
                },
                **{
                    f"bat_sr_{fam}": rec["bat_sr"].get(fam)
                    for fam in FAMILIES
                },
                **{
                    f"bat_runs_{fam}": rec["bat_runs"].get(fam)
                    for fam in FAMILIES
                },
                **{
                    f"bat_inns_{fam}": rec["bat_inns"].get(fam)
                    for fam in FAMILIES
                },
                **{
                    f"bowl_avg_{fam}": rec["bowl_avg"].get(fam)
                    for fam in FAMILIES
                },
                **{
                    f"bowl_sr_{fam}": rec["bowl_sr"].get(fam)
                    for fam in FAMILIES
                },
                **{
                    f"bowl_wkts_{fam}": rec["bowl_wkts"].get(fam)
                    for fam in FAMILIES
                },
                **{
                    f"bowl_inns_{fam}": rec["bowl_inns"].get(fam)
                    for fam in FAMILIES
                },
                "form_version": FORM_VERSION,
            }
        )
    return apply_nines(out)


def _month_ends(dates: pd.Series) -> list[pd.Timestamp]:
    periods = dates.dropna().dt.to_period("M").unique()
    return sorted(pd.Period(p, freq="M").to_timestamp(how="end").normalize() for p in periods)


def _full_member_mask(df: pd.DataFrame) -> pd.Series:
    out = pd.Series(False, index=df.index)
    for gender, teams in FORM_TEAMS.items():
        allowed = set(teams)
        part = df["gender"] == gender
        out.loc[part] = df.loc[part, "team_home"].isin(allowed) & df.loc[part, "team_away"].isin(allowed)
    return out


def _load_lines(con) -> tuple[pd.DataFrame, pd.DataFrame]:
    bat = con.execute(
        """
        SELECT b.person_id, b.runs, b.balls, b.not_out,
               m.start_date, m.competition, m.gender, m.team_home, m.team_away
        FROM batting_lines b
        JOIN matches m ON m.match_id = b.match_id
        WHERE b.innings_kind = 'regular'
          AND m.competition IN ('test', 'odi', 't20i', 'ipl', 'wpl', 'bbl', 'wbbl')
        """
    ).fetchdf()
    bowl = con.execute(
        """
        SELECT bl.person_id, bl.runs, bl.legal_balls, bl.wickets,
               m.start_date, m.competition, m.gender, m.team_home, m.team_away
        FROM bowling_lines bl
        JOIN matches m ON m.match_id = bl.match_id
        WHERE bl.innings_kind = 'regular'
          AND m.competition IN ('test', 'odi', 't20i', 'ipl', 'wpl', 'bbl', 'wbbl')
        """
    ).fetchdf()
    bat = _prepare_lines(bat, "bat")
    bowl = _prepare_lines(bowl, "bowl")
    intl = set(INTL_FAMILIES)
    if not bat.empty:
        keep = ~bat["competition"].isin(intl) | _full_member_mask(bat)
        bat = bat.loc[keep].reset_index(drop=True)
    if not bowl.empty:
        keep = ~bowl["competition"].isin(intl) | _full_member_mask(bowl)
        bowl = bowl.loc[keep].reset_index(drop=True)
    return bat, bowl


def rebuild_form(*, step_months: int = 1) -> dict[str, Any]:
    """Walk month-ends that had scored cricket and write form_ratings."""
    if not warehouse_ready():
        raise RuntimeError("Warehouse not built yet.")
    con = connect()
    try:
        bat, bowl = _load_lines(con)
    finally:
        con.close()
    if bat.empty and bowl.empty:
        write_parquet("form_ratings", [])
        return {"rows": 0, "snapshots": 0, "version": FORM_VERSION}

    bat = bat.sort_values("date").reset_index(drop=True)
    bowl = bowl.sort_values("date").reset_index(drop=True)
    dates = pd.concat([bat["date"], bowl["date"]], ignore_index=True)
    stamps = _month_ends(dates)
    if step_months > 1:
        stamps = stamps[::step_months]
        if stamps and stamps[-1] != _month_ends(dates)[-1]:
            stamps.append(_month_ends(dates)[-1])

    rows: list[dict] = []
    print(f"Form ratings — {len(stamps)} month-end snapshots", flush=True)
    for i, as_of in enumerate(stamps, start=1):
        rows.extend(score_snapshot(bat, bowl, as_of))
        if i % 50 == 0 or i == len(stamps):
            print(f"  scored {i}/{len(stamps)}  rows={len(rows):,}", flush=True)

    packed = _pack_rows(rows)
    write_parquet("form_ratings", packed)
    meta = {
        "form_version": FORM_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "snapshots": len(stamps),
        "rows": len(packed),
        "formats": list(FORMATS),
    }
    (WAREHOUSE / "form_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Form ratings written: {len(packed):,} rows", flush=True)
    return meta


def _pack_rows(rows: list[dict]) -> list[dict]:
    packed = []
    for r in rows:
        item = {
            "as_of": r["as_of"],
            "person_id": r["person_id"],
            "gender": r["gender"],
            "form": r.get("form"),
            "overall": r.get("overall"),
            "primary": r.get("primary"),
            "is_99": False,
            "raw_overall": None if r.get("raw_overall") is None else round(float(r["raw_overall"]), 3),
            "active": bool(r.get("active")),
            "form_version": FORM_VERSION,
        }
        for key in RATING_KEYS:
            item[key] = _maybe_score(r.get(key))
        item["form"] = _maybe_score(r.get("form"))
        item["overall"] = item["form"]
        item["bat_inns"] = _maybe_num(r.get("bat_inns"), 2)
        item["bowl_inns"] = _maybe_num(r.get("bowl_inns"), 2)
        item["runs"] = _maybe_num(r.get("runs"), 1)
        item["wickets"] = _maybe_num(r.get("wickets"), 1)
        for fam in FAMILIES:
            item[f"bat_avg_{fam}"] = _maybe_num(r.get(f"bat_avg_{fam}"), 2)
            item[f"bat_sr_{fam}"] = _maybe_num(r.get(f"bat_sr_{fam}"), 1)
            item[f"bat_runs_{fam}"] = _maybe_num(r.get(f"bat_runs_{fam}"), 1)
            item[f"bat_inns_{fam}"] = _maybe_num(r.get(f"bat_inns_{fam}"), 2)
            item[f"bowl_avg_{fam}"] = _maybe_num(r.get(f"bowl_avg_{fam}"), 2)
            item[f"bowl_sr_{fam}"] = _maybe_num(r.get(f"bowl_sr_{fam}"), 1)
            item[f"bowl_wkts_{fam}"] = _maybe_num(r.get(f"bowl_wkts_{fam}"), 1)
            item[f"bowl_inns_{fam}"] = _maybe_num(r.get(f"bowl_inns_{fam}"), 2)
        packed.append(item)
    return packed


def _maybe_score(value) -> float | None:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    return round(float(value), 1)


def _maybe_num(value, digits: int) -> float | None:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    return round(float(value), digits)


def form_ready() -> bool:
    return (WAREHOUSE / "form_ratings.parquet").exists()


def _rating_cols(con) -> tuple[str, str]:
    """Score expression and extra select list, depending on parquet columns."""
    names = {r[0] for r in con.execute("DESCRIBE form_ratings").fetchall()}
    if "form" in names:
        return "COALESCE(form, overall)", "form, overall, is_99, raw_overall"
    return "overall", "overall, is_99, raw_overall"


def _score_of(row: dict | None) -> float:
    if not row:
        return 0.0
    n = row.get("form")
    if n is None:
        n = row.get("overall")
    try:
        return float(n or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_date(iso) -> date | None:
    if iso is None:
        return None
    try:
        return date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def is_retired(as_of, warehouse_max, *, after: int = RETIRED_AFTER) -> bool:
    """True when the last snapshot is more than `after` days behind the warehouse."""
    last = _as_date(as_of)
    latest = _as_date(warehouse_max)
    if last is None or latest is None:
        return False
    return (latest - last).days > after


def pick_hero(rows: list[dict], warehouse_max) -> tuple[dict, dict, bool]:
    """Return (hero, peak, retired). Retired players show peak form, not the last window."""
    rated = [r for r in rows if _score_of(r)]
    current = rated[-1] if rated else rows[-1]
    peak = max(rows, key=lambda r: (_score_of(r), r.get("as_of") or ""))
    retired = is_retired(current.get("as_of"), warehouse_max)
    return (peak if retired else current), peak, retired


def player_form(person_id: str) -> dict[str, Any] | None:
    if not form_ready():
        return None
    con = connect()
    try:
        recs = con.execute(
            """
            SELECT f.*, p.display_name, p.slug, p.unique_name
            FROM form_ratings f
            JOIN people p ON p.person_id = f.person_id
            WHERE f.person_id = ?
            ORDER BY f.as_of
            """,
            [person_id],
        ).fetchdf()
        if recs is None or recs.empty:
            return None
        rows = _records(recs)
        warehouse_max = con.execute("SELECT MAX(as_of) FROM form_ratings").fetchone()[0]
        hero, peak, retired = pick_hero(rows, warehouse_max)
        last = next((r for r in reversed(rows) if _score_of(r)), rows[-1])
        as_of = hero.get("as_of")
        gender = hero.get("gender") or last.get("gender") or current_gender(rows)
        rank = None
        n99 = 0
        field = 0
        if gender and as_of:
            score_expr, _ = _rating_cols(con)
            board = con.execute(
                f"""
                SELECT person_id, {score_expr} AS form, overall, is_99, raw_overall
                FROM form_ratings
                WHERE as_of = ? AND gender = ?
                  AND {score_expr} IS NOT NULL
                ORDER BY {score_expr} DESC, raw_overall DESC
                """,
                [as_of, gender],
            ).fetchdf()
            if board is not None and not board.empty:
                field = int(len(board))
                n99 = int(board["is_99"].sum()) if "is_99" in board else 0
                ids = list(board["person_id"])
                if person_id in ids:
                    rank = ids.index(person_id) + 1
        return {
            "current": last,
            "hero": hero,
            "peak": {
                "form": peak.get("form") if peak.get("form") is not None else peak.get("overall"),
                "overall": peak.get("overall") if peak.get("overall") is not None else peak.get("form"),
                "as_of": peak.get("as_of"),
            },
            "retired": retired,
            "series": [
                {
                    "as_of": r["as_of"],
                    "form": r.get("form") if r.get("form") is not None else r.get("overall"),
                    "overall": r.get("overall") if r.get("overall") is not None else r.get("form"),
                    "bat": r.get("bat"),
                    "bowl": r.get("bowl"),
                    "test": r.get("test"),
                    "odi": r.get("odi"),
                    "t20i": r.get("t20i"),
                    "t20": r.get("t20"),
                    "is_99": bool(r.get("is_99")),
                }
                for r in rows
            ],
            "rank": rank,
            "field": field,
            "n99": n99,
            "caption": _caption(last, rank, field, n99, retired=retired, peak=peak),
            "version": FORM_VERSION,
        }
    finally:
        con.close()


def current_gender(rows: list[dict]) -> str | None:
    for row in reversed(rows):
        if row.get("gender"):
            return row["gender"]
    return None


FMT_LABEL = {"test": "Tests", "odi": "ODI", "t20i": "T20I", "t20": "T20"}
BOARD_SORTS = ("overall", "test", "odi", "t20i", "t20")


def _finite(value) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _fmt_rating(value) -> str | None:
    n = _finite(value)
    if n is None:
        return None
    return f"{n:.1f}"


def _fmt_stat(value, digits: int, suffix: str) -> str | None:
    n = _finite(value)
    if n is None:
        return None
    return f"{n:.{digits}f} {suffix}"


def cause_of(row: dict[str, Any], family: str | None = None) -> dict[str, Any]:
    """Name the format and window pile that produced the sorted number."""
    fam = family if family in FAMILIES else None
    if fam is None or row.get(fam) is None:
        rated = [(name, row.get(name)) for name in INTL_FAMILIES if row.get(name) is not None]
        if not rated:
            return {"format": None, "format_ovr": None, "line": ""}
        fam, val = max(rated, key=lambda item: (float(item[1]), -INTL_FAMILIES.index(item[0])))
    else:
        val = row.get(fam)
    primary = row.get("primary") or "bat"
    if fam and row.get(f"bowl_{fam}") is not None and (
        row.get(f"bat_{fam}") is None or float(row.get(f"bowl_{fam}") or 0) >= float(row.get(f"bat_{fam}") or 0)
    ):
        primary = "bowl"
    if fam and row.get(f"bat_{fam}") is not None and (
        row.get(f"bowl_{fam}") is None or float(row.get(f"bat_{fam}") or 0) > float(row.get(f"bowl_{fam}") or 0)
    ):
        primary = "bat"
    bat = row.get(f"bat_{fam}")
    bowl = row.get(f"bowl_{fam}")
    parts = [FMT_LABEL[fam]]
    if bat is not None:
        parts.append(f"bat {_fmt_rating(bat)}")
    if bowl is not None:
        parts.append(f"bowl {_fmt_rating(bowl)}")
    if primary == "bowl":
        parts.append(_fmt_stat(row.get(f"bowl_avg_{fam}"), 1, "avg"))
        parts.append(_fmt_stat(row.get(f"bowl_sr_{fam}"), 1, "SR"))
        wkts = _finite(row.get(f"bowl_wkts_{fam}")) or _finite(row.get("wickets"))
        inns = _finite(row.get(f"bowl_inns_{fam}")) or _finite(row.get("bowl_inns"))
        if wkts:
            parts.append(f"{int(round(wkts))} wkts")
        if inns:
            parts.append(f"{int(round(inns))} inns")
    else:
        parts.append(_fmt_stat(row.get(f"bat_avg_{fam}"), 1, "avg"))
        sr = _finite(row.get(f"bat_sr_{fam}"))
        cap = {"test": 100.0, "odi": 175.0, "t20i": 280.0, "t20": 280.0}.get(fam, 200.0)
        if sr is not None and sr <= cap:
            parts.append(_fmt_stat(sr, 1, "SR"))
        runs = _finite(row.get(f"bat_runs_{fam}")) or _finite(row.get("runs"))
        inns = _finite(row.get(f"bat_inns_{fam}")) or _finite(row.get("bat_inns"))
        if runs:
            parts.append(f"{int(round(runs)):,} runs")
        if inns:
            parts.append(f"{int(round(inns))} inns")
    line = " · ".join(p for p in parts if p)
    return {"format": fam, "format_ovr": _finite(val), "line": line}


def _decorate_board(rows: list[dict[str, Any]], family: str | None = None) -> list[dict[str, Any]]:
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
        row["player"] = row.get("display_name")
        if row.get("form") is None:
            row["form"] = row.get("overall")
        if row.get("overall") is None:
            row["overall"] = row.get("form")
        cause = cause_of(row, family=family)
        row["cause"] = cause["line"]
        row["cause_format"] = cause["format"]
        row["peak_date"] = _fmt_as_of(row.get("as_of"))
        row.pop("peak_rk", None)
    return rows


def _sort_col(con, sort: str | None) -> tuple[str, str]:
    score_expr, _ = _rating_cols(con)
    key = sort if sort in BOARD_SORTS else "overall"
    return key, (score_expr if key == "overall" else key)


def latest_board(*, gender: str | None = "male", limit: int = 80, sort: str | None = "overall") -> dict[str, Any]:
    if not form_ready():
        return {
            "rows": [],
            "scope": "Form ratings not built yet. Run: python -m cricwarehouse rebuild-form",
            "metric": "overall",
            "as_of": None,
        }
    gender = gender if gender in {"male", "female"} else "male"
    con = connect()
    try:
        as_of = con.execute(
            "SELECT MAX(as_of) FROM form_ratings WHERE gender = ?", [gender]
        ).fetchone()[0]
        if not as_of:
            return {"rows": [], "scope": "No form snapshots", "metric": "overall", "as_of": None}
        key, col = _sort_col(con, sort)
        recs = con.execute(
            f"""
            SELECT f.*, p.display_name, p.slug, p.unique_name
            FROM form_ratings f
            JOIN people p ON p.person_id = f.person_id
            WHERE f.as_of = ? AND f.gender = ?
              AND {col} IS NOT NULL
            ORDER BY {col} DESC, f.raw_overall DESC, p.display_name
            LIMIT ?
            """,
            [as_of, gender, max(int(limit), 5)],
        ).fetchdf()
        family = None if key == "overall" else key
        rows = _decorate_board(_records(recs), family=family)
        label = FMT_LABEL.get(key, "overall")
        return {
            "rows": rows,
            "as_of": as_of,
            "metric": "overall",
            "sort": key,
            "n99": 0,
            "scope": (
                f"{GENDER_LABEL.get(gender, gender)} · {label} form "
                f"as of {_fmt_as_of(as_of)}"
            ),
        }
    finally:
        con.close()


def peak_board(*, gender: str | None = "male", limit: int = 80, sort: str | None = "overall") -> dict[str, Any]:
    """One row per player at their career-high in the sorted column."""
    if not form_ready():
        return {
            "rows": [],
            "scope": "Form ratings not built yet. Run: python -m cricwarehouse rebuild-form",
            "metric": "peak",
            "as_of": None,
        }
    gender = gender if gender in {"male", "female"} else "male"
    con = connect()
    try:
        key, col = _sort_col(con, sort)
        recs = con.execute(
            f"""
            SELECT f.*, p.display_name, p.slug, p.unique_name
            FROM (
              SELECT *, ROW_NUMBER() OVER (
                PARTITION BY person_id
                ORDER BY {col} DESC NULLS LAST, as_of DESC
              ) AS peak_rk
              FROM form_ratings
              WHERE gender = ? AND {col} IS NOT NULL
            ) f
            JOIN people p ON p.person_id = f.person_id
            WHERE f.peak_rk = 1
            ORDER BY {col} DESC, f.raw_overall DESC, p.display_name
            LIMIT ?
            """,
            [gender, max(int(limit), 5)],
        ).fetchdf()
        family = None if key == "overall" else key
        rows = _decorate_board(_records(recs), family=family)
        label = FMT_LABEL.get(key, "overall")
        return {
            "rows": rows,
            "as_of": None,
            "metric": "peak",
            "sort": key,
            "n99": 0,
            "scope": (
                f"{GENDER_LABEL.get(gender, gender)} · career-high {label}, one snapshot each. "
                "Other format columns are from that month."
            ),
        }
    finally:
        con.close()


def _caption(
    current: dict,
    rank: int | None,
    field: int,
    n99: int = 0,
    *,
    retired: bool = False,
    peak: dict | None = None,
) -> str:
    bits = [
        "Best of recent Test, ODI and T20I counting stats against full-member sides — not a blend, not a percentile, not T20 WAR.",
        "A Test specialist is scored as a Test player. Franchise T20 (IPL, WPL, BBL, WBBL) is its own line and does not feed the overall.",
        "One decimal, 40.0–99.9. Bradman's peak Test window is 99.0; anyone above that can print 99.1–99.9.",
    ]
    if retired and peak:
        bits.append(
            f"Peak {_fmt_rating(_score_of(peak))} on {_fmt_as_of(peak.get('as_of'))}."
            f" Last window {_fmt_rating(_score_of(current))} on {_fmt_as_of(current.get('as_of'))}."
        )
        if rank and field:
            bits.append(f"#{rank} of {field} qualified {current.get('gender') or 'players'} at that peak.")
    elif rank and field:
        bits.append(
            f"#{rank} of {field} qualified {current.get('gender') or 'players'} on {_fmt_as_of(current.get('as_of'))}."
        )
    return " ".join(bits)


def _fmt_as_of(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        d = date.fromisoformat(str(iso)[:10])
        return f"{d.day} {d.strftime('%b %Y')}"
    except ValueError:
        return str(iso)[:10]


def _records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    rows = []
    for raw in df.to_dict("records"):
        item = {}
        for k, v in raw.items():
            if hasattr(v, "item"):
                try:
                    v = v.item()
                except Exception:
                    v = None
            if isinstance(v, float) and v != v:
                v = None
            if isinstance(v, (pd.Timestamp, datetime)):
                v = v.date().isoformat()
            item[k] = v
        rows.append(item)
    return rows
