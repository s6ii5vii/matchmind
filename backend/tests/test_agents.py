import asyncio
import json
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app.agents import run_analysis
from app.agents.llm import configured_provider, model_client, ungrounded_numbers
from app.agents.models import Claim, Job
from app.agents.tools import verify_claim, window_stats
from app.main import app
from app.moments import key_moments
from app.players import compare, ranking
from app.synthetic import EVENTS, MATCHES, match_meta, minute_of, tidy, use_match


NOW = minute_of(75)  # 75' on the clock: Northbridge's pressing spell
START = minute_of(66)


def claim(**overrides) -> Claim:
    base = dict(id="T1", team="home", metric="pressures", start=START, end=NOW,
                value=window_stats("home", START, NOW)["pressures"], relation="more", compare="opponent",
                text="Northbridge City is out-pressing Riverside United")
    return Claim(**{**base, **overrides})


class SkepticTests(unittest.TestCase):
    def test_verifies_true_claim(self):
        self.assertEqual(verify_claim(claim(), NOW).verdict, "verified")

    def test_rejects_future_window(self):
        result = verify_claim(claim(end=NOW + 5), NOW)
        self.assertEqual(result.verdict, "rejected")
        self.assertIn("only at", result.reason)

    def test_rejects_false_direction(self):
        self.assertEqual(verify_claim(claim(team="away"), NOW).verdict, "rejected")

    def test_corrects_wrong_number_and_bad_evidence(self):
        away_shot = next(e["id"] for e in EVENTS if e["team"] == "away" and e["type"] == "shot")
        result = verify_claim(claim(value=99, evidence_ids=[away_shot]), NOW)
        self.assertEqual(result.verdict, "corrected")
        self.assertEqual(result.value, window_stats("home", START, NOW)["pressures"])
        self.assertNotIn(away_shot, result.evidence_ids)
        self.assertTrue(result.evidence_ids)

    def test_tiny_samples_are_unproven_not_busted(self):
        tiny = claim(metric="shots", start=1, end=3, value=window_stats("home", 1, 3)["shots"])
        self.assertEqual(verify_claim(tiny, 3).verdict, "unproven")

    def test_finding_states_what_the_data_shows(self):
        result = verify_claim(claim(team="away"), NOW)
        self.assertIn("Riverside United", result.finding)
        self.assertIn("Northbridge City", result.finding)


