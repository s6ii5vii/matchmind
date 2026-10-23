# MatchMind

**The take vs. the data.** A Pundit agent says what everyone's thinking about the match; a Skeptic agent checks every take against the event log and says whether it holds up.

Built for **Inside the Game: Microsoft Premier League Hackathon 2026** (Best Multi-Agent System).

## How it works

Five agents run as a [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) workflow:

| Agent | Role |
|---|---|
| **Orchestrator** | Turns the viewer's question into a team, minute window and metrics to check, and picks out any assumption in it ("why did Riverside lose control?") |
| **Stats** | Computes the numbers from the event log (code, no model) |
| **Pundit** | Gives confident takes from what a viewer just saw: the last few minutes, no stats (AI model or rules). Usually right, sometimes caught out by recency bias |
| **Skeptic** | Checks every take, and the question's assumption, against the full spell: holds up, half-right, not enough evidence, or doesn't hold up. Sends busted takes back to the Pundit to rethink |
| **Narrator** | Tells fans or analysts what holds up and what doesn't. A grounding guard blocks any number the Skeptic didn't produce |

Models can draft takes and wording, but every number a viewer sees is recomputed from the event log, and no agent can see events after the current minute. The dashboard shows each take next to the data, with the full agent trace one click away.

## Run it

Requires Python 3.10+ and Node.js 20+.

```powershell
# Terminal 1: backend
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# Terminal 2: frontend
cd frontend
npm install
npm run dev
```

Open http://localhost:3000, scrub to a minute, and ask the Agent room a question.

Tests (from `backend/`): `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`

### AI models (optional)

Without credentials the agents run on rules and everything works offline. To let a model drive the Pundit and Narrator, copy `backend/.env.example` to `backend/.env`, fill in one provider, and restart the backend. (`.env` is git-ignored; you can also set the same names as environment variables.)

**Microsoft Foundry** (Azure OpenAI deployment):

```powershell
$env:AZURE_OPENAI_ENDPOINT='https://YOUR-RESOURCE.openai.azure.com'
$env:AZURE_OPENAI_DEPLOYMENT='YOUR-DEPLOYMENT-NAME'
$env:AZURE_OPENAI_API_KEY='YOUR_API_KEY'
```

**Nebius Token Factory** (OpenAI-compatible):

```powershell
$env:NEBIUS_API_KEY='YOUR_API_KEY'
$env:NEBIUS_MODEL='openai/gpt-oss-120b'   # optional; any Token Factory model that supports tool calling
```

If both are set, Foundry is used; set `$env:MATCHMIND_PROVIDER='nebius'` to choose Nebius. Never commit keys or `.env` files.

## Data and limitations

All clubs, players and events are fictional. `backend/app/synthetic.py` simulates a full match possession by possession from a fixed seed: about 1,350 events over 300 possessions, with 11-player squads, passes with start and end positions, pressing that forces errors, interceptions, tackles, shots with xG, and time-based possession. The match follows a story (Riverside's spell before half-time, Northbridge's pressing spell after the hour) so the agents have something real to find. No real Premier League data or footage is used, and xG values are illustrative, not a trained model.
