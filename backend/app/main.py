"""MatchMind MVP REST API. Start: uvicorn app.main:app --reload --port 8000"""

import asyncio
import json
import os
import time
from collections import OrderedDict, deque
from pathlib import Path

from dotenv import load_dotenv

# model keys live in backend/.env (git-ignored); real environment variables take precedence
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents import model_client, run_analysis
from .agents.llm import configured_provider
from .analysis import build_state
from .moments import key_moments
from .players import compare, ranking
from .synthetic import DEFAULT_MATCH, EVENTS, MATCHES, TEAMS, generate_events, match_meta, use_match

app = FastAPI(title="MatchMind API", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
)


MATCH_PATTERN = "^(" + "|".join(MATCHES) + ")$"
MAX_MINUTE = 150  # longer than any match; each request is clamped to its match's length
MatchParam = Query(DEFAULT_MATCH, pattern=MATCH_PATTERN)
MinuteParam = Query(MAX_MINUTE, ge=0, le=MAX_MINUTE)


class AnalyzeRequest(BaseModel):
    minute: int = Field(ge=0, le=MAX_MINUTE)
    mode: str = Field("fan", pattern="^(simple|fan|analyst)$")
    focus: str = Field("home", pattern="^(home|away)$")
    question: str = Field("", max_length=300)
    match: str = Field(DEFAULT_MATCH, pattern=MATCH_PATTERN)


def clamp(minute: int) -> int:
    return min(minute, match_meta()["length"])


# --- keeping model costs in check: a per-visitor limit and a cache of answers ----------------------

RATE_LIMIT = int(os.environ.get("MATCHMIND_RATE_LIMIT", "12"))  # questions per visitor per minute
_recent: dict[str, deque] = {}
_answers: OrderedDict = OrderedDict()
CACHE_SIZE = 512


def visitor(request: Request) -> str:
    # behind Azure's ingress the visitor is the last address it appended; earlier ones can be made up
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[-1].strip() if forwarded else (request.client.host if request.client else "?")


def check_rate(request: Request) -> None:
    now, ip = time.monotonic(), visitor(request)
    times = _recent.setdefault(ip, deque())
    while times and now - times[0] > 60:
        times.popleft()
    if len(times) >= RATE_LIMIT:
        raise HTTPException(429, "That's a lot of questions at once. Give the agents a few seconds and try again.")
    times.append(now)
    if len(_recent) > 10_000:  # forget visitors who have gone quiet
        for key in [k for k, v in _recent.items() if not v or now - v[-1] > 60]:
            _recent.pop(key, None)


def cache_key(body: AnalyzeRequest, provider: str) -> tuple:
    return (body.match, clamp(body.minute), body.mode, body.focus, " ".join(body.question.lower().split()), provider)


def cached(key: tuple) -> dict | None:
    if key in _answers:
        _answers.move_to_end(key)
        return _answers[key]
    return None


def remember(key: tuple, result: dict) -> None:
    # an answer from a model that failed or timed out isn't worth keeping: the next ask may get the model
    if any("Model call failed" in step["action"] for step in result["trace"]):
        return
    _answers[key] = result
    while len(_answers) > CACHE_SIZE:
        _answers.popitem(last=False)


def match_summary(match_id: str) -> dict:
    spec = MATCHES[match_id]
    events = generate_events(match_id)
    score = {side: sum(e["is_goal"] and e["team"] == side for e in events) for side in ("home", "away")}
    return {"id": match_id, "teams": spec.teams, "score": score, "story": spec.story}


@app.get("/health")
def health():
    return {"ok": True, "app": "MatchMind", "synthetic": True}


@app.get("/api/matches")
def matches():
    """The fictional matches you can switch between."""
    return {"synthetic": True, "default": DEFAULT_MATCH, "matches": [match_summary(m) for m in MATCHES]}


@app.get("/api/config")
def config(match: str = MatchParam):
    with use_match(match):
        meta = match_meta()
        return {
            "match": match,
            "teams": dict(TEAMS),
            "story": MATCHES[match].story,
            "questions": list(MATCHES[match].questions),
            "length": meta["length"],
            "first_half": meta["first_half"],
            "added": meta["added"],
            "labels": meta["labels"],
            "total_events": len(EVENTS),
            "matches": [match_summary(m) for m in MATCHES],
            "model_provider": configured_provider(),
            "agents": ["Orchestrator", "Stats", "Pundit", "Skeptic", "Narrator"],
        }


