# MatchMind — synthetic live football intelligence

An original hackathon MVP built for **Inside the Game: Microsoft Premier League Hackathon (2026)**.

## What works in v0.2

- A deterministic, explicitly **synthetic** 90-minute event stream (passes, pressure events, tackles, turnovers, shots, goals).
- Auditable event-based match statistics, including goals, pass completion, shots, synthetic xG, pressures, and **event share (not possession time)**.
- **Agent room: a multi-agent workflow built on Microsoft Agent Framework.** Five agents investigate the match so far and answer viewer questions ("Why did Riverside lose control after 60?"). A Skeptic agent checks every claim against the event log and rejects or corrects anything the data doesn't support. The full agent trace is shown in the dashboard.
- Optional Microsoft Foundry models for the Tactics and Narrator agents. Without credentials, rule-based agents run the same workflow.
- Live playback timeline, tactical feed, favorite-team focus, fan/analyst modes, goal milestones.
- Tests covering future-event leakage, the Skeptic's checks, the revision loop and the grounding guard.

## Requirements

- Python 3.10+
- Node.js 20+
- Internet access for the initial `pip` and `npm` package installs

## Run locally in VS Code (PowerShell on Windows)

Extract this folder, then open it in VS Code.

**Terminal 1 — backend:**

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — frontend:**

```powershell
cd frontend
npm install
npm run dev
```

Go to http://localhost:3000 . API docs: http://127.0.0.1:8000/docs .

If `py` isn't installed, use `python` instead.

## Run the backend tests

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Optional: Microsoft Foundry models for the agents

With no credentials, the agents are rule-based and the dashboard works fully offline. To let Foundry models drive the **Tactics** and **Narrator** agents:

1. In Microsoft Foundry, deploy a chat model (for example a GPT-4o-class model) exposed through the Azure OpenAI API.
2. Set these environment variables in the **backend terminal** (replace placeholders):

```powershell
$env:AZURE_OPENAI_ENDPOINT='https://YOUR-RESOURCE.openai.azure.com'
$env:AZURE_OPENAI_DEPLOYMENT='YOUR-DEPLOYMENT-NAME'
$env:AZURE_OPENAI_API_KEY='YOUR_API_KEY'
```

3. Restart the backend. The Agent room header changes to **Microsoft Foundry agents**.

Never commit keys, secrets or `.env` files to GitHub. If a model call fails, the agents fall back to rules and say so in the trace.


## Architecture

```
Synthetic event generator (seeded Python)
  -> deterministic analytics (auditable evidence IDs)       -> /api/state, /api/events
  -> Microsoft Agent Framework workflow                     -> /api/analyze
       Orchestrator  plans the minute window, team and metrics from the question
       Stats         computes window stats from the event log (tool, no model)
       Tactics       proposes comparative claims with evidence IDs (Foundry model or rules)
       Skeptic       recomputes every claim in code: verified / corrected / rejected
                     -> rejected claims go back to Tactics for one revision round
       Narrator      explains only verified claims (Foundry model or template);
                     a grounding guard blocks any number not found in a verified claim
  -> Next.js dashboard: live timeline, intelligence desk, Agent room with trace
```

Models may draft claims and wording, but they never supply numbers: every figure a viewer sees is recomputed from the event log, and no agent can read events after the current minute.


## Next steps before submission

- Run the agents against a real Foundry deployment and tune the Tactics prompt.
- Deploy (Azure Container Apps for the API, Container Apps or Static Web Apps for the frontend).
- Film the under-2-minute demo around a rejected claim being revised in the Agent room.


## Integrity and limitations

No real Premier League match data, footage, player performance claims or team identities appear in this demo. The fabricated xG numbers illustrate interface behavior and are **not a trained xG model**. The synthetic feed is an educational demo; don't imply it is a commercially validated match-tracking system. Reading only observed events at the current simulated minute prevents future leakage.

Built after the hackathon registration period opened on September 29, 2026.