class WorkflowTests(unittest.TestCase):
    def run_job(self, *args, **kwargs):
        return asyncio.run(run_analysis(*args, **kwargs))

    def test_pipeline_runs_every_agent_once_and_narrates_once(self):
        result = self.run_job(70, "analyst", "home")
        agents = [t["agent"] for t in result["trace"]]
        for name in ("Orchestrator", "Stats", "Pundit", "Skeptic", "Narrator"):
            self.assertIn(name, agents)
        self.assertEqual(agents.count("Narrator"), 1)
        self.assertEqual(agents[-1], "Narrator")
        self.assertTrue(result["narrative"])

    def test_skeptic_sends_busted_takes_back_for_revision(self):
        runs = [self.run_job(minute, "analyst", focus) for minute in range(20, 91, 10) for focus in ("home", "away")]
        revised = [r for r in runs if any(c["revision_of"] for c in r["claims"])]
        self.assertTrue(revised)
        for result in revised:
            self.assertEqual(result["rounds"], 1)
            self.assertTrue(any(c["verdict"] == "rejected" for c in result["claims"]))

    def test_accepted_claims_never_use_future_events(self):
        for minute in (12, 40, 70, 90):
            result = self.run_job(minute, "analyst", "away")
            for c in result["claims"]:
                if c["verdict"] in ("verified", "corrected"):
                    self.assertLessEqual(c["end"], minute)
                    for event_id in c["evidence_ids"]:
                        self.assertLessEqual(int(next(e for e in EVENTS if e["id"] == event_id)["minute"]), minute)

    def test_pundit_is_usually_right_not_a_straw_man(self):
        verdicts = [c["verdict"] for minute in range(15, 91, 5) for focus in ("home", "away")
                    for c in self.run_job(minute, "fan", focus)["claims"] if not c["revision_of"]]
        held = sum(v in ("verified", "corrected") for v in verdicts)
        busted = verdicts.count("rejected")
        self.assertGreater(held, len(verdicts) / 2)
        self.assertGreater(busted, 0)  # but not always right either, or the Skeptic has nothing to do

    def test_question_assumption_is_checked_first(self):
        result = self.run_job(minute_of(80), "fan", "home", "Why did Riverside lose control after 60?")
        premise = result["claims"][0]
        self.assertTrue(premise["premise"])
        self.assertEqual(premise["team"], "away")
        self.assertEqual(premise["verdict"], "verified")
        self.assertTrue(result["narrative"].startswith("Your question assumes"))

    def test_question_without_team_has_no_assumption(self):
        result = self.run_job(55, "fan", "home", "Who is controlling the game?")
        self.assertFalse(any(c["premise"] for c in result["claims"]))

    def test_question_sets_window_and_team(self):
        result = self.run_job(60, "fan", "home", "What did Riverside do between 20 and 35?")
        self.assertEqual(result["window"], [20, 35])
        self.assertEqual(result["focus"], "away")

    def test_question_minutes_are_football_minutes(self):
        """ "after 60" means 60' on the clock, which comes later on the timeline because of first-half added time."""
        result = self.run_job(80, "fan", "home", "What did Riverside do after 60?")
        self.assertEqual(result["window"], [minute_of(60), 80])
        self.assertEqual(result["window_label"].split("–")[0], "60'")
        added = self.run_job(50, "fan", "home", "What happened between 45+1 and 45+2?")
        self.assertEqual(added["window"], [46, 47])

    def test_halves_include_added_time(self):
        first = self.run_job(match_meta()["length"], "fan", "home", "How did the first half go?")
        self.assertEqual(first["window"], [1, match_meta()["first_half"]])
        second = self.run_job(match_meta()["length"], "fan", "home", "How did the second half go?")
        self.assertEqual(second["window"], [match_meta()["first_half"] + 1, match_meta()["length"]])

    def test_every_match_can_be_analysed(self):
        for match_id, spec in MATCHES.items():
            with self.subTest(match=match_id):
                result = self.run_job(70, "fan", "away", spec.questions[1], match=match_id)
                self.assertEqual(result["match"], match_id)
                self.assertTrue(result["narrative"])
                with use_match(match_id):
                    ids = {e["id"] for e in EVENTS if e["minute"] <= 70}
                for c in result["claims"]:
                    self.assertTrue(set(c["evidence_ids"]) <= ids)

    def test_slow_model_falls_back_to_rules(self):
        async def slow(*args, **kwargs):
            await asyncio.sleep(5)
        with mock.patch("app.agents.workflow.MODEL_TIMEOUT", 0.05), \
                mock.patch("app.agents.llm.propose", slow), mock.patch("app.agents.llm.narrate", slow):
            result = self.run_job(70, "fan", "home", client=object(), provider="nebius")
        self.assertEqual(result["engine"], "offline")
        self.assertTrue(any(t["detail"] == "Model took too long" for t in result["trace"]))
        self.assertTrue(result["narrative"])

    def test_question_about_future_is_clamped(self):
        result = self.run_job(30, "fan", "home", "What happened in the second half?")
        start, end = result["window"]
        self.assertLessEqual(start, end)
        self.assertLessEqual(end, 30)

    def test_broken_model_falls_back_to_rules(self):
        result = self.run_job(70, "fan", "home", client=object())
        self.assertEqual(result["engine"], "offline")
        self.assertTrue(result["narrative"])


