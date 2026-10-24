import unittest
from app.synthetic import (EVENTS, MATCHES, generate_events, label, match_meta, minute_of, use_match)
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
        self.assertEqual(build_state(minute_of(71))["score"], {"home": 1, "away": 1})
        self.assertEqual(build_state(minute_of(72))["score"], {"home": 2, "away": 1})

    def test_goals_are_consistent(self):
        end = build_state(match_meta()["length"])
        self.assertEqual(end["score"], {
            t: len([e for e in EVENTS if e["team"] == t and e["is_goal"]])
            for t in ("home", "away")
        })
        self.assertTrue(end["is_synthetic"])

    def test_minutes_beyond_full_time_are_clamped(self):
        self.assertEqual(build_state(500)["minute"], match_meta()["length"])


class MatchesTests(unittest.TestCase):
    def test_every_match_has_its_scripted_result_at_the_right_minute(self):
        for match_id, spec in MATCHES.items():
            with self.subTest(match=match_id), use_match(match_id):
                goals = [e for e in EVENTS if e["is_goal"]]
                scripted = [s for s in spec.script if s[5] == "goal"]
                self.assertEqual(len(goals), len(scripted))
                self.assertEqual([e["label"] for e in goals], [f"{s[0]}'" for s in sorted(scripted)])

    def test_matches_are_different(self):
        firsts = []
        for match_id in MATCHES:
            with use_match(match_id):
                firsts.append(EVENTS[0]["player"])
        self.assertEqual(len(set(firsts)), len(MATCHES))

    def test_added_time_follows_the_stoppages(self):
        for match_id in MATCHES:
            with self.subTest(match=match_id), use_match(match_id):
                meta = match_meta()
                self.assertTrue(1 <= meta["added"][1] <= 7 and 2 <= meta["added"][2] <= 10)
                self.assertEqual(meta["length"], 90 + meta["added"][1] + meta["added"][2])
                # play goes into added time in both halves, and never past it
                first = [e for e in EVENTS if e["period"] == 1]
                self.assertTrue(any(e["label"].startswith("45+") for e in first))
                self.assertTrue(all(e["minute"] <= meta["length"] for e in EVENTS))
                self.assertEqual(label(meta["first_half"]), f"45+{meta['added'][1]}'")
                self.assertEqual(label(meta["length"]), f"90+{meta['added'][2]}'")
                self.assertEqual(label(minute_of(60)), "60'")

    def test_stoppages_and_substitutions_happen(self):
        for match_id in MATCHES:
            with self.subTest(match=match_id), use_match(match_id):
                subs = [e for e in EVENTS if e["type"] == "substitution"]
                self.assertTrue(6 <= len(subs) <= 10)
                self.assertTrue(all(e["period"] == 2 or e["clock"] == "45:00" for e in subs))
                stoppages = [e for e in EVENTS if e["type"] == "stoppage"]
                self.assertTrue(stoppages and all(e["duration_s"] > 0 for e in stoppages))

    def test_nobody_plays_after_being_substituted(self):
        for match_id in MATCHES:
            with self.subTest(match=match_id), use_match(match_id):
                off = {e["player"]: e["t"] for e in EVENTS if e["type"] == "substitution"}
                late = [e for e in EVENTS if e["player"] in off and e["t"] > off[e["player"]]]
                self.assertEqual(late, [])


# Per-match averages measured from 38 recent men's matches in StatsBomb Open Data (2023/24 Bundesliga and
# Euro 2024). Only these aggregate numbers are used for calibration; no real match data ships with MatchMind.
STATSBOMB_RECENT_AVERAGES = {
    "passes": 1076, "pass_pct": 84.6, "shots": 26.4, "xg": 2.8, "pressures": 297, "interceptions": 17.1,
    "tackles": 30.8, "fouls": 23.1, "possessions": 156.5, "saves": 6.2, "corners": 10.7, "cards": 4.1,
    "crosses": 22.8, "substitutions": 9.1, "injury_stoppages": 4.4, "clearances": 37.9, "dribbles": 25.6,
    "added_first_half": 2.3, "added_second_half": 4.9,
}


def per_match(match_id: str) -> dict:
    with use_match(match_id):
        passes = [e for e in EVENTS if e["type"] == "pass"]
        shots = [e for e in EVENTS if e["type"] == "shot"]
        count = lambda kind: sum(e["type"] == kind for e in EVENTS)  # noqa: E731
        return {
            "passes": len(passes), "pass_pct": 100 * sum(e["outcome"] == "complete" for e in passes) / len(passes),
            "shots": len(shots), "xg": sum(e["xg"] for e in shots), "pressures": count("pressure"),
            "interceptions": count("interception"), "tackles": count("tackle"), "fouls": count("foul"),
            "possessions": len({e["possession"] for e in EVENTS}), "saves": count("save"),
            "corners": sum(e["pass_type"] == "corner" for e in passes), "cards": count("card"),
            "crosses": sum(e["pass_type"] == "cross" for e in passes), "substitutions": count("substitution"),
            "injury_stoppages": sum(e["type"] == "stoppage" and e["outcome"] == "injury" for e in EVENTS),
            "clearances": count("clearance"), "dribbles": count("dribble"),
            "added_first_half": match_meta()["added"][1], "added_second_half": match_meta()["added"][2],
        }


class RealismTests(unittest.TestCase):
    def test_simulated_matches_are_close_to_recent_real_averages(self):
        matches = [per_match(m) for m in MATCHES]
        for stat, real in STATSBOMB_RECENT_AVERAGES.items():
            ours = sum(m[stat] for m in matches) / len(matches)
            with self.subTest(stat=stat):
                self.assertLess(abs(ours - real) / real, 0.40, f"{stat}: ours {ours:.1f}, real {real}")


class ExportTests(unittest.TestCase):
    def test_data_files_match_the_simulator(self):
        """data/ is what judges and teammates open; it must be the matches the app actually uses."""
        import csv
        import json
        from app.export import DATA_DIR, match_json
        for match_id in MATCHES:
            with self.subTest(match=match_id), use_match(match_id):
                with open(DATA_DIR / f"{match_id}.json", encoding="utf-8") as f:
                    self.assertEqual(json.load(f), json.loads(json.dumps(match_json())),
                                     "data/ is stale: run `python -m app.export` from backend/")
                with open(DATA_DIR / f"{match_id}.csv", encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual([r["id"] for r in rows], [e["id"] for e in EVENTS])


if __name__ == "__main__":
    unittest.main()
