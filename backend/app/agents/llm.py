"""Microsoft Foundry model-backed agents (Microsoft Agent Framework `Agent`).

Used only when AZURE_OPENAI_* is configured. Models draft claims and prose; every number
they produce is re-checked by deterministic code before it reaches a viewer.
"""

import json
import os
import re

from agent_framework import Agent

from ..synthetic import TEAMS
from .models import METRIC_LABELS, Claim, Job
from .tools import EVENTS_BY_ID, window_events, window_stats

API_VERSION = "2024-10-21"


def foundry_client():
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not all((endpoint, api_key, deployment)):
        return None
    try:
        from agent_framework.openai import OpenAIChatCompletionClient
    except ModuleNotFoundError:
        return None
    return OpenAIChatCompletionClient(model=deployment, api_key=api_key, azure_endpoint=endpoint,
                                      api_version=os.environ.get("AZURE_OPENAI_API_VERSION", API_VERSION))


def make_tools(minute: int):
    """Tools bound to the current minute so a model can't look at the future."""
    def team_window_stats(team: str, start: int, end: int) -> dict:
        """Event counts for team ('home' or 'away') between two match minutes, inclusive."""
        return window_stats(team, max(1, start), min(end, minute))

    def list_events(team: str, event_type: str, start: int, end: int, limit: int = 8) -> list[dict]:
        """Recent events (pass, pressure, tackle, shot, turnover) for a team in a minute window."""
        events = [e for e in window_events(max(1, start), min(end, minute))
                  if e["team"] == team and e["type"] == event_type]
        return [{k: e[k] for k in ("id", "clock", "player", "type", "outcome", "xg")} for e in events[-limit:]]

    return [team_window_stats, list_events]


TACTICS_INSTRUCTIONS = f"""You are the Tactics agent in MatchMind, analysing a fictional football match
(home = {TEAMS['home']['name']}, away = {TEAMS['away']['name']}). Use your tools to inspect the event log,
then propose up to 4 tactical claims. Each claim MUST be a comparison a checker can recompute:
metric in {sorted(METRIC_LABELS)}; compare "opponent" (same window, other team) or "previous"
(the equally long window just before); relation "more" or "less". Cite evidence event IDs from list_events.
Reply with JSON only: {{"claims": [{{"team": "home|away", "metric": "...", "start": 1, "end": 10,
"value": 0, "relation": "more|less", "compare": "opponent|previous", "text": "one plain sentence",
"evidence_ids": ["SIM-0001"]}}]}}. A Skeptic will reject anything the data doesn't support."""

NARRATOR_INSTRUCTIONS = """You are the Narrator agent in MatchMind. The match is fictional.
Write using ONLY the verified claims you are given. Never add numbers, players, causes or events
that are not in them. "fan" readers get 2-3 short, lively sentences with at most one number.
"analyst" readers get precise wording with the numbers. 70 words maximum. No real clubs."""


def _json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    return json.loads(match[0]) if match else {}


async def propose(client, job: Job, rejected: list[Claim] | None = None) -> list[Claim]:
    agent = Agent(client=client, name="Tactics", instructions=TACTICS_INSTRUCTIONS, tools=make_tools(job.minute))
    start, end = job.window
    prompt = (f"Current minute: {job.minute}. Investigate minutes {start}-{end}, following "
              f"{TEAMS[job.focus]['name']} ({job.focus}). Viewer question: {job.question or 'none'}. "
              f"Priority metrics: {job.priorities or 'your choice'}.")
    if rejected:
        prompt += " The Skeptic rejected these claims; propose corrected replacements or drop them: " + json.dumps(
            [{"id": c.id, "text": c.text, "reason": c.reason} for c in rejected])
    response = await agent.run(prompt)
    claims = []
    prefix = "R" if rejected else "C"
    for idx, raw in enumerate(_json(response.text).get("claims", [])[:4], start=1):
        try:
            claims.append(Claim(
                id=f"{prefix}{idx}", team=str(raw["team"]), metric=str(raw["metric"]),
                start=int(raw["start"]), end=int(raw["end"]), value=float(raw["value"]),
                relation=str(raw["relation"]), compare=str(raw["compare"]), text=str(raw["text"])[:200],
                evidence_ids=[str(i) for i in raw.get("evidence_ids", []) if str(i) in EVENTS_BY_ID][:6],
                proposed_by="Tactics (revision)" if rejected else "Tactics",
                revision_of=",".join(c.id for c in rejected) if rejected else None,
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return claims


async def narrate(client, job: Job, accepted: list[Claim]) -> str:
    agent = Agent(client=client, name="Narrator", instructions=NARRATOR_INSTRUCTIONS)
    facts = [{"text": c.text, "metric": METRIC_LABELS[c.metric], "value": c.value,
              "compared_with": c.compare_value, "minutes": [c.start, c.end]} for c in accepted]
    response = await agent.run(
        f"Reader: {job.mode}. Following {TEAMS[job.focus]['name']}. Question: {job.question or 'none'}. "
        f"Verified claims: {json.dumps(facts)}")
    return response.text.strip()


def ungrounded_numbers(text: str, job: Job, accepted: list[Claim]) -> list[str]:
    """Grounding guard: every number in the narration must come from a verified claim or the clock."""
    allowed = {float(job.minute), *map(float, job.window)}
    for c in accepted:
        allowed |= {float(c.start), float(c.end)}
        for v in (c.value, c.actual_value, c.compare_value):
            if v is not None:
                allowed |= {round(float(v), 2), float(round(v))}
    found = re.findall(r"\d+(?:\.\d+)?", text)
    return [n for n in found if not any(abs(float(n) - a) < 0.051 for a in allowed)]
