import asyncio
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app.agents import run_analysis
from app.agents.llm import configured_provider, model_client, ungrounded_numbers
from app.agents.models import Claim, Job
from app.agents.tools import verify_claim, window_stats
from app.main import app
from app.synthetic import EVENTS


def claim(**overrides) -> Claim:
    base = dict(id="T1", team="home", metric="pressures", start=61, end=70,
                value=window_stats("home", 61, 70)["pressures"], relation="more", compare="opponent",
                text="Northbridge City is out-pressing Riverside United")
    return Claim(**{**base, **overrides})


class SkepticTests(unittest.TestCase):
    def test_verifies_true_claim(self):
        self.assertEqual(verify_claim(claim(), 70).verdict, "verified")

    def test_rejects_future_window(self):
        result = verify_claim(claim(end=75), 70)
        self.assertEqual(result.verdict, "rejected")
        self.assertIn("only 70 minutes", result.reason)

    def test_rejects_false_direction(self):
        self.assertEqual(verify_claim(claim(team="away"), 70).verdict, "rejected")

    def test_corrects_wrong_number_and_bad_evidence(self):
        away_shot = next(e["id"] for e in EVENTS if e["team"] == "away" and e["type"] == "shot")
        result = verify_claim(claim(value=99, evidence_ids=[away_shot]), 70)
        self.assertEqual(result.verdict, "corrected")
        self.assertEqual(result.value, window_stats("home", 61, 70)["pressures"])
        self.assertNotIn(away_shot, result.evidence_ids)
        self.assertTrue(result.evidence_ids)

    def test_rejects_tiny_samples(self):
        tiny = claim(start=1, end=3, value=window_stats("home", 1, 3)["pressures"])
        self.assertEqual(verify_claim(tiny, 3).verdict, "rejected")


class WorkflowTests(unittest.TestCase):
    def run_job(self, *args, **kwargs):
        return asyncio.run(run_analysis(*args, **kwargs))

    def test_pipeline_runs_every_agent_once_and_narrates_once(self):
        result = self.run_job(70, "analyst", "home")
        agents = [t["agent"] for t in result["trace"]]
        for name in ("Orchestrator", "Stats", "Tactics", "Skeptic", "Narrator"):
            self.assertIn(name, agents)
        self.assertEqual(agents.count("Narrator"), 1)
        self.assertEqual(agents[-1], "Narrator")
        self.assertTrue(result["narrative"])

    def test_skeptic_sends_rejections_back_for_revision(self):
        result = self.run_job(70, "analyst", "home")
        self.assertTrue(any(c["verdict"] == "rejected" for c in result["claims"]))
        self.assertEqual(result["rounds"], 1)
        self.assertTrue(any(c["revision_of"] for c in result["claims"]))

    def test_accepted_claims_never_use_future_events(self):
        for minute in (12, 40, 70, 90):
            result = self.run_job(minute, "analyst", "away")
            for c in result["claims"]:
                if c["verdict"] != "rejected":
                    self.assertLessEqual(c["end"], minute)
                    for event_id in c["evidence_ids"]:
                        self.assertLessEqual(int(next(e for e in EVENTS if e["id"] == event_id)["minute"]), minute)

    def test_question_sets_window_and_team(self):
        result = self.run_job(60, "fan", "home", "What did Riverside do between 20 and 35?")
        self.assertEqual(result["window"], [20, 35])
        self.assertEqual(result["focus"], "away")

    def test_question_about_future_is_clamped(self):
        result = self.run_job(30, "fan", "home", "What happened in the second half?")
        self.assertLessEqual(result["window"][1], 30)

    def test_broken_model_falls_back_to_rules(self):
        result = self.run_job(70, "fan", "home", client=object())
        self.assertEqual(result["engine"], "offline")
        self.assertTrue(result["narrative"])


class GroundingGuardTests(unittest.TestCase):
    def test_flags_invented_numbers(self):
        job = Job(minute=70, mode="fan", focus="home", window=(61, 70))
        verified = verify_claim(claim(), 70)
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

    def test_foundry_preferred_unless_overridden(self):
        both = {**AZURE, "NEBIUS_API_KEY": "k"}
        self.assertEqual(self.provider(both), "foundry")
        self.assertEqual(self.provider({**both, "MATCHMIND_PROVIDER": "nebius"}), "nebius")

    def test_nebius_client_is_built(self):
        with mock.patch.dict(os.environ, {"NEBIUS_API_KEY": "k"}, clear=True):
            client, provider = model_client()
        self.assertEqual(provider, "nebius")
        self.assertIsNotNone(client)


class ApiTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {}, clear=True)  # rule-based agents, even if a local .env has keys
    def test_analyze_endpoint(self):
        res = TestClient(app).post("/api/analyze", json={"minute": 70, "mode": "fan", "focus": "home",
                                                         "question": "Who is pressing more?"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["synthetic"])
        self.assertEqual(body["claims"][0]["metric"], "pressures")

    def test_analyze_validates_input(self):
        self.assertEqual(TestClient(app).post("/api/analyze", json={"minute": 95}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