class KeyMomentTests(unittest.TestCase):
    def test_moments_never_come_from_the_future(self):
        self.assertTrue(all(m["minute"] <= 50 for m in key_moments(50)))
        self.assertEqual([m["kind"] for m in key_moments(17)].count("goal"), 0)

    def test_goals_have_a_story_and_a_replay_path(self):
        goals = [m for m in key_moments(match_meta()["length"]) if m["kind"] == "goal"]
        self.assertEqual(len(goals), 3)
        for m in goals:
            self.assertTrue(m["creator"])
            self.assertEqual(m["path"][-1]["kind"], "goal")
            self.assertGreaterEqual(len(m["path"]), 3)
            self.assertIn(m["shooter"], m["title"])

    def test_ask_about_a_moment_looks_at_the_minutes_before_it(self):
        moment = next(m for m in key_moments(90) if m["label"] == "72'")
        self.assertEqual(moment["question"], "What led to Northbridge City's goal at 72'?")
        result = asyncio.run(run_analysis(90, "fan", "home", moment["question"]))
        self.assertEqual(result["window"], [minute_of(63), minute_of(72)])
        self.assertTrue(result["narrative"].startswith("At 71:36, I. Brown gave the ball away"))
        self.assertIn("A. Okafor scored", result["narrative"])

    def test_saves_name_the_keeper(self):
        with use_match("hollowmere-stanton"):
            saved = [m for m in key_moments(match_meta()["length"]) if m["title"].endswith("E. Kowal")]
        self.assertTrue(saved)

    def test_asking_about_a_moment_that_has_not_happened_says_nothing_about_it(self):
        result = asyncio.run(run_analysis(60, "fan", "home", "What led to Northbridge City's goal at 72?"))
        self.assertNotIn("Okafor scored", result["narrative"])


class PunditWordingTests(unittest.TestCase):
    def test_takes_quoting_numbers_are_reworded(self):
        from app.agents.llm import _take_text
        raw = {"team": "home", "metric": "pressures", "relation": "more",
               "text": "Northbridge's press was relentless - 17 pressures versus Riverside's 8."}
        self.assertNotRegex(_take_text(raw), r"\d")
        self.assertIn("Northbridge City", _take_text(raw))
        self.assertEqual(_take_text({**raw, "text": "Northbridge are all over them"}), "Northbridge are all over them")


class GroundingGuardTests(unittest.TestCase):
    def test_flags_invented_numbers(self):
        job = Job(minute=NOW, mode="fan", focus="home", window=(START, NOW))
        verified = verify_claim(claim(), NOW)
        ok = f"Northbridge City pressed {verified.value:g} times to {verified.compare_value:g}."
        self.assertEqual(ungrounded_numbers(ok, job, [verified]), [])
        self.assertEqual(ungrounded_numbers("They won 37 duels.", job, [verified]), ["37"])


AZURE = {"AZURE_OPENAI_ENDPOINT": "https://x.openai.azure.com", "AZURE_OPENAI_API_KEY": "k",
         "AZURE_OPENAI_DEPLOYMENT": "d"}


class ProviderTests(unittest.TestCase):
    def provider(self, env):
        with mock.patch.dict(os.environ, env, clear=True):
            return configured_provider()

    def test_offline_without_credentials(self):
        self.assertEqual(self.provider({}), "offline")

    def test_nebius_key_selects_nebius(self):
        self.assertEqual(self.provider({"NEBIUS_API_KEY": "k"}), "nebius")

    def test_placeholders_from_env_example_are_ignored(self):
        placeholders = {"AZURE_OPENAI_ENDPOINT": "https://YOUR-RESOURCE.openai.azure.com",
                        "AZURE_OPENAI_API_KEY": "YOUR_SECRET_API_KEY", "AZURE_OPENAI_DEPLOYMENT": "YOUR-DEPLOYMENT-NAME"}
        self.assertEqual(self.provider({**placeholders, "NEBIUS_API_KEY": "k"}), "nebius")

    def test_foundry_preferred_unless_overridden(self):
        both = {**AZURE, "NEBIUS_API_KEY": "k"}
        self.assertEqual(self.provider(both), "foundry")
        self.assertEqual(self.provider({**both, "MATCHMIND_PROVIDER": "nebius"}), "nebius")

    def test_nebius_client_is_built(self):
        with mock.patch.dict(os.environ, {"NEBIUS_API_KEY": "k"}, clear=True):
            client, provider = model_client()
        self.assertEqual(provider, "nebius")
        self.assertIsNotNone(client)