@app.get("/api/events")
def events(minute: int = MinuteParam, match: str = MatchParam):
    with use_match(match):
        return {"synthetic": True, "events": [e for e in EVENTS if e["minute"] <= clamp(minute)]}


@app.get("/api/state")
def state(
    minute: int = Query(0, ge=0, le=MAX_MINUTE),
    mode: str = Query("fan", pattern="^(simple|fan|analyst)$"),
    focus: str = Query("home", pattern="^(home|away)$"),
    match: str = MatchParam,
):
    with use_match(match):
        return build_state(minute, mode, focus)


@app.post("/api/analyze")
async def analyze(body: AnalyzeRequest, request: Request):
    """Run the multi-agent workflow (Orchestrator, Stats, Pundit, Skeptic, Narrator).

    Uses Microsoft Foundry or Nebius Token Factory models when configured, otherwise rule-based agents. Either way every
    claim is re-verified against the event log, and the full agent trace is returned.
    """
    check_rate(request)
    client, provider = model_client()
    with use_match(body.match):
        key = cache_key(body, provider)
        if (result := cached(key)) is None:
            result = await run_analysis(clamp(body.minute), body.mode, body.focus, body.question,
                                        client=client, provider=provider, match=body.match)
            remember(key, result)
    return {"synthetic": True, **result}


@app.post("/api/analyze/stream")
async def analyze_stream(body: AnalyzeRequest, request: Request):
    """Same as /api/analyze, but streams each agent step as it happens (newline-delimited JSON),
    ending with {"type": "result", "result": {...}}."""
    check_rate(request)
    queue: asyncio.Queue = asyncio.Queue()
    client, provider = model_client()
    with use_match(body.match):
        key, minute = cache_key(body, provider), clamp(body.minute)

    async def produce() -> None:
        try:
            if (result := cached(key)) is not None:  # asked before: replay the agents' steps
                for step in result["trace"]:
                    queue.put_nowait({"type": "working", "agent": step["agent"], "detail": step["action"]})
                    queue.put_nowait({"type": "step", **step})
                    await asyncio.sleep(0.04)
            else:
                result = await run_analysis(minute, body.mode, body.focus, body.question, client=client,
                                            provider=provider, listener=queue.put_nowait, match=body.match)
                remember(key, result)
            queue.put_nowait({"type": "result", "result": {"synthetic": True, **result}})
        except Exception:
            queue.put_nowait({"type": "error", "detail": "The agents couldn't finish this one. Try again."})

    async def lines():
        task = asyncio.create_task(produce())
        try:
            while True:
                item = await queue.get()
                yield json.dumps(item) + "\n"
                if item["type"] in ("result", "error"):
                    break
        finally:
            task.cancel()

    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/players")
def players(minute: int = MinuteParam, match: str = MatchParam):
    """Every player's impact so far: credit for all actions, not just goals and assists."""
    with use_match(match):
        return {"synthetic": True, "minute": clamp(minute), "players": ranking(clamp(minute))}


@app.get("/api/moments")
def moments(minute: int = MinuteParam, match: str = MatchParam):
    """Goals and big chances so far, newest first, with each move's path for the pitch replay."""
    with use_match(match):
        return {"synthetic": True, "minute": clamp(minute), "moments": key_moments(clamp(minute))}


@app.get("/api/compare")
def compare_players(
    a: str, b: str,
    minute: int = MinuteParam,
    mode: str = Query("fan", pattern="^(simple|fan|analyst)$"),
    match: str = MatchParam,
):
    with use_match(match):
        try:
            return {"synthetic": True, **compare(a, b, clamp(minute), mode)}
        except KeyError:
            raise HTTPException(404, "Unknown player") from None


# In the deployed container the dashboard is built to static files and served from here,
# so the site and the API share one URL. Mounted last so /api routes always win.
STATIC_DIR = Path(os.environ.get("MATCHMIND_STATIC", Path(__file__).resolve().parents[1] / "static"))
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="site")
