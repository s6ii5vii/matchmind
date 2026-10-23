# MatchMind

**Hear the take. See the data.** Five AI agents watch a football match with you. A Pundit says what everyone's thinking; a Skeptic checks every take against every pass, tackle and shot, and tells you whether it holds up. Ask anything, in plain English.

Built for **Inside the Game: Microsoft Premier League Hackathon 2026**, targeting **Best Multi-Agent System**.

## What you can do

| Feature | What it does |
|---|---|
| **Agent room** | Ask a question ("Why did Riverside lose control after 60?"). Watch the five agents work live, then get **the answer**: what the question assumed, which takes hold up, which don't, and why, each next to the data. |
| **Key moments** | Every goal and big chance as a short story: *"I. Brown loses the ball near their own goal → a 4-pass move, set up by M. Diallo → A. Okafor scores"*. Click one to replay the move on the pitch, or ask the agents what led to it. |
| **Player rating & duel** | Every player gets a rating out of 10 based on the moments they drove and the ones they caused, not just goals and assists. Compare any two players side by side. A hard-working defender can outrate a striker who scored. |
| **For everyone** | One switch for the whole page: *New to football* (no jargon, short answer first), *Fan*, or *Analyst* (numbers and evidence events). |
| **Match by the numbers** | Possession, shots, xG, passing, pressing, final-third entries and ball recoveries, updating as the match plays. |

Everything follows the match clock: scrub or play the timeline, and no feature ever uses events that haven't happened yet.

## The agents

Five agents run as a [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) workflow:

```
Question ─▶ Orchestrator ─▶ Stats ─▶ Pundit ─▶ Skeptic ─▶ Narrator ─▶ Answer
                                       ▲          │
                                       └──────────┘  busted takes go back for one rethink
```

| Agent | Job |
|---|---|
| **Orchestrator** | Turns the question into a team, a stretch of minutes and the stats to check, and picks out any assumption in it ("…lose control" assumes they lost control). |
| **Stats** | Counts everything that happened in that stretch from the event log. Code, no AI. |
| **Pundit** | Gives confident takes from what a viewer just saw (the last few minutes, no stats), the way a TV pundit would. Usually right, sometimes caught out by recency bias. AI model, or rules when offline. |
| **Skeptic** | Checks every take, and the question's assumption, against the whole stretch: **holds up**, **half-right** (numbers corrected), **not enough evidence**, or **doesn't hold up**. Code, no AI, so it can't be talked round. |
| **Narrator** | Writes the answer for the chosen audience from the checked takes. AI model, or a template when offline. |

**Safeguards:** every number a viewer sees is recomputed from the event log. The Pundit isn't allowed to quote numbers. A grounding guard throws out any Narrator answer containing a number the Skeptic didn't produce. If a model call fails, the agents fall back to rules and say so in the trace.

## The player rating

Most ratings add up a player's actions. MatchMind's asks **who drove the moments that mattered, and who caused the bad ones**:

- **Chances:** every move that ends in a shot shares its value (10 points for a goal, otherwise 10 × xG) between:
  - the shooter (50%);
  - the player who set it up (25%);
  - the rest of the move, including whoever won the ball back to start it (25%).

  This shows who orchestrates.
- **Costly mistakes:** every chance the opponent creates straight after a player loses the ball is charged to that player.
- **Everyday actions** count for less: passes that move the ball towards goal, ball wins (double near your own goal), pressing that forces an error, losing the ball, fouls.

Each action is worth −10 to +10 impact points. The total becomes a rating that starts at 6.0 and moves with the match. Players earn tags such as *Orchestrator*, *Ball winner* and *Costly mistakes*. The model is transparent and rule-based, in the spirit of action-value metrics like VAEP and expected threat.

## The match data

All clubs, players and events are **fictional**. [`backend/app/synthetic.py`](backend/app/synthetic.py) simulates a full match possession by possession from a fixed seed:
- about 1,500 events over 220 possessions, with 11-player squads;
- passes with start and end positions and receivers;
- pressing that forces errors, interceptions, tackles, fouls, shots with xG, and time-based possession.