class PlayerRatingTests(unittest.TestCase):
    def test_rating_only_uses_events_so_far(self):
        before = {p["name"]: p for p in ranking(minute_of(71))}
        after = {p["name"]: p for p in ranking(minute_of(73))}
        self.assertEqual(before["A. Okafor"]["counts"]["goals"], 0)  # scores at 71:36 (72nd minute)
        self.assertEqual(after["A. Okafor"]["counts"]["goals"], 1)
        self.assertGreater(after["A. Okafor"]["rating"], before["A. Okafor"]["rating"])

    def test_ratings_start_at_six_and_stay_out_of_ten(self):
        self.assertTrue(all(p["rating"] == 6.0 for p in ranking(0)))
        full_time = ranking(90)
        self.assertTrue(all(3.0 <= p["rating"] <= 10.0 for p in full_time))
        self.assertGreater(full_time[0]["rating"] - full_time[-1]["rating"], 1.5)

    def test_every_action_is_worth_between_minus_ten_and_ten(self):
        for p in ranking(90):
            for m in p["moments"]:
                self.assertLessEqual(abs(m["points"]), 10)

    def test_chances_are_shared_and_mistakes_are_charged(self):
        players = ranking(90)
        self.assertTrue(any(p["counts"]["chances_involved"] and not p["counts"]["shots"] for p in players))
        self.assertTrue(any(p["counts"]["chances_after_loss"] and p["values"]["costly"] < 0 for p in players))

    def test_a_defender_can_rate_as_well_as_a_goalscorer(self):
        players = ranking(90)
        best_defender = max((p for p in players if p["position"] == "DF"), key=lambda p: p["rating"])
        scorers = [p for p in players if p["counts"]["goals"]]
        self.assertGreaterEqual(best_defender["rating"], min(p["rating"] for p in scorers))

    def test_keepers_are_credited_for_saves(self):
        with use_match("hollowmere-stanton"):
            keeper = next(p for p in ranking(match_meta()["length"]) if p["name"] == "E. Kowal")
        self.assertGreaterEqual(keeper["counts"]["saves"], 3)
        self.assertGreater(keeper["values"]["defending"], 3)
        self.assertGreater(keeper["rating"], 6.5)

    def test_substitutes_only_appear_once_they_come_on(self):
        on = {e["receiver"]: e["minute"] for e in EVENTS if e["type"] == "substitution"}
        for minute in (40, 70, match_meta()["length"]):
            names = {p["name"] for p in ranking(minute)}
            self.assertEqual({n for n in on if n in names}, {n for n, m in on.items() if m <= minute})

    def test_compare_explains_the_difference(self):
        result = compare("A. Okafor", "I. Brown", 90)
        self.assertEqual(result["winner"], "A. Okafor")
        self.assertIn("/10", result["verdict"])
        self.assertIn("lost the ball before", result["verdict"])
        self.assertNotIn("xG", compare("A. Okafor", "I. Brown", 90, "simple")["verdict"])


