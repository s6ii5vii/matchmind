import unittest
from app.synthetic import EVENTS, generate_events
from app.analysis import build_state


class MatchMindTests(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(EVENTS, generate_events())

    def test_no_future_leakage(self):
        before = build_state(10)
        self.assertEqual(before["score"], {"home": 0, "away": 0})
        self.assertTrue(all(e["minute"] <= 10 for e in before["recent_events"]))
        self.assertEqual(before["goal_events"], [])

    def test_goal_timeline(self):
        self.assertEqual(build_state(18)["score"], {"home": 1, "away": 0})
        self.assertEqual(build_state(42)["score"], {"home": 1, "away": 1})
        self.assertEqual(build_state(72)["score"], {"home": 2, "away": 1})

    def test_goals_are_consistent(self):
        end = build_state(90)
        self.assertEqual(end["score"], {
            t: len([e for e in EVENTS if e["team"] == t and e["is_goal"]])
            for t in ("home", "away")
        })
        self.assertTrue(end["is_synthetic"])

    def test_valid_evidence(self):
        end = build_state(70, "analyst")
        ids = {e["id"] for e in EVENTS if e["minute"] <= 70}
        for insight in end["insights"]:
            self.assertTrue(set(insight["evidence_ids"]).issubset(ids))


# Per-match averages measured from 20 matches of StatsBomb Open Data (Premier League 2015/16).
# Only these aggregate numbers are used for calibration; no real match data ships with MatchMind.
STATSBOMB_PL_AVERAGES = {"shots": 24.6, "xg": 2.2, "pass_pct": 76.3, "pressures": 305.5,
                         "interceptions": 25.1, "tackles": 41.9, "fouls": 25.2, "possessions": 183.1}


class RealismTests(unittest.TestCase):
    def test_simulated_match_is_close_to_real_match_averages(self):
        passes = [e for e in EVENTS if e["type"] == "pass"]
        shots = [e for e in EVENTS if e["type"] == "shot"]
        ours = {
            "shots": len(shots), "xg": sum(e["xg"] for e in shots),
            "pass_pct": 100 * sum(e["outcome"] == "complete" for e in passes) / len(passes),
            "pressures": sum(e["type"] == "pressure" for e in EVENTS),
            "interceptions": sum(e["type"] == "interception" for e in EVENTS),
            "tackles": sum(e["type"] == "tackle" for e in EVENTS),
            "fouls": sum(e["type"] == "foul" for e in EVENTS),
            "possessions": len({e["possession"] for e in EVENTS}),
        }
        for stat, real in STATSBOMB_PL_AVERAGES.items():
            with self.subTest(stat=stat):
                self.assertLess(abs(ours[stat] - real) / real, 0.40, f"{stat}: ours {ours[stat]:.1f}, real {real}")


class ExportTests(unittest.TestCase):
    def test_data_files_match_the_simulator(self):
        """data/ is what judges and teammates open; it must be the match the app actually uses."""
        import csv
        import json
        from app.export import DATA_DIR, match_json
        with open(DATA_DIR / "match.json") as f:
            self.assertEqual(json.load(f), json.loads(json.dumps(match_json())),
                             "data/ is stale: run `python -m app.export` from backend/")
        with open(DATA_DIR / "match_events.csv") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([r["id"] for r in rows], [e["id"] for e in EVENTS])


if __name__ == "__main__":
    unittest.main()
