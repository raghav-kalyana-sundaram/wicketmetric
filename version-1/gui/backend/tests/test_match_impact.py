"""Sanity checks for scorecard match impact (parity with frontend scorecardMatchImpact)."""

import unittest

from match_impact import MIN_BALLS_BAT_IMPACT, compute_match_impact_combined_rows


class TestMatchImpact(unittest.TestCase):
    def test_batting_impact_runs_squared_over_balls(self):
        innings = {
            "1": {
                "batting": [
                    {
                        "batter_id": "p1",
                        "batter": "A",
                        "runs": 50,
                        "balls": 25,
                    }
                ],
                "bowling": [],
            }
        }
        rows = compute_match_impact_combined_rows(innings)
        p1 = next(r for r in rows if r["player_id"] == "p1")
        self.assertEqual(p1["bat_runs"], 50)
        self.assertEqual(p1["bat_balls"], 25)
        self.assertEqual(p1["bat_impact"], 100.0)
        self.assertEqual(p1["total_impact"], 100.0)

    def test_below_min_bat_balls_excluded(self):
        innings = {
            "1": {
                "batting": [
                    {
                        "batter_id": "p1",
                        "batter": "A",
                        "runs": 20,
                        "balls": MIN_BALLS_BAT_IMPACT - 1,
                    }
                ],
                "bowling": [],
            }
        }
        rows = compute_match_impact_combined_rows(innings)
        self.assertFalse(any(r["player_id"] == "p1" for r in rows))


if __name__ == "__main__":
    unittest.main()
