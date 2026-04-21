"""
Unit tests for the config module: loading, merging, dot-notation access,
defaults, YAML override, and cache behaviour.
"""

import os
import sys
import tempfile

import pytest
import yaml

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import (
    _DEFAULTS,
    Config,
    _deep_merge,
    cfg,
    get_config,
    reload_config,
    reset_to_defaults,
)

# ===========================================================================
# Config class — dot-notation access
# ===========================================================================


class TestConfigAccess:
    """Tests for the Config wrapper's get/contains/repr methods."""

    def test_get_simple_key(self):
        c = Config({"a": 1, "b": 2})
        assert c.get("a") == 1
        assert c.get("b") == 2

    def test_get_nested_key(self):
        c = Config({"a": {"b": {"c": 42}}})
        assert c.get("a.b.c") == 42

    def test_get_returns_dict_for_intermediate_key(self):
        c = Config({"a": {"b": 1, "c": 2}})
        result = c.get("a")
        assert isinstance(result, dict)
        assert result == {"b": 1, "c": 2}

    def test_get_missing_key_raises_keyerror(self):
        c = Config({"a": 1})
        with pytest.raises(KeyError, match="nonexistent"):
            c.get("nonexistent")

    def test_get_missing_nested_key_raises_keyerror(self):
        c = Config({"a": {"b": 1}})
        with pytest.raises(KeyError):
            c.get("a.z")

    def test_get_deeply_missing_key_raises_keyerror(self):
        c = Config({"a": {"b": 1}})
        with pytest.raises(KeyError):
            c.get("a.b.c.d")

    def test_get_with_default(self):
        c = Config({"a": 1})
        assert c.get("missing", default=99) == 99

    def test_get_nested_with_default(self):
        c = Config({"a": {"b": 1}})
        assert c.get("a.z.w", default="fallback") == "fallback"

    def test_get_default_none(self):
        """Explicit None as default should be returned, not raise."""
        c = Config({"a": 1})
        assert c.get("missing", default=None) is None

    def test_get_default_false(self):
        """Falsy default values should be returned correctly."""
        c = Config({"a": 1})
        assert c.get("missing", default=0) == 0
        assert c.get("missing", default=False) is False
        assert c.get("missing", default="") == ""

    def test_getitem(self):
        c = Config({"x": {"y": 10}})
        assert c["x"] == {"y": 10}

    def test_getitem_missing_raises(self):
        c = Config({"a": 1})
        with pytest.raises(KeyError):
            _ = c["b"]

    def test_contains(self):
        c = Config({"a": 1, "b": 2})
        assert "a" in c
        assert "b" in c
        assert "c" not in c

    def test_data_property_returns_copy(self):
        c = Config({"a": 1})
        d = c.data
        d["a"] = 999
        assert c.get("a") == 1  # original unmodified

    def test_repr(self):
        c = Config({"alpha": 1, "beta": 2})
        r = repr(c)
        assert "alpha" in r
        assert "beta" in r
        assert "Config" in r


# ===========================================================================
# Deep merge
# ===========================================================================


class TestDeepMerge:
    """Tests for the _deep_merge helper."""

    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        assert _deep_merge(base, override) == {"a": 1, "b": 99}

    def test_nested_override(self):
        base = {"a": {"b": 1, "c": 2}, "d": 3}
        override = {"a": {"b": 99}}
        result = _deep_merge(base, override)
        assert result == {"a": {"b": 99, "c": 2}, "d": 3}

    def test_add_new_key(self):
        base = {"a": 1}
        override = {"b": 2}
        assert _deep_merge(base, override) == {"a": 1, "b": 2}

    def test_add_new_nested_key(self):
        base = {"a": {"b": 1}}
        override = {"a": {"c": 2}}
        assert _deep_merge(base, override) == {"a": {"b": 1, "c": 2}}

    def test_override_dict_with_scalar(self):
        """If user overrides a dict with a scalar, the scalar wins."""
        base = {"a": {"b": 1}}
        override = {"a": "flat"}
        assert _deep_merge(base, override) == {"a": "flat"}

    def test_override_scalar_with_dict(self):
        """If user overrides a scalar with a dict, the dict wins."""
        base = {"a": 1}
        override = {"a": {"b": 2}}
        assert _deep_merge(base, override) == {"a": {"b": 2}}

    def test_does_not_mutate_base(self):
        base = {"a": {"b": 1}}
        override = {"a": {"c": 2}}
        _deep_merge(base, override)
        assert base == {"a": {"b": 1}}

    def test_does_not_mutate_override(self):
        base = {"a": 1}
        override = {"a": 2, "b": 3}
        _deep_merge(base, override)
        assert override == {"a": 2, "b": 3}

    def test_empty_base(self):
        assert _deep_merge({}, {"a": 1}) == {"a": 1}

    def test_empty_override(self):
        assert _deep_merge({"a": 1}, {}) == {"a": 1}

    def test_both_empty(self):
        assert _deep_merge({}, {}) == {}

    def test_deeply_nested(self):
        base = {"a": {"b": {"c": {"d": 1}}}}
        override = {"a": {"b": {"c": {"d": 2, "e": 3}}}}
        result = _deep_merge(base, override)
        assert result == {"a": {"b": {"c": {"d": 2, "e": 3}}}}