The match has a story the agents can find: Riverside's spell before half-time, and Northbridge's pressing spell after the hour.

It's calibrated against [StatsBomb Open Data](https://github.com/statsbomb/open-data). We measured 20 Premier League 2015/16 matches and tuned towards their per-match averages. Only those aggregate numbers are used, and a test keeps the simulation within range:

| Per match | Real (StatsBomb, 20 PL matches) | MatchMind |
|---|---|---|
| Shots | 24.6 | 25 |
| xG | 2.2 | 2.2 |
| Pass completion | 76% | 78% |
| Pressures | 306 | 302 |
| Interceptions | 25 | 30 |
| Tackles | 42 | 52 |
| Fouls | 25 | 31 |
| Possessions | 183 | 219 |

The match is in [`data/`](data/) as CSV (opens in Excel) and JSON, with a guide to every column. No real Premier League data or footage is used, and xG values are illustrative, not a trained model.

## Run it

Requires Python 3.10+ and Node.js 20+.

```powershell
# Terminal 1: backend (http://127.0.0.1:8000, API docs at /docs)
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# Terminal 2: frontend (http://localhost:3000)
cd frontend
npm install
npm run dev
```

Then click **Ask the agents**, drag the timeline to a minute, and ask a question or click a key moment.

### AI models (optional)

Without credentials everything works offline with rule-based agents. To let an AI model drive the Pundit and Narrator, copy `backend/.env.example` to `backend/.env`, fill in **one** provider, and restart the backend. `.env` is git-ignored, so keys never reach GitHub.

```ini
# Microsoft Foundry (Azure OpenAI deployment, e.g. gpt-5.4-mini)
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.cognitiveservices.azure.com
AZURE_OPENAI_DEPLOYMENT=YOUR-DEPLOYMENT-NAME
AZURE_OPENAI_API_KEY=YOUR_API_KEY
# AZURE_OPENAI_API_VERSION=2025-04-01-preview   (the default; match your deployment's Target URI)

# or Nebius Token Factory (OpenAI-compatible)
NEBIUS_API_KEY=YOUR_API_KEY
NEBIUS_MODEL=openai/gpt-oss-120b   # any Token Factory model that supports tool calling
```

If both are set, Foundry is used unless `MATCHMIND_PROVIDER=nebius`. The Agent room header shows which provider answered.

### Deploy

One container serves the dashboard and the API at a single URL. [DEPLOY.md](DEPLOY.md) walks through deploying it to Azure Container Apps.

### Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests cover: no future events leaking into any feature, the Skeptic's verdicts, the revision loop, the grounding guard, the Pundit being usually right (not a straw man), plain-language mode having no jargon, the rating's range and fairness, key moments, the streaming endpoint, and the simulation staying close to real match averages.

## API

| Endpoint | What it returns |
|---|---|
| `GET /api/state?minute=` | Score, stats and recent events up to that minute |
| `POST /api/analyze` | The agents' answer: `{minute, mode, focus, question}` → answer, checked takes, trace |
| `POST /api/analyze/stream` | The same, streamed: each agent step as it happens (newline-delimited JSON), then the result |
| `GET /api/moments?minute=` | Goals and big chances so far, with each move's path |
| `GET /api/players?minute=` | Every player's rating, impact points and biggest moments |
| `GET /api/compare?a=&b=&minute=&mode=` | Two players side by side, with a verdict |
| `GET /api/events?minute=` | Raw events up to that minute |
| `GET /api/config` | Teams and which model provider is active |

## Project layout

```
backend/app/
  synthetic.py     match simulator (fictional, seeded, calibrated)
  analysis.py      match stats
  agents/          the five agents and their Agent Framework workflow
  players.py       player rating
  moments.py       key moments
  main.py          FastAPI app
  export.py        writes data/ (python -m app.export)
frontend/app/      Next.js dashboard (served by the API in the container)
Dockerfile         builds the dashboard, then runs everything in one container
data/              the match as CSV and JSON
```
