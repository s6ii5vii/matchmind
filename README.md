# MatchMind

**A football analyst whose AI agents argue with each other.** Every claim needs evidence, and a Skeptic agent rejects anything the match data doesn't support.

Built for **Inside the Game: Microsoft Premier League Hackathon 2026** (Best Multi-Agent System).

## How it works

Five agents run as a [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) workflow:

| Agent | Role |
|---|---|
| **Orchestrator** | Turns the viewer's question into a team, minute window and metrics to check |
| **Stats** | Computes the numbers from the event log (code, no model) |
| **Tactics** | Proposes tactical claims, each citing evidence events (Foundry model or rules) |
| **Skeptic** | Recomputes every claim: verified, corrected or rejected. Sends rejections back to Tactics for revision |
| **Narrator** | Explains only verified claims, for fans or analysts. A grounding guard blocks any number not in a verified claim |

Models can draft claims and wording, but every number a viewer sees is recomputed from the event log, and no agent can see events after the current minute. The dashboard shows the full agent trace.

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

### Microsoft Foundry models (optional)

Without credentials the agents run on rules and everything works offline. To let a Foundry chat model drive Tactics and Narrator, set these in the backend terminal and restart it:

```powershell
$env:AZURE_OPENAI_ENDPOINT='https://YOUR-RESOURCE.openai.azure.com'
$env:AZURE_OPENAI_DEPLOYMENT='YOUR-DEPLOYMENT-NAME'
$env:AZURE_OPENAI_API_KEY='YOUR_API_KEY'
```

Never commit keys or `.env` files.

## Data and limitations

All clubs, players and events are fictional and generated from a fixed seed. No real Premier League data or footage is used. xG values are illustrative, not a trained model, and event share is not possession time.
