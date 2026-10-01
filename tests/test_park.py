"""Park-factor math for the stat-line shift card — no application data required."""

from __future__ import annotations

from cricwarehouse.app.park import (
    CellIndex,
    EnvRow,
    MatchLine,
    TalentIndex,
    Totals,
    attach_pitch,
    expect_lines,
    expected_sr,
    family_of,
    innings_role,
    loo_rate,
    park_factor,
    shrink_phi,
)


def _env(match_id, day, venue, runs, balls, wickets=5, role="set", competition="ipl"):
    return EnvRow(
        match_id=match_id,
        date=day,
        venue=venue,
        competition=competition,
        gender="male",
        role=role,
        balls=balls,
        runs=runs,
        wickets=wickets,
    )


def _line(match_id, day, venue, runs, balls, wickets=5, role="set", competition="ipl"):
    return MatchLine(
        match_id=match_id,
        innings=1,
        date=day,
        venue=venue,
        competition=competition,
        gender="male",
        role=role,
        balls=balls,
        runs=runs,
        wickets=wickets,
    )


def test_family_splits_t20_from_tests():
    assert family_of("ipl") == "t20"
    assert family_of("t20i") == "t20"
    assert family_of("odi") == "odi"
    assert family_of("test") == "test"


def test_test_innings_three_and_four_are_not_a_venue_factor():
    assert innings_role(None, 1, "test") == "set"
    assert innings_role(300, 2, "test") == "chase"
    assert innings_role(None, 3, "test") is None
    assert innings_role(200, 4, "test") is None


def test_shrink_phi_is_one_when_the_cell_is_empty():
    assert shrink_phi(1.20, 0, 600) == 1.0


def test_shrink_phi_moves_toward_the_raw_factor_as_balls_grow():
    thin = shrink_phi(1.20, 120, 600)
    thick = shrink_phi(1.20, 6000, 600)
    assert 1.0 < thin < thick < 1.20
    assert thick > 1.18


def test_loo_rate_does_not_let_todays_220_define_the_pitch():
    # Ten par innings at 148 SR (178 runs / 120 balls) plus one 220.
    cell_runs, cell_balls = 10 * 178 + 220, 11 * 120
    included = (cell_runs / cell_balls) * 100
    loo = loo_rate(cell_runs, cell_balls, 220, 120) * 100
    assert included > 150
    assert abs(loo - 148.333) < 0.01


def test_talent_times_park_matches_the_worked_ipl_shape():
    # League T20 SR 135, Wankhede 148 → φ ≈ 1.10; teammate baseline 139.3.
    assert abs(expected_sr(1.393, 1.10) - 153.23) < 0.01


def test_park_factor_refuses_a_three_innings_cell():
    cell = Totals(balls=360, runs=532, wickets=15, n_innings=3)
    league = Totals(balls=20000, runs=27000, wickets=800, n_innings=160)
    phi_r, phi_w, reason = park_factor(cell, league, n0=600, n_min=4)
    assert phi_r == 1.0
    assert "too few matches at these grounds" in reason


def test_expect_lines_is_leave_one_match_out():
    day = 738000  # arbitrary ordinal in-range
    # Eight other Wankhede set innings at 148 SR, plus today's 220, plus a
    # league pile at 135 so φ is identified.
    wankhede = [
        _env(f"w{i}", day - 10 * i, "Wankhede", 178, 120, wickets=6)
        for i in range(1, 9)
    ]
    today = _env("today", day, "Wankhede", 220, 120, wickets=4)
    league = [
        _env(f"l{i}", day - 7 * i, f"ground-{i}", 162, 120, wickets=6)
        for i in range(20)
    ]
    env = CellIndex.from_rows(wankhede + [today] + league)
    # Teammate talent away from Wankhede: SR 139.3 on 800 balls.
    talent_lines = [
        _line("away-a", day - 20, "Chepauk", 557, 400, wickets=16),
        _line("away-b", day - 40, "Eden", 557, 400, wickets=16),
    ]
    observed = [_line("today", day, "Wankhede", 162, 120, wickets=8)]
    exp = expect_lines(observed, {"today"}, env, TalentIndex(talent_lines + observed))
    assert exp.ok
    # φ uses the eight 148-SR innings, not today's 220.
    cell = env.window(("Wankhede", "ipl", "male", "set"), day, 730, "today")
    assert cell.n_innings == 8
    assert abs((cell.runs / cell.balls) * 100 - 148.333) < 0.01
    # Expected SR should sit near 139.3 × (148/135) after shrinkage, well above 135.
    assert exp.expected_sr > 145
    assert exp.expected_sr < 160


def test_empty_without_sample_has_a_pitch_residual_and_no_adj_delta():
    day = 738000
    rows = [_env(f"w{i}", day - 10 * i, "Wankhede", 178, 120) for i in range(1, 10)]
    rows += [_env(f"l{i}", day - 8 * i, f"g{i}", 162, 120) for i in range(24)]
    env = CellIndex.from_rows(rows)
    with_line = _line("m1", day, "Wankhede", 162, 120, wickets=8)
    away = [_line(f"a{i}", day - 15 * i, "Chepauk", 167, 120, wickets=6) for i in range(1, 8)]
    split = {
        "matches_with": 1,
        "matches_wo": 0,
        "bat": {
            "sr_with": 135.0,
            "sr_wo": None,
            "avg_with": 20.2,
            "avg_wo": None,
            "outs_with": 8,
            "outs_wo": 0,
        },
        "bowl": {},
    }
    attach_pitch(split, [with_line] + away, [], {"m1"}, ["m1"], env)
    assert split["pitch"]["ok_with"] is True
    assert split["pitch"]["ok_wo"] is False
    assert split["pitch"]["ok_adj"] is False
    assert split["bat"]["sr_exp_with"] is not None
    assert split["bat"]["sr_resid_with"] is not None
    assert split["bat"]["sr_delta_adj"] is None


def test_adj_delta_is_residual_minus_residual():
    day = 738000
    # Same park both sides, so the adj delta equals the raw residual difference.
    rows = [_env(f"w{i}", day - 10 * i, "Wankhede", 178, 120) for i in range(1, 10)]
    rows += [_env(f"l{i}", day - 8 * i, f"g{i}", 162, 120) for i in range(24)]
    env = CellIndex.from_rows(rows)
    with_line = _line("with", day, "Wankhede", 150, 120, wickets=8)
    wo_line = _line("wo", day - 5, "Wankhede", 180, 120, wickets=6)
    away = [_line(f"a{i}", day - 20 * i, "Chepauk", 167, 120, wickets=6) for i in range(1, 8)]
    split = {
        "matches_with": 1,
        "matches_wo": 1,
        "bat": {
            "sr_with": 125.0,
            "sr_wo": 150.0,
            "avg_with": 18.8,
            "avg_wo": 30.0,
            "outs_with": 8,
            "outs_wo": 6,
        },
        "bowl": {},
    }
    attach_pitch(split, [with_line, wo_line] + away, [], {"with"}, ["with", "wo"], env)
    assert split["pitch"]["ok_adj"] is True
    # With scored slower than the same pitch the without-sample faced.
    assert split["bat"]["sr_delta_adj"] < 0
    assert abs(
        split["bat"]["sr_delta_adj"]
        - (split["bat"]["sr_resid_with"] - split["bat"]["sr_resid_wo"])
    ) < 0.05
