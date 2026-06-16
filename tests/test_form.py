"""Form ratings from counting stats — no warehouse, no T20 resource model."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from cricwarehouse.app.form import (
    apply_nines,
    best_format,
    cause_of,
    piecewise,
    player_overall,
    publish_score,
    score_batting_window,
    score_bowling_window,
    score_snapshot,
    shrink,
)


def test_piecewise_hits_anchors_and_clamps():
    pts = ((10, 50), (20, 70), (40, 90))
    assert piecewise(10, pts) == 50
    assert piecewise(20, pts) == 70
    assert piecewise(15, pts) == 60
    assert piecewise(5, pts) == 50
    assert piecewise(80, pts) == 90
    assert piecewise(None, pts) is None


def test_piecewise_invert_rewards_cheaper_bowling():
    pts = ((40, 52), (20, 87), (12, 99))
    assert piecewise(40, pts, invert=True) == 52
    assert piecewise(12, pts, invert=True) == 99
    cheap = piecewise(18, pts, invert=True)
    dear = piecewise(30, pts, invert=True)
    assert cheap > dear


def test_shrink_holds_thin_samples_down():
    assert shrink(96, 4) < 88
    assert shrink(96, 12) == 96
    assert shrink(96, 12) > shrink(96, 6)


def test_elite_test_batting_window_is_high_not_automatically_99():
    elite = score_batting_window(
        fmt="test", inns=18, runs=1400, outs=14, balls=2400, hundreds=6, fifties=4
    )
    handy = score_batting_window(
        fmt="test", inns=16, runs=520, outs=15, balls=1400, hundreds=1, fifties=3
    )
    assert elite and handy
    assert elite["rating"] > handy["rating"]
    assert elite["rating"] >= 88
    assert handy["rating"] < 84


def test_test_rating_barely_moves_when_strike_rate_jumps():
    slow = score_batting_window(
        fmt="test", inns=16, runs=800, outs=12, balls=2200, hundreds=2, fifties=4
    )
    quick = score_batting_window(
        fmt="test", inns=16, runs=800, outs=12, balls=1100, hundreds=2, fifties=4
    )
    t20_slow = score_batting_window(
        fmt="t20i", inns=16, runs=480, outs=14, balls=420, hundreds=0, fifties=4
    )
    t20_quick = score_batting_window(
        fmt="t20i", inns=16, runs=480, outs=14, balls=280, hundreds=0, fifties=4
    )
    assert abs(quick["rating"] - slow["rating"]) < 4
    assert t20_quick["rating"] - t20_slow["rating"] > 5


def test_bowling_average_and_economy_matter_by_format():
    tight = score_bowling_window(fmt="t20i", inns=16, wickets=24, runs=380, balls=360)
    leaky = score_bowling_window(fmt="t20i", inns=16, wickets=24, runs=520, balls=360)
    test_same_econ = score_bowling_window(fmt="test", inns=14, wickets=40, runs=880, balls=2400)
    test_dearer = score_bowling_window(fmt="test", inns=14, wickets=28, runs=980, balls=2400)
    assert tight["rating"] > leaky["rating"]
    assert test_same_econ["rating"] > test_dearer["rating"]


def test_elite_test_bowling_window_is_high():
    # Warne-shaped: ~100 wickets in the window at ~22, strike-rate in the mid-40s.
    elite = score_bowling_window(fmt="test", inns=30, wickets=99, runs=2190, balls=4450)
    stock = score_bowling_window(fmt="test", inns=16, wickets=32, runs=960, balls=2100)
    assert elite and stock
    assert elite["rating"] >= 93
    assert elite["rating"] > stock["rating"]
    assert stock["rating"] < 88


def test_small_samples_do_not_qualify():
    assert score_batting_window(
        fmt="odi", inns=3, runs=220, outs=2, balls=180, hundreds=1, fifties=0
    ) is None
    assert score_bowling_window(fmt="test", inns=10, wickets=4, runs=280, balls=200) is None


def test_overall_is_the_best_international_format():
    rating, fmt = best_format({"test": 90, "t20i": 70, "t20": 99})
    assert fmt == "test"
    assert rating == 90
    # Ties keep Test ahead of later families.
    tied, tied_fmt = best_format({"test": 85, "odi": 85, "t20i": 85})
    assert tied == 85
    assert tied_fmt == "test"
    assert best_format({}) == (None, None)


def test_all_rounder_bump_cannot_mint_a_99():
    ovr, primary = player_overall(92, 86)
    assert primary == "bat"
    assert 92 < ovr <= 98.4
    specialist, role = player_overall(92, None)
    assert specialist == 92
    assert role == "bat"


def test_publish_score_puts_bradman_on_99_and_keeps_decimals():
    assert publish_score(97.668) == 99.0
    assert publish_score(98.029) == 99.4
    assert publish_score(90.891) == 92.2
    assert publish_score(40) == 41.3
    rows = [
        {"person_id": "a", "raw_overall": 97.668, "bat": 97.668, "bowl": None, "active": False},
        {"person_id": "b", "raw_overall": 90.891, "bat": None, "bowl": 90.891, "active": True},
    ]
    apply_nines(rows)
    assert all(r.get("is_99") is False for r in rows)
    assert rows[0]["form"] == 99.0
    assert rows[0]["bat"] == 99.0
    assert rows[1]["form"] == 92.2
    assert rows[1]["bowl"] == 92.2


def _inn(pid, day, comp, *, runs=0, balls=0, not_out=False, wickets=0, legal_balls=0, gender="male"):
    return {
        "person_id": pid,
        "start_date": day.isoformat(),
        "competition": comp,
        "gender": gender,
        "runs": runs,
        "balls": balls,
        "not_out": not_out,
        "wickets": wickets,
        "legal_balls": legal_balls,
    }


def test_snapshot_prefers_recent_form_and_caps_nines():
    as_of = date(2024, 12, 31)
    bat_rows = []
    bowl_rows = []
    # Six elite batters in the window, plus one whose hundreds are two years old.
    for i in range(6):
        for n in range(12):
            day = as_of - timedelta(days=20 + n * 12)
            bat_rows.append(_inn(f"star-{i}", day, "test", runs=90 + i, balls=160, not_out=n % 4 == 0))
            bat_rows.append(_inn(f"star-{i}", day, "odi", runs=70 + i, balls=75))
    cold = as_of - timedelta(days=700)
    for n in range(12):
        bat_rows.append(_inn("cold", cold - timedelta(days=n * 10), "test", runs=150, balls=280))

    # One current fast bowler in the mix.
    for n in range(14):
        day = as_of - timedelta(days=15 + n * 14)
        bowl_rows.append(_inn("quick", day, "test", wickets=4, legal_balls=120, runs=70))
        bowl_rows.append(_inn("quick", day, "odi", wickets=3, legal_balls=60, runs=28))

    from cricwarehouse.app.form import _prepare_lines

    bat = _prepare_lines(pd.DataFrame(bat_rows), "bat")
    bowl = _prepare_lines(pd.DataFrame(bowl_rows), "bowl")
    scored = score_snapshot(bat, bowl, as_of)
    by_id = {r["person_id"]: r for r in scored}
    assert "star-0" in by_id
    assert by_id["star-5"]["overall"] >= by_id["star-0"]["overall"]
    if "cold" in by_id:
        assert by_id["cold"]["overall"] < by_id["star-5"]["overall"]
    assert all(r.get("is_99") is False for r in scored)
    assert all("raa" not in r and "war" not in r for r in scored)
    for r in scored:
        if r.get("raw_overall") is not None:
            assert r["form"] == publish_score(r["raw_overall"])
            assert r["overall"] == r["form"]


def test_stale_tests_do_not_dilute_current_odi_form():
    from cricwarehouse.app.form import _prepare_lines

    as_of = date(2024, 12, 31)
    bat_rows = []
    for n in range(12):
        day = as_of - timedelta(days=20 + n * 14)
        bat_rows.append(_inn("x", day, "odi", runs=80, balls=90))
    for n in range(10):
        day = as_of - timedelta(days=500 + n * 10)
        bat_rows.append(_inn("x", day, "test", runs=8, balls=40))
    bat = _prepare_lines(pd.DataFrame(bat_rows), "bat")
    scored = score_snapshot(bat, pd.DataFrame(), as_of)
    row = next(r for r in scored if r["person_id"] == "x")
    assert row["bat_test"] is None
    assert row["bat_odi"] is not None
    assert row["overall"] >= 80


def test_test_goat_is_not_diluted_by_weaker_white_ball():
    from cricwarehouse.app.form import _prepare_lines

    as_of = date(2024, 12, 31)
    bat_rows = []
    for n in range(14):
        day = as_of - timedelta(days=20 + n * 16)
        bat_rows.append(_inn("goat", day, "test", runs=120, balls=220, not_out=n % 3 == 0))
        bat_rows.append(_inn("goat", day, "odi", runs=35, balls=50))
    bat = _prepare_lines(pd.DataFrame(bat_rows), "bat")
    scored = score_snapshot(bat, pd.DataFrame(), as_of)
    row = next(r for r in scored if r["person_id"] == "goat")
    assert row["test"] is not None
    assert row["odi"] is not None
    assert row["test"] > row["odi"] + 8
    assert abs(row["form"] - row["test"]) < 0.01
    assert abs(row["bat"] - row["bat_test"]) < 0.01


def test_franchise_t20_does_not_feed_international_overall():
    from cricwarehouse.app.form import _prepare_lines

    as_of = date(2024, 5, 31)
    bat_rows = []
    for n in range(12):
        day = as_of - timedelta(days=10 + n * 8)
        bat_rows.append(_inn("sky", day, "ipl", runs=55, balls=32))
        bat_rows.append(_inn("sky", day, "t20i", runs=22, balls=18))
    bat = _prepare_lines(pd.DataFrame(bat_rows), "bat")
    scored = score_snapshot(bat, pd.DataFrame(), as_of)
    row = next(r for r in scored if r["person_id"] == "sky")
    assert row["t20"] is not None
    assert row["t20i"] is not None
    assert row["bat_t20"] is not None
    # Overall is the T20I rating, not a blend with IPL.
    assert abs(row["form"] - row["t20i"]) < 0.6
    mixed, fam = best_format({"t20i": 70, "t20": 95})
    assert mixed == 70
    assert fam == "t20i"


def test_t20_family_uses_the_t20i_curve():
    ipl = score_batting_window(
        fmt="t20", inns=16, runs=480, outs=14, balls=280, hundreds=0, fifties=4
    )
    intl = score_batting_window(
        fmt="t20i", inns=16, runs=480, outs=14, balls=280, hundreds=0, fifties=4
    )
    assert ipl and intl
    assert abs(ipl["rating"] - intl["rating"]) < 0.01


def test_retired_hero_is_peak_not_last_window():
    from cricwarehouse.app.form import pick_hero

    rows = [
        {"as_of": "2011-12-31", "form": 92, "overall": 92},
        {"as_of": "2013-06-30", "form": 80, "overall": 80},
        {"as_of": "2014-10-31", "form": 68, "overall": 68},
    ]
    hero, peak, retired = pick_hero(rows, "2026-08-31")
    assert retired is True
    assert hero["form"] == 92
    assert peak["as_of"] == "2011-12-31"
    live, _, still_in = pick_hero(rows[-1:] + [{"as_of": "2026-08-31", "form": 73, "overall": 73}], "2026-08-31")
    assert still_in is False
    assert live["form"] == 73


def test_cause_of_names_the_winning_format_and_window():
    batter = cause_of(
        {
            "test": 86.0,
            "odi": 72.0,
            "t20i": None,
            "bat_test": 86.0,
            "bowl_test": None,
            "primary": "bat",
            "bat_avg_test": 55.21,
            "bat_sr_test": 48.14,
            "bat_runs_test": 1840.4,
            "bat_inns_test": 18.2,
        }
    )
    assert batter["format"] == "test"
    assert batter["format_ovr"] == 86
    assert batter["line"] == "Tests · bat 86.0 · 55.2 avg · 48.1 SR · 1,840 runs · 18 inns"

    bowler = cause_of(
        {
            "test": 80.0,
            "odi": 91.0,
            "t20i": 88.0,
            "bat_odi": None,
            "bowl_odi": 91.0,
            "primary": "bowl",
            "bowl_avg_odi": 18.44,
            "bowl_sr_odi": 32.1,
            "bowl_wkts_odi": 42.6,
            "bowl_inns_odi": 16.4,
        }
    )
    assert bowler["format"] == "odi"
    assert "ODI" in bowler["line"]
    assert "bowl 91.0" in bowler["line"]
    assert "18.4 avg" in bowler["line"]
    assert "32.1 SR" in bowler["line"]
    assert "43 wkts" in bowler["line"]
