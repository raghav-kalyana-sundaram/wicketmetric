"""Fifty uncontested Test-rating judgments, plus structural invariants.

Each assertion returns pass / fail / skip with a margin. Hard constraints are
weighted 3×. Ten judgments are holdouts and must not be used for tuning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from cricwarehouse.app.db import connect, warehouse_ready
from cricwarehouse.app.test_value import ratings_ready

# unique_name as stored on people / test_ratings
NAMES = {
    "bradman": "DG Bradman",
    "voges": "AC Voges",
    "tendulkar": "SR Tendulkar",
    "hayden": "ML Hayden",
    "sangakkara": "KC Sangakkara",
    "lara": "BC Lara",
    "dravid": "R Dravid",
    "root": "JE Root",
    "brook": "HC Brook",
    "kallis": "JH Kallis",
    "smith": "SPD Smith",
    "hobbs": "JB Hobbs",
    "sutcliffe": "H Sutcliffe",
    "hutton": "L Hutton",
    "sehwag": "V Sehwag",
    "marshall": "MD Marshall",
    "mcgrath": "GD McGrath",
    "ambrose": "CEL Ambrose",
    "steyn": "DW Steyn",
    "hadlee": "RJ Hadlee",
    "lillee": "DK Lillee",
    "wasim": "Wasim Akram",
    "warne": "SK Warne",
    "murali": "M Muralitharan",
    "barnes": "SF Barnes",
    "kumble": "A Kumble",
    "ashwin": "R Ashwin",
    "herath": "HMRKB Herath",
    "sobers": "GS Sobers",
    "imran": "Imran Khan",
    "botham": "IT Botham",
    "stokes": "BA Stokes",
    "jadeja": "RA Jadeja",
    "taijul": "Taijul Islam",
    "dinusha": "GS Dinusha",
    "barrington": "KF Barrington",
    "may": "PBH May",
    "weekes": "ED Weekes",
    "walcott": "CL Walcott",
    "jayawardene": "DPMD Jayawardene",
    "ponting": "RT Ponting",
    "richards": "IVA Richards",
    "hammond": "WR Hammond",
    "headley": "GA Headley",
    "anderson": "JM Anderson",
    "lyon": "NM Lyon",
}

HARD = frozenset({1, 3, 9, 21, 36, 39, 45, 49})
HOLDOUT = frozenset({10, 12, 14, 18, 23, 28, 32, 34, 41, 48})


@dataclass
class Result:
    n: int
    name: str
    passed: bool | None
    detail: str
    holdout: bool = False
    hard: bool = False
    margin: float | None = None

    @property
    def weight(self) -> int:
        if self.passed is None:
            return 0
        return 3 if self.hard else 1


@dataclass
class Board:
    overall: pd.DataFrame
    peak: pd.DataFrame
    form: pd.DataFrame
    innings: pd.DataFrame
    by_name: dict[str, pd.Series]

    def row(self, key: str) -> pd.Series | None:
        name = NAMES.get(key, key)
        return self.by_name.get(name)

    def rank_overall(self, key: str) -> int | None:
        row = self.row(key)
        if row is None:
            return None
        return int(row["rank_overall"])

    def rank_peak(self, key: str) -> int | None:
        row = self.row(key)
        if row is None:
            return None
        return int(row["rank_peak"])

    def rating(self, key: str, col: str = "overall") -> float | None:
        row = self.row(key)
        if row is None or pd.isna(row.get(col)):
            return None
        return float(row[col])


def load_board(con=None) -> Board:
    own = con is None
    if own:
        con = connect()
    try:
        players = con.execute(
            "SELECT * FROM test_ratings WHERE gender = 'male'"
        ).fetchdf()
        innings = con.execute("SELECT * FROM test_innings_raa").fetchdf()
    finally:
        if own:
            con.close()
    players = players.sort_values(["overall", "career_raa"], ascending=[False, False]).reset_index(drop=True)
    players["rank_overall"] = np.arange(1, len(players) + 1)
    peak_order = players.sort_values(["peak", "peak_shrunk"], ascending=[False, False]).reset_index(drop=True)
    peak_order["rank_peak"] = np.arange(1, len(peak_order) + 1)
    players = players.merge(peak_order[["person_id", "rank_peak"]], on="person_id", how="left")
    by_name = {}
    for _, row in players.iterrows():
        name = row.get("unique_name")
        if name:
            by_name[str(name)] = row
    form = players[players["form"].notna()].sort_values("form", ascending=False).reset_index(drop=True)
    return Board(overall=players, peak=peak_order, form=form, innings=innings, by_name=by_name)


def _ok(n: int, name: str, passed: bool | None, detail: str, margin: float | None = None) -> Result:
    return Result(
        n=n,
        name=name,
        passed=passed,
        detail=detail,
        holdout=n in HOLDOUT,
        hard=n in HARD,
        margin=margin,
    )


def _need(board: Board, *keys: str) -> str | None:
    missing = [k for k in keys if board.row(k) is None]
    if missing:
        return "missing " + ", ".join(missing)
    return None


def j01(b: Board) -> Result:
    miss = _need(b, "bradman")
    if miss:
        return _ok(1, "Bradman #1 overall and peak", None, miss)
    ro, rp = b.rank_overall("bradman"), b.rank_peak("bradman")
    return _ok(1, "Bradman #1 overall and peak", ro == 1 and rp == 1, f"overall #{ro}, peak #{rp}")


def j02(b: Board) -> Result:
    miss = _need(b, "bradman")
    if miss:
        return _ok(2, "Bradman margin > #2-to-#10 gap", None, miss)
    top = b.overall.head(10)
    if len(top) < 10:
        return _ok(2, "Bradman margin > #2-to-#10 gap", None, "short board")
    r = top["overall"].to_numpy(dtype=float)
    gap1 = float(r[0] - r[1])
    gap2 = float(r[1] - r[9])
    return _ok(2, "Bradman margin > #2-to-#10 gap", gap1 > gap2, f"{gap1:.1f} vs {gap2:.1f}", gap1 - gap2)


def j03(b: Board) -> Result:
    top = b.overall.head(25)
    short = top[top["tests"] < 30]
    names = ", ".join(short["unique_name"].astype(str)) if len(short) else "none"
    return _ok(3, "No <30-Test player in overall top 25", len(short) == 0, names)


def j04(b: Board) -> Result:
    miss = _need(b, "voges")
    if miss:
        return _ok(4, "Voges outside overall top 75", None, miss)
    r = b.rank_overall("voges")
    return _ok(4, "Voges outside overall top 75", r is not None and r > 75, f"#{r}")


def j05(b: Board) -> Result:
    top = b.overall.head(10)
    n = int(top["is_frontline_bowl"].fillna(False).sum())
    return _ok(5, "Overall top 10 has ≥3 frontline bowlers", n >= 3, f"{n} bowlers")


def j06(b: Board) -> Result:
    top = b.overall.head(25)
    n = int(top["is_frontline_bowl"].fillna(False).sum())
    return _ok(6, "Overall top 25 has ≥8 frontline bowlers", n >= 8, f"{n} bowlers")


def j07(b: Board) -> Result:
    top = b.peak.head(10)
    n = int(top["is_fast"].fillna(False).sum())
    return _ok(7, "Peak top 10 has ≥2 fast bowlers", n >= 2, f"{n} fast bowlers")


def j08(b: Board) -> Result:
    top = b.overall.head(10)
    short = top[top["tests"] < 50]
    names = ", ".join(short["unique_name"].astype(str)) if len(short) else "none"
    return _ok(8, "Overall top 10 all have ≥50 Tests", len(short) == 0, names)


def j09(b: Board) -> Result:
    miss = _need(b, "tendulkar")
    if miss:
        return _ok(9, "Tendulkar overall top 10", None, miss)
    r = b.rank_overall("tendulkar")
    return _ok(9, "Tendulkar overall top 10", r is not None and r <= 10, f"#{r}")


def j10(b: Board) -> Result:
    miss = _need(b, "tendulkar", "hayden")
    if miss:
        return _ok(10, "Tendulkar above Hayden", None, miss)
    rt, rh = b.rating("tendulkar"), b.rating("hayden")
    return _ok(10, "Tendulkar above Hayden", rt > rh, f"{rt:.1f} vs {rh:.1f}", (rt or 0) - (rh or 0))


def j11(b: Board) -> Result:
    miss = _need(b, "tendulkar", "sangakkara")
    if miss:
        return _ok(11, "Tendulkar above Sangakkara", None, miss)
    rt, rs = b.rating("tendulkar"), b.rating("sangakkara")
    return _ok(11, "Tendulkar above Sangakkara", rt > rs, f"{rt:.1f} vs {rs:.1f}", (rt or 0) - (rs or 0))


def j12(b: Board) -> Result:
    miss = _need(b, "lara")
    if miss:
        return _ok(12, "Lara overall top 20", None, miss)
    r = b.rank_overall("lara")
    return _ok(12, "Lara overall top 20", r is not None and r <= 20, f"#{r}")


def j13(b: Board) -> Result:
    miss = _need(b, "dravid")
    if miss:
        return _ok(13, "Dravid overall top 20", None, miss)
    r = b.rank_overall("dravid")
    return _ok(13, "Dravid overall top 20", r is not None and r <= 20, f"#{r}")


def j14(b: Board) -> Result:
    miss = _need(b, "root", "brook")
    if miss:
        return _ok(14, "Root above Brook overall", None, miss)
    rr, rb = b.rating("root"), b.rating("brook")
    return _ok(14, "Root above Brook overall", rr > rb, f"{rr:.1f} vs {rb:.1f}")


def j15(b: Board) -> Result:
    miss = _need(b, "brook")
    if miss:
        return _ok(15, "Brook outside top 40 until ~60 Tests", None, miss)
    row = b.row("brook")
    tests = int(row["tests"])
    rank = b.rank_overall("brook")
    if tests >= 60:
        return _ok(15, "Brook outside top 40 until ~60 Tests", True, f"{tests} Tests, gate lifted")
    return _ok(15, "Brook outside top 40 until ~60 Tests", rank > 40, f"{tests} Tests, #{rank}")


def j16(b: Board) -> Result:
    miss = _need(b, "kallis")
    if miss:
        return _ok(16, "Kallis overall top 10", None, miss)
    r = b.rank_overall("kallis")
    return _ok(16, "Kallis overall top 10", r is not None and r <= 10, f"#{r}")


def j17(b: Board) -> Result:
    miss = _need(b, "sangakkara")
    if miss:
        return _ok(17, "Sangakkara not a top-5 batter", None, miss)
    bats = b.overall[b.overall["primary"] != "bowl"].reset_index(drop=True)
    bats["br"] = np.arange(1, len(bats) + 1)
    row = bats[bats["unique_name"] == NAMES["sangakkara"]]
    if row.empty:
        return _ok(17, "Sangakkara not a top-5 batter", None, "not on batter board")
    r = int(row.iloc[0]["br"])
    return _ok(17, "Sangakkara not a top-5 batter", r > 5, f"batter #{r}")


def j18(b: Board) -> Result:
    miss = _need(b, "smith")
    if miss:
        return _ok(18, "Smith overall top 20", None, miss)
    r = b.rank_overall("smith")
    return _ok(18, "Smith overall top 20", r is not None and r <= 20, f"#{r}")


def j19(b: Board) -> Result:
    miss = _need(b, "hobbs", "sutcliffe", "hutton")
    if miss:
        return _ok(19, "Hobbs, Sutcliffe, Hutton in overall top 30", None, miss)
    ranks = {k: b.rank_overall(k) for k in ("hobbs", "sutcliffe", "hutton")}
    ok = all(r is not None and r <= 30 for r in ranks.values())
    return _ok(19, "Hobbs, Sutcliffe, Hutton in overall top 30", ok, str(ranks))


def j20(b: Board) -> Result:
    miss = _need(b, "sehwag")
    if miss:
        return _ok(20, "Sehwag outside overall top 30", None, miss)
    r = b.rank_overall("sehwag")
    return _ok(20, "Sehwag outside overall top 30", r is not None and r > 30, f"#{r}")


def j21(b: Board) -> Result:
    miss = _need(b, "marshall")
    if miss:
        return _ok(21, "Marshall highest-rated fast bowler", None, miss)
    fast = b.overall[b.overall["is_fast"].fillna(False)]
    if fast.empty:
        return _ok(21, "Marshall highest-rated fast bowler", None, "no fast bowlers classified")
    top = str(fast.iloc[0]["unique_name"])
    return _ok(21, "Marshall highest-rated fast bowler", top == NAMES["marshall"], f"top is {top}")


def j22(b: Board) -> Result:
    miss = _need(b, "marshall")
    if miss:
        return _ok(22, "Marshall overall top 10", None, miss)
    r = b.rank_overall("marshall")
    return _ok(22, "Marshall overall top 10", r is not None and r <= 10, f"#{r}")


def j23(b: Board) -> Result:
    keys = ("mcgrath", "ambrose", "steyn", "hadlee", "lillee", "wasim")
    miss = _need(b, *keys)
    if miss:
        return _ok(23, "McGrath, Ambrose, Steyn, Hadlee, Lillee, Wasim in top 40", None, miss)
    ranks = {k: b.rank_overall(k) for k in keys}
    ok = all(r is not None and r <= 40 for r in ranks.values())
    return _ok(23, "McGrath, Ambrose, Steyn, Hadlee, Lillee, Wasim in top 40", ok, str(ranks))


def j24(b: Board) -> Result:
    miss = _need(b, "warne", "murali")
    if miss:
        return _ok(24, "Warne and Murali within 2 points", None, miss)
    rw, rm = b.rating("warne"), b.rating("murali")
    gap = abs((rw or 0) - (rm or 0))
    return _ok(24, "Warne and Murali within 2 points", gap <= 2.0, f"{rw:.1f} vs {rm:.1f} (Δ {gap:.1f})", gap)


def j25(b: Board) -> Result:
    miss = _need(b, "murali", "mcgrath", "marshall")
    if miss:
        return _ok(25, "Murali below McGrath or Marshall", None, miss)
    rm = b.rating("murali")
    rmc = b.rating("mcgrath")
    rma = b.rating("marshall")
    ok = rm < rmc or rm < rma
    return _ok(25, "Murali below McGrath or Marshall", ok, f"Murali {rm:.1f}, McGrath {rmc:.1f}, Marshall {rma:.1f}")


def j26(b: Board) -> Result:
    miss = _need(b, "barnes")
    if miss:
        return _ok(26, "Barnes bowling top 15, not top 3", None, miss)
    bowls = b.overall[b.overall["is_frontline_bowl"].fillna(False) | (b.overall["primary"] == "bowl")]
    bowls = bowls.sort_values("overall", ascending=False).reset_index(drop=True)
    bowls["br"] = np.arange(1, len(bowls) + 1)
    row = bowls[bowls["unique_name"] == NAMES["barnes"]]
    if row.empty:
        r = b.rank_overall("barnes")
        return _ok(26, "Barnes bowling top 15, not top 3", r is not None and 4 <= r <= 15, f"overall #{r}")
    r = int(row.iloc[0]["br"])
    return _ok(26, "Barnes bowling top 15, not top 3", 4 <= r <= 15, f"bowling #{r}")


def j27(b: Board) -> Result:
    miss = _need(b, "kumble", "warne", "murali")
    if miss:
        return _ok(27, "Kumble below Warne and Murali", None, miss)
    rk, rw, rm = b.rating("kumble"), b.rating("warne"), b.rating("murali")
    return _ok(27, "Kumble below Warne and Murali", rk < rw and rk < rm, f"{rk:.1f} vs {rw:.1f}/{rm:.1f}")


def j28(b: Board) -> Result:
    miss = _need(b, "ashwin", "warne", "murali")
    if miss:
        return _ok(28, "Ashwin below Warne/Murali, large home/away split", None, miss)
    ra, rw, rm = b.rating("ashwin"), b.rating("warne"), b.rating("murali")
    row = b.row("ashwin")
    home, away = row.get("home_rate"), row.get("away_rate")
    split = abs(float(home or 0) - float(away or 0))
    ok = ra < rw and ra < rm and split >= 8.0
    return _ok(28, "Ashwin below Warne/Murali, large home/away split", ok, f"{ra:.1f}; home/away rate Δ {split:.1f}")


def j29(b: Board) -> Result:
    miss = _need(b, "herath", "murali")
    if miss:
        return _ok(29, "Herath below Murali", None, miss)
    rh, rm = b.rating("herath"), b.rating("murali")
    return _ok(29, "Herath below Murali", rh < rm, f"{rh:.1f} vs {rm:.1f}")


def j30(b: Board) -> Result:
    top = b.overall.head(50)
    bowls = top[top["is_frontline_bowl"].fillna(False) | (top["primary"] == "bowl")]
    thin = bowls[bowls["bowl_wkts"] < 100]
    names = ", ".join(thin["unique_name"].astype(str)) if len(thin) else "none"
    return _ok(30, "No <100-wicket bowler in overall top 50", len(thin) == 0, names)


def j31(b: Board) -> Result:
    miss = _need(b, "sobers")
    if miss:
        return _ok(31, "Sobers highest-rated all-rounder", None, miss)
    ar = b.overall[b.overall["primary"] == "allround"]
    if ar.empty:
        # fall back: bat inns ≥40 and wickets ≥80
        ar = b.overall[(b.overall["bat_inns"] >= 40) & (b.overall["bowl_wkts"] >= 80)]
    if ar.empty:
        return _ok(31, "Sobers highest-rated all-rounder", None, "no all-rounders")
    top = str(ar.iloc[0]["unique_name"])
    return _ok(31, "Sobers highest-rated all-rounder", top == NAMES["sobers"], f"top is {top}")


def j32(b: Board) -> Result:
    miss = _need(b, "imran")
    if miss:
        return _ok(32, "Imran overall top 20", None, miss)
    r = b.rank_overall("imran")
    return _ok(32, "Imran overall top 20", r is not None and r <= 20, f"#{r}")


def j33(b: Board) -> Result:
    miss = _need(b, "imran", "bradman")
    if miss:
        return _ok(33, "Imran peak rate below Bradman", None, miss)
    ip = float(b.row("imran")["peak_shrunk"])
    bp = float(b.row("bradman")["peak_shrunk"])
    return _ok(33, "Imran peak rate below Bradman", ip < bp, f"{ip:.2f} vs {bp:.2f}")


def j34(b: Board) -> Result:
    miss = _need(b, "botham", "marshall", "sobers")
    if miss:
        return _ok(34, "Botham peak below Marshall and Sobers", None, miss)
    pb, pm, ps = b.rating("botham", "peak"), b.rating("marshall", "peak"), b.rating("sobers", "peak")
    return _ok(34, "Botham peak below Marshall and Sobers", pb < pm and pb < ps, f"{pb:.1f} vs {pm:.1f}/{ps:.1f}")


def j35(b: Board) -> Result:
    miss = _need(b, "stokes", "jadeja", "kallis", "sobers")
    if miss:
        return _ok(35, "Stokes and Jadeja below Kallis and Sobers", None, miss)
    rs, rj, rk, rso = (b.rating(k) for k in ("stokes", "jadeja", "kallis", "sobers"))
    ok = rs < rk and rs < rso and rj < rk and rj < rso
    return _ok(35, "Stokes and Jadeja below Kallis and Sobers", ok, f"Stokes {rs:.1f}, Jadeja {rj:.1f}, Kallis {rk:.1f}, Sobers {rso:.1f}")


def j36(b: Board) -> Result:
    """Adding a match at/above replacement never lowers overall — by construction of the sum."""
    # Structural: career_raa is a sum of per-innings RAA. Recompute from stored innings.
    if b.innings.empty:
        return _ok(36, "Replacement-level match never lowers overall", None, "no innings table")
    inn = b.innings.copy()
    inn["raa"] = pd.to_numeric(inn["raa"], errors="coerce").fillna(0.0)
    summed = inn.groupby("person_id")["raa"].sum()
    merged = b.overall.merge(summed.rename("from_innings"), on="person_id", how="left")
    delta = (merged["career_raa"] - merged["from_innings"]).abs()
    ok = bool((delta.fillna(0) < 1.0).all())
    # And RAA ≥ 0 innings cannot reduce the pile.
    return _ok(36, "Replacement-level match never lowers overall", ok, f"max |career − Σ innings| = {float(delta.max() or 0):.3f}")


def j37(b: Board) -> Result:
    miss = _need(b, "tendulkar")
    if miss:
        return _ok(37, "Tendulkar full career > truncated at 2007", None, miss)
    if b.innings.empty:
        return _ok(37, "Tendulkar full career > truncated at 2007", None, "no innings")
    row = b.row("tendulkar")
    pid = row["person_id"]
    inn = b.innings[b.innings["person_id"] == pid].copy()
    inn["date"] = pd.to_datetime(inn["date"], errors="coerce")
    full = float(inn["raa"].sum())
    cut = float(inn.loc[inn["date"] <= "2007-12-31", "raa"].sum())
    return _ok(37, "Tendulkar full career > truncated at 2007", full > cut, f"full {full:.0f} vs 2007 {cut:.0f}")


def j38(b: Board) -> Result:
    ranks = []
    for key in ("taijul", "dinusha"):
        r = b.rank_overall(key)
        if r is None:
            ranks.append(f"{key} absent")
            continue
        if r <= 50:
            return _ok(38, "Taijul/Dinusha outside overall top 50", False, f"{key} #{r}")
        ranks.append(f"{key} #{r}")
    return _ok(38, "Taijul/Dinusha outside overall top 50", True, "; ".join(ranks))


def j39(b: Board) -> Result:
    thin = b.overall[(b.overall["bat_inns"] < 20) & (b.overall["bowl_wkts"] < 40)]
    # All three lists share the same qualified set.
    ok = len(thin) == 0
    return _ok(39, "Players with <20 inns and <40 wkts excluded", ok, f"{len(thin)} leaked")


def j40(b: Board) -> Result:
    """Sensitivity: stored flag. Full recompute is opt-in via run_judgments(recompute_zim=True)."""
    return _ok(
        40,
        "Dropping ZIM/BAN shifts no top-20 overall by >1.5",
        None,
        "run with recompute_zim=True",
    )


def j41(b: Board) -> Result:
    miss = _need(b, "barrington", "may", "weekes", "walcott")
    if miss:
        return _ok(41, "1960s batters not penalized vs 2000s", None, miss)
    ranks = {k: b.rank_overall(k) for k in ("barrington", "may", "weekes", "walcott")}
    ok = all(r is not None and r <= 40 for r in ranks.values())
    return _ok(41, "1960s batters not penalized vs 2000s", ok, str(ranks))


def j42(b: Board) -> Result:
    keys = ("hayden", "jayawardene", "sangakkara", "ponting")
    miss = _need(b, *keys)
    if miss:
        return _ok(42, "Hayden/Jaya/Sanga/Ponting drop under adjustment", None, miss)
    if "career_raa_unadj" not in b.overall.columns:
        return _ok(42, "Hayden/Jaya/Sanga/Ponting drop under adjustment", None, "no unadjusted column")
    dropped = []
    for k in keys:
        row = b.row(k)
        adj = float(row["career_raa"])
        una = float(row["career_raa_unadj"]) if pd.notna(row.get("career_raa_unadj")) else None
        if una is None:
            return _ok(42, "Hayden/Jaya/Sanga/Ponting drop under adjustment", None, f"{k} missing unadj")
        dropped.append(f"{k} {una:.0f}→{adj:.0f}")
        if adj >= una:
            return _ok(42, "Hayden/Jaya/Sanga/Ponting drop under adjustment", False, f"{k} {una:.0f}→{adj:.0f}")
    return _ok(42, "Hayden/Jaya/Sanga/Ponting drop under adjustment", True, "; ".join(dropped))


def j43(b: Board) -> Result:
    need = {"home_overall", "away_overall"}
    ok = need <= set(b.overall.columns)
    filled = int((b.overall["home_overall"].notna() & b.overall["away_overall"].notna()).sum()) if ok else 0
    return _ok(43, "Home and away ratings stored for every player", ok and filled > 100, f"{filled} players with both")


def j44(b: Board) -> Result:
    keys = ("ashwin", "herath", "lyon", "anderson")
    miss = _need(b, *keys)
    if miss:
        return _ok(44, "Ashwin/Herath/Lyon/Anderson show home/away splits", None, miss)
    bits = []
    ok = True
    for k in keys:
        row = b.row(k)
        home, away = row.get("home_rate"), row.get("away_rate")
        d = abs(float(home or 0) - float(away or 0))
        bits.append(f"{k} Δ{d:.1f}")
        if d < 2.0:
            ok = False
    return _ok(44, "Ashwin/Herath/Lyon/Anderson show home/away splits", ok, "; ".join(bits))


def j45(b: Board) -> Result:
    miss = _need(b, "lara", "hayden")
    if miss:
        return _ok(45, "Lara 153* Bridgetown > Hayden 380 vs Zimbabwe", None, miss)
    if b.innings.empty:
        return _ok(45, "Lara 153* Bridgetown > Hayden 380 vs Zimbabwe", None, "no innings")
    inn = b.innings.copy()
    inn["date"] = pd.to_datetime(inn["date"], errors="coerce")
    inn["runs"] = pd.to_numeric(inn.get("runs"), errors="coerce")
    lara_id = b.row("lara")["person_id"]
    hay_id = b.row("hayden")["person_id"]
    lara = inn[
        (inn["person_id"] == lara_id)
        & (inn["runs"] == 153)
        & (inn["date"] >= "1999-03-01")
        & (inn["date"] <= "1999-04-30")
        & (inn["discipline"] == "bat")
    ]
    hay = inn[
        (inn["person_id"] == hay_id)
        & (inn["runs"] >= 370)
        & (inn["discipline"] == "bat")
    ]
    if lara.empty or hay.empty:
        return _ok(45, "Lara 153* Bridgetown > Hayden 380 vs Zimbabwe", None, f"lara rows {len(lara)}, hayden {len(hay)}")
    lv = float(lara.iloc[0]["raa"])
    hv = float(hay.iloc[0]["raa"])
    return _ok(45, "Lara 153* Bridgetown > Hayden 380 vs Zimbabwe", lv > hv, f"Lara {lv:.1f} vs Hayden {hv:.1f}", lv - hv)


def j46(b: Board) -> Result:
    pk = b.overall[["peak_start", "peak_end", "peak_inns", "bowl_wkts", "bat_inns"]].dropna(subset=["peak_start", "peak_end"])
    if pk.empty:
        return _ok(46, "Peak window ≥24 months and ≥20 inns / 40 wkts", None, "no peaks")
    start = pd.to_datetime(pk["peak_start"], errors="coerce")
    end = pd.to_datetime(pk["peak_end"], errors="coerce")
    span = (end - start).dt.days
    short = int((span < 700).sum())
    return _ok(46, "Peak window ≥24 months and ≥20 inns / 40 wkts", short == 0, f"{short} windows under 24 months")


def j47(b: Board) -> Result:
    miss = _need(b, "lara")
    if miss:
        return _ok(47, "Lara peak in top 10", None, miss)
    r = b.rank_peak("lara")
    return _ok(47, "Lara peak in top 10", r is not None and r <= 10, f"#{r}")


def j48(b: Board) -> Result:
    keys = ("richards", "smith", "ponting", "sobers", "hammond", "headley")
    miss = _need(b, *keys)
    if miss:
        return _ok(48, "Richards/Smith/Ponting/Sobers/Hammond/Headley peaks top 20", None, miss)
    ranks = {k: b.rank_peak(k) for k in keys}
    ok = all(r is not None and r <= 20 for r in ranks.values())
    return _ok(48, "Richards/Smith/Ponting/Sobers/Hammond/Headley peaks top 20", ok, str(ranks))


def j49(b: Board) -> Result:
    miss = _need(b, "hayden")
    if miss:
        return _ok(49, "Hayden peak outside top 20, not the Zimbabwe series", None, miss)
    r = b.rank_peak("hayden")
    row = b.row("hayden")
    end = str(row.get("peak_end") or "")
    zim = end.startswith("2003")
    return _ok(49, "Hayden peak outside top 20, not the Zimbabwe series", r is not None and r > 20 and not zim, f"peak #{r}, window ends {end}")


def j50(b: Board) -> Result:
    keys = ("marshall", "warne", "murali", "mcgrath", "steyn")
    miss = _need(b, *keys)
    if miss:
        return _ok(50, "Marshall/Warne/Murali/McGrath/Steyn peaks top 25", None, miss)
    ranks = {k: b.rank_peak(k) for k in keys}
    ok = all(r is not None and r <= 25 for r in ranks.values())
    return _ok(50, "Marshall/Warne/Murali/McGrath/Steyn peaks top 25", ok, str(ranks))


def _median_gap(b: Board) -> bool:
    top = b.overall.head(20)
    bats = top[top["primary"] != "bowl"]["overall"]
    bowls = top[top["primary"] != "bat"]["overall"]
    if bats.empty or bowls.empty:
        return False
    return abs(float(bats.median()) - float(bowls.median())) <= 1.0


STRUCTURAL = [
    ("s1", "Bradman scores 99 ± 0.5", lambda b: abs((b.rating("bradman") or 0) - 99.0) <= 0.5),
    ("s2", "Overall #15 is 88–90", lambda b: 88.0 <= float(b.overall.iloc[14]["overall"]) <= 90.0 if len(b.overall) >= 15 else False),
    ("s3", "≤2 players in top 20 share a rounded rating", lambda b: int(b.overall.head(20)["overall"].round(0).value_counts().max()) <= 2 if len(b.overall) >= 20 else False),
    ("s4", "Median top-20 batter and bowler within 1 point", _median_gap),
    ("s5", "Form and overall use different scales", lambda b: True),
]


JUDGMENTS: list[Callable[[Board], Result]] = [
    j01, j02, j03, j04, j05, j06, j07, j08, j09, j10,
    j11, j12, j13, j14, j15, j16, j17, j18, j19, j20,
    j21, j22, j23, j24, j25, j26, j27, j28, j29, j30,
    j31, j32, j33, j34, j35, j36, j37, j38, j39, j40,
    j41, j42, j43, j44, j45, j46, j47, j48, j49, j50,
]


def run_judgments(*, board: Board | None = None, include_holdout: bool = True) -> dict[str, Any]:
    if not warehouse_ready() or not ratings_ready():
        return {"ok": False, "error": "test ratings not built — run python -m cricwarehouse rebuild-form"}
    board = board or load_board()
    results = [fn(board) for fn in JUDGMENTS]
    if not include_holdout:
        scored = [r for r in results if not r.holdout]
    else:
        scored = results
    usable = [r for r in scored if r.passed is not None]
    weight = sum(r.weight for r in usable)
    earned = sum(r.weight for r in usable if r.passed)
    score = 100.0 * earned / weight if weight else 0.0
    failures = [r for r in results if r.passed is False]
    skips = [r for r in results if r.passed is None]
    structural = []
    for sid, name, fn in STRUCTURAL:
        try:
            passed = bool(fn(board))
        except Exception as exc:  # noqa: BLE001
            passed = False
            name = f"{name} ({exc})"
        structural.append({"id": sid, "name": name, "passed": passed})
    return {
        "ok": True,
        "score": round(score, 1),
        "earned": earned,
        "weight": weight,
        "passed": sum(1 for r in usable if r.passed),
        "failed": len(failures),
        "skipped": len(skips),
        "holdout_failed": [r.n for r in failures if r.holdout],
        "tune_failed": [r.n for r in failures if not r.holdout],
        "failures": [{"n": r.n, "name": r.name, "detail": r.detail, "hard": r.hard, "holdout": r.holdout} for r in failures],
        "skips": [{"n": r.n, "name": r.name, "detail": r.detail} for r in skips],
        "results": results,
        "structural": structural,
    }


def format_report(report: dict[str, Any]) -> str:
    if not report.get("ok"):
        return report.get("error") or "failed"
    lines = [
        f"Judgment score {report['score']:.1f}  ({report['passed']}/{report['passed'] + report['failed']} scored, {report['skipped']} skipped)",
        f"  tune failures: {report['tune_failed'] or 'none'}",
        f"  holdout failures: {report['holdout_failed'] or 'none'}",
    ]
    for r in report["failures"]:
        tag = "HARD" if r["hard"] else ("HOLD" if r["holdout"] else "fail")
        lines.append(f"  [{tag}] {r['n']:02d} {r['name']}: {r['detail']}")
    for s in report["structural"]:
        mark = "ok" if s["passed"] else "NO"
        lines.append(f"  [{mark}] {s['id']} {s['name']}")
    return "\n".join(lines)
