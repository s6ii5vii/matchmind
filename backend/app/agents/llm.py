"""Model-backed agents (Microsoft Agent Framework `Agent`).

Used only when a model provider is configured: Microsoft Foundry (AZURE_OPENAI_*) or any
OpenAI-compatible endpoint such as Nebius Token Factory (NEBIUS_API_KEY). Models draft claims
and prose; every number they produce is re-checked by deterministic code before a viewer sees it.
"""

import json
import os
import re

from agent_framework import Agent

from ..synthetic import TEAMS
from .models import METRIC_LABELS, Claim, Job
from .tools import EVENTS_BY_ID, window_events

API_VERSION = "2025-04-01-preview"  # GPT-5 family needs 2025-04-01-preview or later
NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
NEBIUS_DEFAULT_MODEL = "openai/gpt-oss-120b"
PROVIDERS = ("foundry", "nebius")


def _is_set(name: str) -> bool:
    """True for a real value; the YOUR-... placeholders copied from .env.example don't count."""
    value = os.environ.get(name, "").strip()
    return bool(value) and "YOUR" not in value


def configured_provider() -> str:
    """Which model provider to use: MATCHMIND_PROVIDER if set, else the first one configured."""
    configured = {
        "foundry": all(_is_set(k) for k in
                       ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT")),
        "nebius": _is_set("NEBIUS_API_KEY"),
    }
    preferred = os.environ.get("MATCHMIND_PROVIDER", "").lower()
    if configured.get(preferred):
        return preferred
    return next((p for p in PROVIDERS if configured[p]), "offline")


def model_client():
    """Return (Agent Framework chat client, provider name), or (None, "offline")."""
    provider = configured_provider()
    if provider == "offline":
        return None, provider
    try:
        from agent_framework.openai import OpenAIChatCompletionClient
    except ModuleNotFoundError:
        return None, "offline"
    if provider == "foundry":
        client = OpenAIChatCompletionClient(
            model=os.environ["AZURE_OPENAI_DEPLOYMENT"], api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/"),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", API_VERSION))
    else:
        client = OpenAIChatCompletionClient(
            model=os.environ.get("NEBIUS_MODEL", NEBIUS_DEFAULT_MODEL), api_key=os.environ["NEBIUS_API_KEY"],
            base_url=os.environ.get("NEBIUS_BASE_URL", NEBIUS_BASE_URL))
    return client, provider


def make_pundit_tools(minute: int):
    """A viewer's-eye view: recent moves and events only, no aggregated stats, nothing after the current minute."""
    def recent_moves(team: str = "", last_minutes: int = 5) -> list[dict]:
        """The passing moves a viewer just watched (optionally one team, 'home' or 'away'): who had the ball,
        how many passes, where the move started and reached, and how it ended."""
        moves: dict[int, list[dict]] = {}
        for e in window_events(max(1, minute - last_minutes + 1), minute):
            moves.setdefault(e["possession"], []).append(e)
        summary = []
        for events in moves.values():
            side = events[0]["possession_team"]
            if team and side != team:
                continue
            own = [e for e in events if e["team"] == side]
            ending = next((e["possession_end"] for e in reversed(events) if e["possession_end"]), "still going")
            summary.append({
                "team": side, "from": events[0]["clock"], "passes": sum(e["type"] == "pass" for e in own),
                "started_in": own[0]["zone"] + " third" if own else "n/a",
                "reached": max((e["zone"] for e in own), key=("defensive", "middle", "attacking").index) + " third"
                if own else "n/a",
                "pressed_times": sum(e["type"] == "pressure" for e in events), "ended": ending,
                "event_ids": [e["id"] for e in events][-4:],
            })
        return summary[-12:]

    def recent_events(team: str, event_type: str = "", last_minutes: int = 5, limit: int = 8) -> list[dict]:
        """Individual events a viewer just watched for team ('home' or 'away'), optionally one type
        (pass, pressure, tackle, interception, shot, turnover, foul)."""
        events = [e for e in window_events(max(1, minute - last_minutes + 1), minute)
                  if e["team"] == team and (not event_type or e["type"] == event_type)]
        keys = ("id", "clock", "player", "position", "type", "outcome", "zone", "receiver", "under_pressure")
        return [{k: e[k] for k in keys} for e in events[-limit:]]

    return [recent_moves, recent_events]


