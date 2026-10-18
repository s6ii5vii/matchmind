"""MatchMind MVP REST API. Start: uvicorn app.main:app --reload --port 8000"""

import os
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .analysis import build_state
from .synthetic import EVENTS, TEAMS

app = FastAPI(title="MatchMind API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
)


class NarrateRequest(BaseModel):
    minute: int = Field(ge=0, le=90)
    mode: str = "fan"
    focus: str = "home"


@app.get("/health")
def health():
    return {"ok": True, "app": "MatchMind", "synthetic": True}


@app.get("/api/config")
def config():
    return {
        "teams": TEAMS,
        "total_events": len(EVENTS),
        "foundry_configured": bool(os.environ.get("AZURE_OPENAI_ENDPOINT") and
                                   os.environ.get("AZURE_OPENAI_API_KEY") and
                                   os.environ.get("AZURE_OPENAI_DEPLOYMENT")),
    }


@app.get("/api/events")
def events(minute: int = Query(90, ge=0, le=90)):
    return {"synthetic": True, "events": [e for e in EVENTS if e["minute"] <= minute]}


@app.get("/api/state")
def state(
    minute: int = Query(0, ge=0, le=90),
    mode: str = Query("fan", pattern="^(fan|analyst)$"),
    focus: str = Query("home", pattern="^(home|away)$"),
):
    return build_state(minute, mode, focus)


@app.post("/api/narrate")
async def narrate(body: NarrateRequest):
    """Optional Microsoft Foundry (Azure OpenAI deployment) narration.

    This is a single model narration step, not yet a multi-agent production workflow.
    An unavailable or failing model never silently masquerades as AI.
    """
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not all((endpoint, api_key, deployment)):
        raise HTTPException(503, "Microsoft Foundry isn't configured. Use the verified local explanations meanwhile.")
    state_data = build_state(body.minute, body.mode, body.focus)
    insight_lines = [f"{i['title']}: {i['body']} (evidence: {','.join(i['evidence_ids'])})" for i in state_data["insights"]]
    h, a = state_data["stats"]["home"], state_data["stats"]["away"]
    evidence = (
        f"Fictional match, minute {body.minute}. Home {TEAMS['home']['name']} {h['goals']}, "
        f"away {TEAMS['away']['name']} {a['goals']}. "
        f"Shots home/away {h['shots']}/{a['shots']}; passes home/away {h['passes']}/{a['passes']}; "
        f"synthetic xG home/away {h['xg']}/{a['xg']}. "
        f"Evidence-backed insights: {' | '.join(insight_lines)}."
    )
    url = (f"{endpoint}/openai/deployments/{quote(deployment, safe='')}/chat/completions"
           f"?api-version=2024-10-21")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(url, headers={"api-key": api_key}, json={
                "messages": [
                    {"role": "system", "content": "You are a concise football match commentator. The match and data are synthetic. Use ONLY supplied facts. Never invent players, numbers, statistics, or causes. Distinguish interpretation from proven fact. Reply in English, 60 words maximum. Do not mention real football clubs."},
                    {"role": "user", "content": f"Write for a {body.mode} viewer, following {TEAMS.get(body.focus,TEAMS['home'])['name']}. {evidence}"},
                ],
                "max_tokens": 170,
                "temperature": 0.2,
            })
            res.raise_for_status()
            answer = res.json()["choices"][0]["message"]["content"]
            return {"provider": "Microsoft Foundry / Azure OpenAI", "text": answer, "synthetic": True}
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise HTTPException(502, "Foundry model call failed. Check deployment, endpoint, key and permissions.") from exc