class ApiTests(unittest.TestCase):
    def setUp(self):
        from app import main
        main._recent.clear()
        main._answers.clear()

    @mock.patch.dict(os.environ, {}, clear=True)  # rule-based agents, even if a local .env has keys
    def test_analyze_endpoint(self):
        res = TestClient(app).post("/api/analyze", json={"minute": 70, "mode": "fan", "focus": "home",
                                                         "question": "Who is pressing more?"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["synthetic"])
        self.assertEqual(body["claims"][0]["metric"], "pressures")

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_analyze_stream_reports_each_agent_then_the_result(self):
        with TestClient(app).stream("POST", "/api/analyze/stream",
                                    json={"minute": 70, "mode": "fan", "focus": "home"}) as res:
            items = [json.loads(line) for line in res.iter_lines() if line]
        working = [i["agent"] for i in items if i["type"] == "working"]
        self.assertEqual(working[:3], ["Orchestrator", "Stats", "Pundit"])
        self.assertIn("Narrator", working)
        self.assertTrue(any(i["type"] == "step" for i in items))
        self.assertEqual(items[-1]["type"], "result")
        self.assertTrue(items[-1]["result"]["narrative"])
        self.assertNotIn("listener", items[-1]["result"])

    def test_moments_endpoint(self):
        moments = TestClient(app).get("/api/moments?minute=45").json()["moments"]
        self.assertTrue(moments)
        self.assertEqual(moments, sorted(moments, key=lambda m: -m["minute"]))

    def test_players_and_compare_endpoints(self):
        client = TestClient(app)
        players = client.get("/api/players?minute=60").json()["players"]
        subs = sum(e["type"] == "substitution" and e["minute"] <= 60 for e in EVENTS)
        self.assertEqual(len(players), 22 + subs)
        res = client.get("/api/compare", params={"a": players[0]["name"], "b": players[-1]["name"], "minute": 60})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(client.get("/api/compare", params={"a": "Nobody", "b": "Nobody"}).status_code, 404)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_simple_mode_has_no_jargon(self):
        res = TestClient(app).post("/api/analyze", json={"minute": 70, "mode": "simple", "focus": "home",
                                                         "question": "Why did Riverside lose control after 60?"})
        narrative = res.json()["narrative"]
        for jargon in ("xG", "final third", "press", "possession"):
            self.assertNotIn(jargon, narrative)

    def test_analyze_validates_input(self):
        client = TestClient(app)
        self.assertEqual(client.post("/api/analyze", json={"minute": 200}).status_code, 422)
        self.assertEqual(client.post("/api/analyze", json={"minute": 50, "match": "real-madrid"}).status_code, 422)

    def test_every_endpoint_takes_a_match(self):
        client = TestClient(app)
        self.assertEqual(len(client.get("/api/matches").json()["matches"]), len(MATCHES))
        for match_id, spec in MATCHES.items():
            with self.subTest(match=match_id):
                config = client.get("/api/config", params={"match": match_id}).json()
                self.assertEqual(config["teams"]["home"]["name"], spec.teams["home"]["name"])
                self.assertEqual(len(config["labels"]), config["length"] + 1)
                state = client.get("/api/state", params={"match": match_id, "minute": 150}).json()
                self.assertEqual(state["minute"], config["length"])
                self.assertEqual(state["label"], config["labels"][-1])
                names = {p["name"] for p in client.get("/api/players", params={"match": match_id}).json()["players"]}
                self.assertIn(spec.squads["home"][0][2], names)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_repeat_questions_are_answered_from_the_cache_and_streamed(self):
        client = TestClient(app)
        body = {"minute": 70, "mode": "fan", "focus": "home", "question": "Who is pressing more?"}
        first = client.post("/api/analyze", json=body).json()
        with mock.patch("app.main.run_analysis") as run:
            again = client.post("/api/analyze", json={**body, "question": "  who is PRESSING more? "}).json()
            with client.stream("POST", "/api/analyze/stream", json=body) as res:
                items = [json.loads(line) for line in res.iter_lines() if line]
            run.assert_not_called()
        self.assertEqual(first["narrative"], again["narrative"])
        self.assertTrue(any(i["type"] == "step" for i in items))
        self.assertEqual(items[-1]["result"]["narrative"], first["narrative"])

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_rate_limit(self):
        client = TestClient(app)
        with mock.patch("app.main.RATE_LIMIT", 3):
            codes = [client.post("/api/analyze", json={"minute": 30 + i}).status_code for i in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])


class WordingTests(unittest.TestCase):
    def test_possessives(self):
        self.assertEqual(tidy("Ashford Rovers's press"), "Ashford Rovers' press")
        self.assertEqual(tidy("Northbridge City's press"), "Northbridge City's press")


if __name__ == "__main__":
    unittest.main()