PUNDIT_INSTRUCTIONS = f"""You are the Pundit agent in MatchMind, a TV pundit watching a fictional football match
(home = {TEAMS['home']['name']}, away = {TEAMS['away']['name']}). You only see what a viewer sees: the score
and the last few minutes of play (use recent_moves for the passing moves, recent_events for detail). You do NOT
have the stats. Read the game honestly and
give up to 3 confident, punchy takes, the way a good pundit would say them on air. You'll usually be right, but
you only saw the last few minutes and you're talking about the whole spell, so don't hedge: commit to your read.
Each take MUST map to a comparison a Skeptic can recompute: metric in {sorted(METRIC_LABELS)}; compare
"opponent" (same window, other team) or "previous" (the equally long window just before); relation "more" or
"less"; value = your best guess of the number. Cite event IDs you saw.
Reply with JSON only: {{"claims": [{{"team": "home|away", "metric": "...", "start": 1, "end": 10,
"value": 0, "relation": "more|less", "compare": "opponent|previous", "text": "the take, under 14 words",
"evidence_ids": ["SIM-0001"]}}]}}"""

NARRATOR_INSTRUCTIONS = """You are the Narrator agent in MatchMind. The match is fictional.
You get takes (from the viewer's question and a pundit), each with the Skeptic's verdict and what the data shows.
Tell the reader what holds up and what doesn't, starting with the viewer's question if there is one.
Use ONLY the data lines given; never add numbers, players, causes or events. "fan" readers: 2-3 short, lively
sentences, at most one number. "analyst" readers: precise, with the numbers. 70 words maximum. No real clubs."""


def _json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    return json.loads(match[0]) if match else {}


async def propose(client, job: Job, rejected: list[Claim] | None = None) -> list[Claim]:
    agent = Agent(client=client, name="Pundit", instructions=PUNDIT_INSTRUCTIONS, tools=make_pundit_tools(job.minute))
    start, end = job.window
    score = {side: sum(1 for e in window_events(1, job.minute) if e["team"] == side and e["is_goal"]) for side in TEAMS}
    prompt = (f"Minute {job.minute}. Score: {TEAMS['home']['name']} {score['home']}-{score['away']} "
              f"{TEAMS['away']['name']}. Talk about minutes {start}-{end}, following {TEAMS[job.focus]['name']} "
              f"({job.focus}). Viewer question: {job.question or 'none'}.")
    covered = [c.metric for c in job.claims if c.premise]
    if covered:
        prompt += f" The question's own assumption ({covered[0]}) is already being checked; talk about something else."
    if rejected:
        prompt += (" The Skeptic busted these takes with data. Give a better take for each, or drop it: " +
                   json.dumps([{"id": c.id, "take": c.text, "data": c.finding or c.reason} for c in rejected]))
    response = await agent.run(prompt)
    claims = []
    prefix = "R" if rejected else "C"
    for idx, raw in enumerate(_json(response.text).get("claims", [])[:3], start=1):
        try:
            claims.append(Claim(
                id=f"{prefix}{idx}", team=str(raw["team"]), metric=str(raw["metric"]),
                start=int(raw["start"]), end=int(raw["end"]), value=float(raw["value"]),
                relation=str(raw["relation"]), compare=str(raw["compare"]), text=str(raw["text"])[:200],
                evidence_ids=[str(i) for i in raw.get("evidence_ids", []) if str(i) in EVENTS_BY_ID][:6],
                proposed_by="Pundit (revision)" if rejected else "Pundit",
                revision_of=",".join(c.id for c in rejected) if rejected else None,
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return claims


async def narrate(client, job: Job, checked: list[Claim]) -> str:
    agent = Agent(client=client, name="Narrator", instructions=NARRATOR_INSTRUCTIONS)
    takes = [{"from": "viewer's question" if c.premise else "pundit", "take": c.text, "verdict": c.verdict,
              "data": c.finding or c.reason} for c in checked]
    response = await agent.run(
        f"Reader: {job.mode}. Following {TEAMS[job.focus]['name']}. Question: {job.question or 'none'}. "
        f"Checked takes: {json.dumps(takes)}")
    return response.text.strip()


def ungrounded_numbers(text: str, job: Job, checked: list[Claim]) -> list[str]:
    """Grounding guard: every number in the narration must come from the Skeptic's data or the clock."""
    allowed = {float(job.minute), *map(float, job.window)}
    for c in checked:
        allowed |= {float(c.start), float(c.end), float(c.start - (c.end - c.start + 1)), float(c.start - 1)}
        for v in (c.actual_value, c.compare_value):
            if v is not None:
                allowed |= {round(float(v), 2), float(round(v))}
    found = re.findall(r"\d+(?:\.\d+)?", text)
    return [n for n in found if not any(abs(float(n) - a) < 0.051 for a in allowed)]
