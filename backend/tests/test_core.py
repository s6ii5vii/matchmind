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


if __name__ == "__main__":
    unittest.main()
