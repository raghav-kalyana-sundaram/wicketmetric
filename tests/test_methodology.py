"""Deterministic clocks and attribution from the T20 methodology fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from cricwarehouse.app.ledger import attach_batter_state, attach_chase_state, attach_clocks
from cricwarehouse.app.parse import parse_match_file
from cricwarehouse.competitions import classify_match
from cricwarehouse.laws import dismissal_effect

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "335985_over5.json"
IPL = ROOT / "ipl_json-1"


def _path(match_id: str) -> Path:
    return IPL / f"{match_id}.json"


def _require(match_id: str) -> Path:
    path = _path(match_id)
    if not path.exists():
        pytest.skip(f"IPL dump not present locally: {path.name}")
    return path


def _frame(parsed: dict) -> pd.DataFrame:
    df = pd.DataFrame(parsed["deliveries"])
    match = parsed["match"]
    inn = {(row["match_id"], row["innings"]): row for row in parsed["innings"]}
    bpo = int(match.get("balls_per_over") or 6)
    sched = float(match.get("scheduled_overs") or 20)
    df["start_date"] = match.get("start_date")
    df["balls_per_over"] = bpo
    df["sched_overs"] = sched
    df["sched_balls"] = int(round(sched * bpo))
    df["target_runs"] = [
        inn[(mid, innings)].get("target_runs")
        for mid, innings in zip(df["match_id"], df["innings"])
    ]
    return attach_batter_state(attach_chase_state(attach_clocks(df)))


def test_t20_universe_filter_accepts_attached_fixtures(ipl_2008_paths):
    for path in ipl_2008_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        info = data["info"]
        assert classify_match(info, "IPL") == "ipl"
        assert info["match_type"] == "T20"
        assert info.get("gender")
        assert info.get("balls_per_over") == 6


def test_target_runs_is_score_required_to_win(ipl_2008_paths):
    for path in ipl_2008_paths:
        parsed = parse_match_file(path, readme_code="IPL")
        first = next(i for i in parsed["innings"] if i["innings"] == 1)
        chase = next(i for i in parsed["innings"] if i["innings"] == 2)
        assert chase["target_runs"] == first["runs"] + 1


def test_worked_example_over_five_clocks():
    parsed = parse_match_file(_require("335985"), readme_code="IPL")
    df = _frame(parsed)
    gold = json.loads(GOLDEN.read_text(encoding="utf-8"))
    first = df[df["innings"] == 1].reset_index(drop=True)
    over = first[first["over"] == 5].reset_index(drop=True)
    assert len(over) == 6
    enter = over.iloc[0]
    assert int(enter["u_before"]) == gold["enter_over"]["valid_balls_before"]
    assert int(enter["b_before"]) == gold["enter_over"]["pre"][0]
    assert int(enter["w_before"]) == gold["enter_over"]["pre"][1]
    for row, expected in zip(over.itertuples(index=False), gold["deliveries"]):
        assert int(row.b_before) == expected["b_before"]
        assert int(row.w_before) == expected["w_before"]
        assert int(row.l_valid) == expected["L"]
        assert int(row.f_opp) == expected["F"]
        assert int(row.runs_total) == expected["r_team"]
        assert int(row.runs_batter) == expected["r_bat"]
        assert int(row.d_team) == expected["d_team"]
        assert int(row.d_bat) == expected["d_bat"]
        assert int(row.d_bowl) == expected["d_bowl"]
        assert int(row.b_after) == expected["b_after"]
        assert int(row.w_after) == expected["w_after"]
        if expected.get("kind"):
            assert str(row.wicket_kind).lower() == expected["kind"]


def test_retired_hurt_consumes_no_team_wicket():
    parsed = parse_match_file(_require("335985"), readme_code="IPL")
    first = [d for d in parsed["deliveries"] if d["innings"] == 1]
    hurt = next(d for d in first if d["over"] == 3 and str(d.get("wicket_kind") or "").lower() == "retired hurt")
    assert hurt["d_team"] == 0
    assert hurt["d_bat"] == 0
    assert hurt["d_bowl"] == 0
    assert dismissal_effect("retired hurt") == (0, 0, 0)
    df = _frame(parsed)
    terminal = df[(df["innings"] == 1)].iloc[-1]
    entries = sum(1 for d in first if d.get("wicket_kind"))
    assert entries == 7
    assert int(terminal["w_after"]) == 4


def test_run_out_fielder_bowler_gets_no_wicket_credit():
    parsed = parse_match_file(_require("335985"), readme_code="IPL")
    ball = next(
        d
        for d in parsed["deliveries"]
        if d["innings"] == 1 and d["over"] == 5 and str(d.get("wicket_kind") or "").lower() == "run out"
    )
    assert ball["d_team"] == 1
    assert ball["d_bat"] == 1
    assert ball["d_bowl"] == 0
    assert ball["player_out"] == ball["striker"]


def test_derived_free_hits_follow_no_balls():
    parsed = parse_match_file(_require("335987"), readme_code="IPL")
    df = _frame(parsed)
    chase = df[df["innings"] == 2].reset_index(drop=True)
    noballs = chase.index[chase["is_noball"].astype(bool)].tolist()
    assert len(noballs) >= 4
    for i in noballs:
        nxt = i + 1
        while nxt < len(chase) and int(chase.iloc[nxt]["l_valid"]) == 0 and not bool(chase.iloc[nxt]["is_noball"]):
            nxt += 1
        if nxt < len(chase):
            assert bool(chase.iloc[nxt]["free_hit"])
    assert int(chase["free_hit"].sum()) >= 4
    assert bool(chase["fh_approx"].all())


def test_chase_overshoot_is_capped():
    parsed = parse_match_file(_require("335987"), readme_code="IPL")
    df = _frame(parsed)
    chase = df[df["innings"] == 2]
    inn = next(i for i in parsed["innings"] if i["innings"] == 2)
    need_start = float(chase.iloc[0]["need_before"])
    assert need_start == inn["target_runs"]
    assert float(chase["runs_capped"].sum()) == need_start
    assert float(chase["runs_total"].sum()) == need_start + 1


def test_all_out_first_innings_is_complete():
    parsed = parse_match_file(_require("335986"), readme_code="IPL")
    first = next(i for i in parsed["innings"] if i["innings"] == 1)
    assert first["all_out"] is True
    assert first["legal_balls"] == 112
    assert first["runs"] == 110