# ===========================================================================
# Defaults
# ===========================================================================


class TestDefaults:
    """Tests that _DEFAULTS contains all required sections with sensible values."""

    EXPECTED_SECTIONS = [
        "pipeline",
        "rating",
        "batting_acceleration_weights",
        "batting_power_weights",
        "batting_control_weights",
        "batting_avg_quality",
        "batting_volume",
        "bowling_accuracy_weights",
        "bowling_control_weights",
        "bowling_threat_weights",
        "bowling_volume",
        "wicket_quality",
        "opposition_quality",
        "team_quality",
        "icc_ranking",
        "recency",
        "batting_dot_penalty_phase_weights",
        "player_aliases",
        "player_name_overrides",
        "duplicate_detection",
    ]

    def test_all_sections_present(self):
        for section in self.EXPECTED_SECTIONS:
            assert section in _DEFAULTS, f"Missing default section: {section}"

    def test_pipeline_thresholds_are_positive(self):
        p = _DEFAULTS["pipeline"]
        assert p["min_bat_innings"] > 0
        assert p["min_bowl_overs"] > 0
        assert p["min_phase_balls_batting"] > 0
        assert p["min_phase_balls_bowling"] > 0

    def test_rating_defaults(self):
        r = _DEFAULTS["rating"]
        assert r["shrinkage_k_bat"] > 0
        assert r["shrinkage_k_bowl"] > 0
        assert 0 < r["confidence_alpha"] < 1
        assert r["confidence_reference_n"] > 0

    def test_batting_weight_dicts_sum_to_one(self):
        for key in [
            "batting_acceleration_weights",
            "batting_power_weights",
            "batting_control_weights",
        ]:
            total = sum(_DEFAULTS[key].values())
            assert abs(total - 1.0) < 1e-6, f"{key} sums to {total}, not 1.0"

    def test_bowling_weight_dicts_sum_to_one(self):
        for key in [
            "bowling_accuracy_weights",
            "bowling_control_weights",
            "bowling_threat_weights",
        ]:
            total = sum(_DEFAULTS[key].values())
            assert abs(total - 1.0) < 1e-6, f"{key} sums to {total}, not 1.0"

    def test_recency_defaults(self):
        r = _DEFAULTS["recency"]
        assert isinstance(r["enabled"], bool)
        assert r["half_life_days"] > 0
        assert 0 < r["min_weight"] < 1

    def test_volume_defaults_have_required_keys(self):
        for section in ["batting_volume", "bowling_volume"]:
            v = _DEFAULTS[section]
            assert "base" in v
            assert "ref" in v
            assert "curve" in v
            assert 0 < v["base"] < 1
            assert v["ref"] > 0
            assert v["curve"] > 0

    def test_wicket_quality_positions_cover_1_to_11(self):
        positions = _DEFAULTS["wicket_quality"]["position_weights"]
        for pos in range(1, 12):
            assert pos in positions, f"Missing position {pos}"
            assert positions[pos] > 0

    def test_opposition_quality_defaults(self):
        oq = _DEFAULTS["opposition_quality"]
        assert oq["scale"] > 0
        assert oq["clip"] > 0

    def test_team_quality_defaults(self):
        tq = _DEFAULTS["team_quality"]
        assert tq["scale"] > 0
        assert tq["clip"] > 0

    def test_icc_ranking_defaults(self):
        icc = _DEFAULTS["icc_ranking"]
        assert isinstance(icc["enabled"], bool)
        assert 0.0 < icc["floor"] < 1.0
        assert icc["ceiling"] > 1.0
        assert icc["curve"] > 0
        assert icc["max_rating"] > 0
        assert icc["default_rating"] >= 0
        assert isinstance(icc["ratings"], dict)
        # Should contain major cricket nations
        assert "India" in icc["ratings"]
        assert "Australia" in icc["ratings"]
        assert "England" in icc["ratings"]
        # India should have the highest rating (max_rating)
        assert icc["ratings"]["India"] == icc["max_rating"]
        # All ratings should be non-negative integers
        for team, rating in icc["ratings"].items():
            assert isinstance(rating, int), f"{team} rating is not int"
            assert rating >= 0, f"{team} has negative rating"

    def test_player_aliases_is_dict(self):
        assert isinstance(_DEFAULTS["player_aliases"], dict)

    def test_player_name_overrides_is_dict(self):
        assert isinstance(_DEFAULTS["player_name_overrides"], dict)

    def test_avg_quality_defaults(self):
        aq = _DEFAULTS["batting_avg_quality"]
        assert aq["reference"] > 0
        assert aq["exponent_below"] > 0
        assert aq["exponent_above"] > 0
        assert 0 < aq["floor"] < 1
        assert aq["ceil"] > 1
        assert 0 < aq["gate_base"] < 1
        assert aq["gate_ref"] > 0
        assert 0 < aq["ctrl_gate_base"] < 1
        assert aq["ctrl_gate_ref"] > 0


