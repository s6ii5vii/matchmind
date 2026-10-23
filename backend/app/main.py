"""MatchMind MVP REST API. Start: uvicorn app.main:app --reload --port 8000"""

from pathlib import Path

from dotenv import load_dotenv

# model keys live in backend/.env (git-ignored); real environment variables take precedence
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agents import model_client, run_analysis
from .agents.llm import configured_provider
from .analysis import build_state
from .synthetic import EVENTS, TEAMS

app = FastAPI(title="MatchMind API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
)


class AnalyzeRequest(BaseModel):
    minute: int = Field(ge=0, le=90)
    mode: str = Field("fan", pattern="^(fan|analyst)$")
    focus: str = Field("home", pattern="^(home|away)$")
    question: str = Field("", max_length=300)


@app.get("/health")
def health():
    return {"ok": True, "app": "MatchMind", "synthetic": True}


@app.get("/api/config")
def config():
    return {
        "teams": TEAMS,
        "total_events": len(EVENTS),
        "model_provider": configured_provider(),
        "agents": ["Orchestrator", "Stats", "Tactics", "Skeptic", "Narrator"],
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


@app.post("/api/analyze")
async def analyze(body: AnalyzeRequest):
    """Run the multi-agent workflow (Orchestrator, Stats, Tactics, Skeptic, Narrator).

    Uses Microsoft Foundry or Nebius Token Factory models when configured, otherwise rule-based agents. Either way every
    claim is re-verified against the event log, and the full agent trace is returned.
    """
    client, provider = model_client()
    result = await run_analysis(body.minute, body.mode, body.focus, body.question, client=client, provider=provider)
    return {"synthetic": True, **result}
