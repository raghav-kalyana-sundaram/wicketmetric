"""Synthetic Tests for the Test RAA pipeline — no warehouse required."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from cricwarehouse.app.test_value import (
    Params,
    aggregate_players,
    classify,
    prepare_lines,
    qualify,
    run_model,
    score_raa,
)
from cricwarehouse.app.judgments import HARD, HOLDOUT, JUDGMENTS, NAMES


def _bat(
    pid,
    match,
    day,
    runs,
    *,
    outs=1,
    team="Australia",
    home="Australia",
    away="England",
    venue="SCG",
    innings=1,
    name=None,
):
    return {
        "person_id": pid,
        "match_id": match,
        "innings": innings,
        "runs": runs,
        "balls": max(runs * 2, 10),
        "not_out": outs == 0,
        "dismissal_kind": None if outs == 0 else "bowled",
        "team": team,
        "player_name": name or pid,
        "display_name": name or pid,
        "unique_name": name or pid,
        "slug": (name or pid).lower().replace(" ", "-"),
        "start_date": day.isoformat() if hasattr(day, "isoformat") else day,
        "venue": venue,
        "team_home": home,
        "team_away": away,
        "gender": "male",
    }


def _bowl(
    pid,
    match,
    day,
    wickets,
    runs,
    *,
    team="Australia",
    home="Australia",
    away="England",
    venue="SCG",
    innings=2,
    balls=120,
    name=None,
):
    return {
        "person_id": pid,
        "match_id": match,
        "innings": innings,
        "runs": runs,
        "legal_balls": balls,
        "wickets": wickets,
        "team": team,
        "player_name": name or pid,
        "display_name": name or pid,
        "unique_name": name or pid,
        "slug": (name or pid).lower().replace(" ", "-"),
        "start_date": day.isoformat() if hasattr(day, "isoformat") else day,
        "venue": venue,
        "team_home": home,
        "team_away": away,
        "gender": "male",
    }


def _career_match(n=40, *, star_runs=80, other_runs=20, start=date(2000, 1, 1)):
    """n Tests: one star batter, ten others, a stock attack."""
    bat, bowl = [], []
    others = [f"o{i}" for i in range(10)]
    bowlers = [f"q{i}" for i in range(5)]
    for m in range(n):
        day = start + timedelta(days=40 * m)
        mid = f"m{m}"
        bat.append(_bat("star", mid, day, star_runs, name="Star Batter"))
        for i, oid in enumerate(others):
            bat.append(_bat(oid, mid, day, other_runs, innings=1, name=oid))
        for i, bid in enumerate(bowlers):
            bowl.append(_bowl(bid, mid, day, 2, 40, name=bid))
            bat.append(_bat(bid, mid, day, 8, innings=2, team="England", home="Australia", away="England"))
        # opposition innings so the match has two sides
        for i, oid in enumerate(others):
            bat.append(
                _bat(oid, mid, day, other_runs, innings=2, team="England", home="Australia", away="England", name=oid)
            )
        bowl.append(_bowl("star", mid, day, 0, 12, balls=12, innings=2, team="Australia", name="Star Batter"))
    return pd.DataFrame(bat), pd.DataFrame(bowl)


def test_not_out_is_not_charged_an_out():
    day = date(2010, 1, 1)
    bat = pd.DataFrame(
        [
            _bat("a", "m1", day, 50, outs=0, name="A"),
            _bat("b", "m1", day, 50, outs=1, name="B"),
            _bat("c", "m1", day, 20, outs=1, name="C"),
            _bat("d", "m1", day, 20, outs=1, name="D"),
        ]
    )
    model = run_model(bat, pd.DataFrame(), Params(attack_passes=1, z_pool_min_tests=1, min_list_inns=1, min_list_wkts=1))
    pm = model["player_matches"]
    a = float(pm.loc[pm["person_id"] == "a", "raa_bat"].sum())
    b = float(pm.loc[pm["person_id"] == "b", "raa_bat"].sum())
    assert a > b


def test_adding_replacement_or_better_match_raises_career_value():
    bat, bowl = _career_match(24, star_runs=70)
    model = run_model(bat, bowl, Params(attack_passes=1, peak_min_bat_inns=8, z_pool_min_tests=5))
    before = float(model["players"].set_index("person_id").loc["star", "career_raa"])
    extra_day = date(2000, 1, 1) + timedelta(days=40 * 24)
    extra_bat, extra_bowl = _career_match(1, star_runs=70, start=extra_day)
    extra_bat["match_id"] = "extra"
    extra_bowl["match_id"] = "extra"
    bat2 = pd.concat([bat, extra_bat], ignore_index=True)
    bowl2 = pd.concat([bowl, extra_bowl], ignore_index=True)
    model2 = run_model(bat2, bowl2, Params(attack_passes=1, peak_min_bat_inns=8, z_pool_min_tests=5))
    after = float(model2["players"].set_index("person_id").loc["star", "career_raa"])
    assert after >= before - 1e-6


def test_peak_rejects_a_six_match_purple_patch():
    # 30 ordinary matches, then 6 absurd ones packed into two months.
    bat, bowl = _career_match(30, star_runs=35)
    start = date(2000, 1, 1) + timedelta(days=40 * 30)
    hot_bat, hot_bowl = [], []
    others = [f"o{i}" for i in range(10)]
    bowlers = [f"q{i}" for i in range(5)]
    for m in range(6):
        day = start + timedelta(days=8 * m)
        mid = f"hot{m}"
        hot_bat.append(_bat("star", mid, day, 250, name="Star Batter"))
        for oid in others:
            hot_bat.append(_bat(oid, mid, day, 15, name=oid))
        for bid in bowlers:
            hot_bowl.append(_bowl(bid, mid, day, 2, 50, name=bid))
            hot_bat.append(_bat(bid, mid, day, 5, innings=2, team="England", home="Australia", away="England"))
    bat = pd.concat([bat, pd.DataFrame(hot_bat)], ignore_index=True)
    bowl = pd.concat([bowl, pd.DataFrame(hot_bowl)], ignore_index=True)
    params = Params(attack_passes=1, peak_min_days=730, peak_min_bat_inns=20, peak_min_tests=12, z_pool_min_tests=5)
    model = run_model(bat, bowl, params)
    star = model["players"].set_index("person_id").loc["star"]
    start_p = pd.Timestamp(star["peak_start"])
    end_p = pd.Timestamp(star["peak_end"])
    assert (end_p - start_p).days >= 700
    assert float(star["peak_rate"]) > float(star["career_rate"]) + 5


def test_weak_attack_reduces_batting_raa_for_the_same_score():
    day = date(2011, 1, 1)
    # Build two matches with identical scorelines except the bowling team's identity,
    # after giving each attack a history so the rolling R/W can separate them.
    bat, bowl = [], []
    for m in range(12):
        d = date(2010, 1, 1) + timedelta(days=30 * m)
        # Strong attack (England): cheap wickets
        bat.append(_bat("victim", f"e{m}", d, 10, team="Australia", home="Australia", away="England", venue="Lord's"))
        for i in range(9):
            bat.append(_bat(f"e{i}", f"e{m}", d, 8, team="Australia", home="Australia", away="England", venue="Lord's"))
        bowl.append(_bowl("mcg", f"e{m}", d, 8, 80, team="England", home="Australia", away="England", venue="Lord's", balls=240))
        # Weak attack (Zimbabwe): dear wickets
        bat.append(_bat("victim2", f"z{m}", d, 10, team="Australia", home="Australia", away="Zimbabwe", venue="Harare"))
        for i in range(9):
            bat.append(_bat(f"z{i}", f"z{m}", d, 40, team="Australia", home="Australia", away="Zimbabwe", venue="Harare"))
        bowl.append(_bowl("zim", f"z{m}", d, 2, 200, team="Zimbabwe", home="Australia", away="Zimbabwe", venue="Harare", balls=240))
    # The innings under test: 100 vs each attack, same outs.
    d = date(2011, 6, 1)
    bat.append(_bat("hero", "vsE", d, 100, team="Australia", home="Australia", away="England", venue="Lord's", name="Hero"))
    for i in range(9):
        bat.append(_bat(f"e{i}", "vsE", d, 20, team="Australia", home="Australia", away="England", venue="Lord's"))
    bowl.append(_bowl("mcg", "vsE", d, 6, 120, team="England", home="Australia", away="England", venue="Lord's"))
    bat.append(_bat("hero", "vsZ", d, 100, team="Australia", home="Australia", away="Zimbabwe", venue="Harare", name="Hero"))
    for i in range(9):
        bat.append(_bat(f"z{i}", "vsZ", d, 40, team="Australia", home="Australia", away="Zimbabwe", venue="Harare"))
    bowl.append(_bowl("zim", "vsZ", d, 2, 250, team="Zimbabwe", home="Australia", away="Zimbabwe", venue="Harare"))
    model = run_model(pd.DataFrame(bat), pd.DataFrame(bowl), Params(attack_passes=3, min_list_inns=1, z_pool_min_tests=1))
    inn = model["innings"]
    inn = inn[(inn["person_id"] == "hero") & (inn["discipline"] == "bat")]
    vs_e = float(inn.loc[inn["match_id"] == "vsE", "raa"].iloc[0])
    vs_z = float(inn.loc[inn["match_id"] == "vsZ", "raa"].iloc[0])
    assert vs_e > vs_z


def test_small_samples_are_excluded_from_lists():
    day = date(2015, 1, 1)
    bat = pd.DataFrame([_bat("short", "m1", day, 200, name="Short")])
    model = run_model(bat, pd.DataFrame(), Params(min_list_inns=20, min_list_wkts=40, attack_passes=1))
    assert "short" not in set(model["players"]["person_id"]) if len(model["players"]) else True
    assert model["players"].empty or (model["players"]["bat_inns"] >= 20).all() or (model["players"]["bowl_wkts"] >= 40).all()


def test_bradman_anchor_calibrates_to_99():
    bat, bowl = _career_match(50, star_runs=120)
    bat.loc[bat["person_id"] == "star", "unique_name"] = "DG Bradman"
    model = run_model(bat, bowl, Params(attack_passes=1, z_pool_min_tests=10, peak_min_bat_inns=15))
    star = model["players"][model["players"]["unique_name"] == "DG Bradman"]
    assert not star.empty
    assert abs(float(star.iloc[0]["overall"]) - 99.0) <= 0.5


def test_form_is_on_a_different_scale_from_overall():
    bat, bowl = _career_match(40, star_runs=60)
    model = run_model(bat, bowl, Params(attack_passes=1, z_pool_min_tests=8, form_gate_inns=8))
    row = model["players"].set_index("person_id").loc["star"]
    assert 40 <= float(row["overall"]) <= 99.9
    if pd.notna(row.get("form")):
        assert 0 <= float(row["form"]) <= 10


def test_overall_reproduces_from_stored_innings():
    bat, bowl = _career_match(20, star_runs=55)
    model = run_model(bat, bowl, Params(attack_passes=1, z_pool_min_tests=5, peak_min_bat_inns=10))
    inn = model["innings"]
    summed = inn.groupby("person_id")["raa"].sum()
    players = model["players"].set_index("person_id")
    for pid in players.index:
        assert abs(float(players.loc[pid, "career_raa"]) - float(summed.get(pid, 0))) < 1.0


def test_home_and_away_columns_exist():
    bat, bowl = _career_match(16, star_runs=50)
    model = run_model(bat, bowl, Params(attack_passes=1, z_pool_min_tests=4, peak_min_bat_inns=8, min_list_inns=8))
    row = model["players"].iloc[0]
    assert "home_overall" in row
    assert "away_overall" in row


def test_harness_has_fifty_judgments_and_holdouts():
    assert len(JUDGMENTS) == 50
    assert HARD == {1, 3, 9, 21, 36, 39, 45, 49}
    assert HOLDOUT == {10, 12, 14, 18, 23, 28, 32, 34, 41, 48}
    assert HARD.isdisjoint(HOLDOUT)
    assert "bradman" in NAMES
    assert "brook" in NAMES
