# MatchMind — synthetic live football intelligence

An original hackathon MVP built for **Inside the Game: Microsoft Premier League Hackathon (2026)**.

## What works in v0.1

- A deterministic, explicitly **synthetic** 90-minute event stream (passes, pressure events, tackles, turnovers, shots, goals).
- Auditable event-based match statistics, including goals, pass completion, shots, synthetic xG, pressures, and **event share (not possession time)**.
- Explainable tactical observations with linked evidence event IDs.
- Live playback timeline, tactical feed, favorite-team focus, fan/analyst modes, goal milestones.
- Optional Azure OpenAI model call through Microsoft Foundry to rewrite verified evidence into a short narrative.
- Tests protecting against future-event leakage.

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

## Optional: Microsoft Foundry narration

This is an **optional** Azure OpenAI-compatible deployment inside Microsoft Foundry, *not yet a full multi-agent workflow*. The dashboard remains usable without cloud access.

1. Create or choose a model deployment exposed through the Azure OpenAI API.
2. Set these environment variables in the **backend terminal** (replace placeholders):

```powershell
$env:AZURE_OPENAI_ENDPOINT='https://YOUR-RESOURCE.openai.azure.com'
$env:AZURE_OPENAI_DEPLOYMENT='YOUR-DEPLOYMENT-NAME'
$env:AZURE_OPENAI_API_KEY='YOUR_API_KEY'
```

3. Restart the backend, then click **AI recap** in the dashboard.

Never commit keys, secrets or `.env` files to GitHub. Some Microsoft Foundry endpoints use a different SDK/protocol and will need an adapter; do not assume any Foundry URL works with this example.

## Architecture

```
Synthetic event generator (seeded Python)
  -> deterministic analytics + windowed tactical rules (auditable evidence IDs)
  -> FastAPI /api/state, /api/events
  -> Next.js live dashboard, modes, timeline
  -> optional /api/narrate through Azure OpenAI deployment
```

## Next phase for a credible competition entry

- Replace single-step narration with **specialized cooperating agents**: tactical analyst, evidence checker, broadcast storyteller.
- Wire model orchestration into Microsoft Agent Framework / Foundry with logged handoffs and retries.
- Validate generated claims against evidence IDs; reject ungrounded stats.
- Upgrade data realism (possessions/durations, field positions, passing networks, momentum methodology).
- Add multilingual outputs, overlay-ready JSON, and optional real-time Server-Sent Events.
- Deploy a free-to-access demo, film a <2-minute video, and publish public GitHub repo before deadline.

## Integrity and limitations

No real Premier League match data, footage, player performance claims or team identities appear in this demo. The fabricated xG numbers illustrate interface behavior and are **not a trained xG model**. The synthetic feed is an educational demo; don't imply it is a commercially validated match-tracking system. Reading only observed events at the current simulated minute prevents future leakage.

Built after the hackathon registration period opened on September 29, 2026.
