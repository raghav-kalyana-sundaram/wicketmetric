"""Style-twin distance, calibration, and explanation — no warehouse required."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cricwarehouse.app.twin import (
    block_distance,
    calibrate_score,
    explain_match,
    format_kind,
    pair_distance,
    sample_median_distance,
    shrink_value,
    specs_for,
    zscore_frame,
)


def test_format_kind_splits_schemas():
    assert format_kind(["t20i", "ipl"]) == "t20"
    assert format_kind(["odi"]) == "odi"
    assert format_kind(["test"]) == "test"


def test_t20_and_test_feature_sets_differ():
    t20 = {s["key"] for s in specs_for("t20", "bat")}
    test = {s["key"] for s in specs_for("test", "bat")}
    assert "rel_sr" in t20
    assert "dot_pct" in t20
    assert "haz_1_20" in test
    assert "balls_per_out" in test
    assert "haz_1_20" not in t20
    assert "rel_sr" not in test


def test_style_mode_has_no_impact_weight():
    from cricwarehouse.app.twin import BLOCK_WEIGHTS

    assert BLOCK_WEIGHTS["style"]["impact"] == 0.0
    assert BLOCK_WEIGHTS["value"]["impact"] == 1.0


def test_zscore_does_not_impute():
    df = pd.DataFrame({"sr": [120.0, np.nan, 140.0]})
    out = zscore_frame(df, ["sr"])
    assert pd.isna(out.loc[1, "sr_z"])
    assert pd.notna(out.loc[0, "sr_z"])


def test_block_distance_skips_missing():
    a = pd.Series({"sr_z": 1.0, "dot_z": np.nan})
    b = pd.Series({"sr_z": 0.0, "dot_z": 2.0})
    assert block_distance(a, b, ["sr_z", "dot_z"]) == 1.0
    assert block_distance(a, b, ["dot_z"]) is None


def test_pair_distance_ignores_zero_weight_blocks():
    a = pd.Series({"role_z": 0.0, "impact_z": 10.0})
    b = pd.Series({"role_z": 0.0, "impact_z": 0.0})
    d, used = pair_distance(
        a,
        b,
        {"role": ["role_z"], "impact": ["impact_z"]},
        {"role": 1.0, "impact": 0.0},
    )
    assert d == 0.0
    assert used == 1


def test_calibration_puts_median_near_fifty():
    assert calibrate_score(1.0, 1.0) == 50.0
    assert calibrate_score(0.0, 1.0) == 100.0
    assert 24.0 < calibrate_score(2.0, 1.0) < 26.0


def test_sample_median_distance_is_positive():
    rng = np.random.default_rng(1)
    frame = pd.DataFrame(
        {
            "a_z": rng.normal(size=40),
            "b_z": rng.normal(size=40),
        }
    )
    med = sample_median_distance(frame, {"tempo": ["a_z", "b_z"]}, {"tempo": 1.0}, cap=40, rng=rng)
    assert med > 0


def test_shrink_moves_short_sample_toward_prior():
    assert shrink_value(200.0, 100.0, n=0, n0=10) == 100.0
    assert shrink_value(200.0, 100.0, n=10, n0=10) == 150.0
    assert shrink_value(None, 100.0, n=10, n0=10) is None


def test_explain_splits_match_and_diverge():
    a = pd.Series(dtype=float)
    b = pd.Series(dtype=float)
    specs = [
        {"key": "dot_pct", "label": "Dot %", "block": "method"},
        {"key": "entry_over", "label": "Entry over", "block": "role"},
        {"key": "six_pct", "label": "Six %", "block": "method"},
        {"key": "war", "label": "WAR", "block": "impact"},
    ]
    note = explain_match(
        a,
        b,
        {"dot_pct": 50, "entry_over": 48, "six_pct": 90, "war": 10},
        {"dot_pct": 52, "entry_over": 51, "six_pct": 20, "war": 80},
        specs,
    )
    labels_m = {row["label"] for row in note["matches"]}
    labels_d = {row["label"] for row in note["diverges"]}
    assert "Dot %" in labels_m
    assert "Six %" in labels_d
    assert "WAR" not in labels_m and "WAR" not in labels_d


def test_jayawardene_style_prefers_sangakkara_over_value_neighbours():
    from cricwarehouse.app.db import warehouse_ready
    from cricwarehouse.app.studio import profile_twin

    if not warehouse_ready():
        pytest.skip("Warehouse not built")
    d = profile_twin("Jayawardene", pool="t20i_ipl", mode="style")
    assert d.get("ok")
    names = [t["display_name"] for t in d.get("twins") or []]
    assert names, "expected neighbours"
    assert any("Sangakkara" in n for n in names)
    assert not any("Dussen" in n for n in names)
    assert (d["twins"][0]["match"] or 0) < 92