# ===========================================================================
# YAML loading
# ===========================================================================


class TestYAMLLoading:
    """Tests for loading config from YAML files."""

    def test_load_nonexistent_file_uses_defaults(self):
        c = reload_config("/tmp/__nonexistent_cricket_config_xyz.yaml")
        assert c.get("recency.half_life_days") == 730
        assert c.get("pipeline.min_bat_innings") == 10

    def test_load_empty_yaml_uses_defaults(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            path = f.name

        try:
            c = reload_config(path)
            assert c.get("recency.half_life_days") == 730
        finally:
            os.unlink(path)

    def test_load_partial_yaml_merges_with_defaults(self):
        """A YAML file that only overrides recency should keep all other defaults."""
        override = {"recency": {"half_life_days": 365}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(override, f)
            path = f.name

        try:
            c = reload_config(path)
            assert c.get("recency.half_life_days") == 365
            # Other recency keys should still have defaults
            assert c.get("recency.enabled") is True
            assert c.get("recency.min_weight") == 0.05
            # Other sections should be untouched
            assert c.get("pipeline.min_bat_innings") == 10
            assert c.get("rating.shrinkage_k_bat") == 12.0
        finally:
            os.unlink(path)

    def test_load_full_override(self):
        override = {
            "pipeline": {"min_bat_innings": 20},
            "recency": {"enabled": False, "half_life_days": 500, "min_weight": 0.1},
            "batting_volume": {"base": 0.90, "ref": 30.0, "curve": 0.5},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(override, f)
            path = f.name

        try:
            c = reload_config(path)
            assert c.get("pipeline.min_bat_innings") == 20
            assert c.get("recency.enabled") is False
            assert c.get("recency.half_life_days") == 500
            assert c.get("recency.min_weight") == 0.1
            assert c.get("batting_volume.base") == 0.90
            assert c.get("batting_volume.ref") == 30.0
            # Default sections should still exist
            assert "batting_acceleration_weights" in c
        finally:
            os.unlink(path)

    def test_override_weight_dict(self):
        """Overriding a weight dict merges with defaults; all keys must be
        provided (or their default weights accepted) to keep sum == 1.0."""
        override = {
            "batting_acceleration_weights": {
                "overall_sr": 0.30,
                "sr_growth": 0.15,
                "death_sr": 0.10,
                "impact": 0.10,
                "runs_above_expected": 0.15,
                "leveraged_rva": 0.20,
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(override, f)
            path = f.name

        try:
            c = reload_config(path)
            w = c.get("batting_acceleration_weights")
            assert w["overall_sr"] == 0.30
            assert abs(sum(w.values()) - 1.0) < 1e-6
        finally:
            os.unlink(path)

    def test_player_aliases_from_yaml(self):
        override = {
            "player_aliases": {"abc123": "def456", "ghi789": "def456"},
            "player_name_overrides": {"def456": "Rohit Sharma"},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(override, f)
            path = f.name

        try:
            c = reload_config(path)
            aliases = c.get("player_aliases")
            assert aliases["abc123"] == "def456"
            assert aliases["ghi789"] == "def456"
            names = c.get("player_name_overrides")
            assert names["def456"] == "Rohit Sharma"
        finally:
            os.unlink(path)


# ===========================================================================
# Caching
# ===========================================================================


class TestCaching:
    """Tests for the config caching mechanism."""

    def test_get_config_returns_same_object_on_repeated_calls(self):
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

    def test_reload_clears_cache(self):
        c1 = get_config()
        c2 = reload_config()
        # After reload, object should be different (new instance)
        assert c1 is not c2

    def test_reset_to_defaults_works(self):
        c = reset_to_defaults()
        assert c.get("recency.half_life_days") == 730
        assert c.get("pipeline.min_bat_innings") == 10

    def test_reload_with_different_path_changes_values(self):
        override = {"recency": {"half_life_days": 999}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(override, f)
            path = f.name

        try:
            c1 = reload_config()
            c2 = reload_config(path)
            assert c2.get("recency.half_life_days") == 999
        finally:
            os.unlink(path)
            # Reset to not affect other tests
            reload_config()


# ===========================================================================
# Module-level cfg() convenience function
# ===========================================================================


class TestCfgFunction:
    """Tests for the module-level cfg() shortcut."""

    def test_cfg_reads_default_values(self):
        # Ensure we're using defaults
        reload_config()
        assert cfg("recency.half_life_days") == 545
        assert cfg("pipeline.min_bat_innings") == 10

    def test_cfg_with_default_kwarg(self):
        assert cfg("completely.nonexistent.key", default=42) == 42

    def test_cfg_raises_without_default(self):
        with pytest.raises(KeyError):
            cfg("completely.nonexistent.key")

    def test_cfg_returns_dict_for_section(self):
        result = cfg("batting_acceleration_weights")
        assert isinstance(result, dict)
        assert "overall_sr" in result

    def test_cfg_returns_correct_types(self):
        assert isinstance(cfg("recency.enabled"), bool)
        assert isinstance(cfg("recency.half_life_days"), (int, float))
        assert isinstance(cfg("recency.min_weight"), float)
        assert isinstance(cfg("player_aliases"), dict)


# ===========================================================================
# Integration: config values match what modules actually use
# ===========================================================================


class TestConfigIntegration:
    """Verify that config values match what the batting/bowling modules read."""

    def test_batting_min_phase_balls_from_config(self):
        from src.batting import MIN_PHASE_BALLS

        expected = cfg("pipeline.min_phase_balls_batting", default=4)
        assert MIN_PHASE_BALLS == expected

    def test_bowling_min_phase_balls_from_config(self):
        from src.bowling import MIN_PHASE_BALLS

        expected = cfg("pipeline.min_phase_balls_bowling", default=6)
        assert MIN_PHASE_BALLS == expected

    def test_batting_recency_constants_from_config(self):
        from src.batting import (
            RECENCY_ENABLED,
            RECENCY_HALF_LIFE_DAYS,
            RECENCY_MIN_WEIGHT,
        )

        assert RECENCY_ENABLED == cfg("recency.enabled", default=True)
        assert RECENCY_HALF_LIFE_DAYS == cfg("recency.half_life_days", default=730.0)
        assert RECENCY_MIN_WEIGHT == cfg("recency.min_weight", default=0.05)

    def test_bowling_recency_constants_from_config(self):
        from src.bowling import (
            RECENCY_ENABLED,
            RECENCY_HALF_LIFE_DAYS,
            RECENCY_MIN_WEIGHT,
        )

        assert RECENCY_ENABLED == cfg("recency.enabled", default=True)
        assert RECENCY_HALF_LIFE_DAYS == cfg("recency.half_life_days", default=730.0)
        assert RECENCY_MIN_WEIGHT == cfg("recency.min_weight", default=0.05)

    def test_batting_acc_weights_from_config(self):
        from src.batting import ACC_WEIGHTS

        expected = cfg("batting_acceleration_weights")
        assert ACC_WEIGHTS == expected

    def test_batting_pow_weights_from_config(self):
        from src.batting import POW_WEIGHTS

        expected = cfg("batting_power_weights")
        assert POW_WEIGHTS == expected

    def test_batting_ctrl_weights_from_config(self):
        from src.batting import CTRL_WEIGHTS

        expected = cfg("batting_control_weights")
        assert CTRL_WEIGHTS == expected

    def test_bowling_acc_weights_from_config(self):
        from src.bowling import ACC_WEIGHTS

        expected = cfg("bowling_accuracy_weights")
        assert ACC_WEIGHTS == expected

    def test_bowling_ctrl_weights_from_config(self):
        from src.bowling import CTRL_WEIGHTS

        expected = cfg("bowling_control_weights")
        assert CTRL_WEIGHTS == expected

    def test_bowling_threat_weights_from_config(self):
        from src.bowling import THREAT_WEIGHTS

        expected = cfg("bowling_threat_weights")
        assert THREAT_WEIGHTS == expected

    def test_batting_volume_constants_from_config(self):
        from src.batting import VOLUME_BASE, VOLUME_CURVE, VOLUME_REF

        assert VOLUME_BASE == cfg("batting_volume.base")
        assert VOLUME_REF == cfg("batting_volume.ref")
        assert VOLUME_CURVE == cfg("batting_volume.curve")

    def test_bowling_volume_constants_from_config(self):
        from src.bowling import BOWL_VOLUME_BASE, BOWL_VOLUME_CURVE, BOWL_VOLUME_REF

        assert BOWL_VOLUME_BASE == cfg("bowling_volume.base")
        assert BOWL_VOLUME_REF == cfg("bowling_volume.ref")
        assert BOWL_VOLUME_CURVE == cfg("bowling_volume.curve")

    def test_avg_quality_constants_from_config(self):
        from src.batting import (
            AVG_GATE_BASE,
            AVG_GATE_REF,
            AVG_QUALITY_CEIL,
            AVG_QUALITY_EXPONENT_ABOVE,
            AVG_QUALITY_EXPONENT_BELOW,
            AVG_QUALITY_FLOOR,
            AVG_QUALITY_REFERENCE,
            CTRL_AVG_GATE_BASE,
            CTRL_AVG_GATE_REF,
        )

        assert AVG_QUALITY_REFERENCE == cfg("batting_avg_quality.reference")
        assert AVG_QUALITY_EXPONENT_BELOW == cfg("batting_avg_quality.exponent_below")
        assert AVG_QUALITY_EXPONENT_ABOVE == cfg("batting_avg_quality.exponent_above")
        assert AVG_QUALITY_FLOOR == cfg("batting_avg_quality.floor")
        assert AVG_QUALITY_CEIL == cfg("batting_avg_quality.ceil")
        assert AVG_GATE_BASE == cfg("batting_avg_quality.gate_base")
        assert AVG_GATE_REF == cfg("batting_avg_quality.gate_ref")
        assert CTRL_AVG_GATE_BASE == cfg("batting_avg_quality.ctrl_gate_base")
        assert CTRL_AVG_GATE_REF == cfg("batting_avg_quality.ctrl_gate_ref")

    def test_opposition_quality_constants_from_config(self):
        from src.batting import OPP_QUALITY_CLIP, OPP_QUALITY_SCALE

        assert OPP_QUALITY_SCALE == cfg("opposition_quality.scale")
        assert OPP_QUALITY_CLIP == cfg("opposition_quality.clip")

    def test_team_quality_constants_from_config(self):
        from src.batting import TEAM_QUALITY_CLIP, TEAM_QUALITY_SCALE

        assert TEAM_QUALITY_SCALE == cfg("team_quality.scale")
        assert TEAM_QUALITY_CLIP == cfg("team_quality.clip")

    def test_icc_ranking_constants_from_config(self):
        from src.batting import (
            ICC_RANKING_CEILING,
            ICC_RANKING_CURVE,
            ICC_RANKING_DEFAULT_RATING,
            ICC_RANKING_ENABLED,
            ICC_RANKING_FLOOR,
            ICC_RANKING_MAX_RATING,
            ICC_RANKING_RATINGS,
        )

        assert ICC_RANKING_ENABLED == cfg("icc_ranking.enabled")
        assert ICC_RANKING_FLOOR == cfg("icc_ranking.floor")
        assert ICC_RANKING_CEILING == cfg("icc_ranking.ceiling")
        assert ICC_RANKING_CURVE == cfg("icc_ranking.curve")
        assert ICC_RANKING_MAX_RATING == cfg("icc_ranking.max_rating")
        assert ICC_RANKING_DEFAULT_RATING == cfg("icc_ranking.default_rating")
        assert isinstance(ICC_RANKING_RATINGS, dict)
        assert "India" in ICC_RANKING_RATINGS

    def test_wicket_position_weights_from_config(self):
        from src.batting import WICKET_POSITION_DEFAULT, WICKET_POSITION_WEIGHTS

        raw = cfg("wicket_quality.position_weights")
        expected = {int(k): float(v) for k, v in raw.items()}
        assert WICKET_POSITION_WEIGHTS == expected
        assert WICKET_POSITION_DEFAULT == cfg("wicket_quality.default_weight")
