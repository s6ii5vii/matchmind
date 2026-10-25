# MatchMind

**Hear the take. See the data.** Five AI agents watch a football match with you. A Pundit says what everyone's thinking; a Skeptic checks every take against every pass, tackle and shot, and tells you whether it holds up. Ask anything, in plain English.

Built for **Inside the Game: Microsoft Premier League Hackathon 2026**, targeting **Best Multi-Agent System**.

**Try it live:** https://matchmind.politesky-f0495435.swedencentral.azurecontainerapps.io (runs on Azure Container Apps; the first visit after a quiet spell can take a few seconds to wake up)

## What you can do

| Feature | What it does |
|---|---|
| **Three matches** | Switch between a 2-1 decided by a pressing spell, a 2-3 comeback and a goalless game won by the keepers. Each has added time (45+2', 90+5'), substitutions, injuries and VAR checks. |
| **Agent room** | Ask a question ("Why did Riverside lose control after 60?"). Watch the five agents work live, then get **the answer**: what the question assumed, which takes hold up, which don't, and why, each next to the data. |
| **Key moments** | Every goal and big chance as a short story: *"I. Brown loses the ball near their own goal → a 4-pass move, set up by M. Diallo → A. Okafor scores"*. Click one to replay the move on the pitch, or ask the agents what led to it. |
| **Player rating & duel** | Every player gets a rating out of 10 based on the moments they drove and the ones they caused, not just goals and assists. Compare any two players side by side. A hard-working defender can outrate a striker who scored. |
| **For everyone** | One switch for the whole page: *New to football* (no jargon, short answer first), *Fan*, or *Analyst* (numbers and evidence events). |
| **Follow a question** | Follow up to three questions and their answers refresh as the match plays on. Your recent questions are kept in your browser, with no sign-up. |
| **Match by the numbers** | Possession, shots, xG, passing, pressing, final-third entries, recoveries, saves, corners, fouls and cards, updating as the match plays. |

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

**Safeguards:** every number a viewer sees is recomputed from the event log. The Pundit isn't allowed to quote numbers. A grounding guard throws out any Narrator answer containing a number the Skeptic didn't produce. If a model call fails or takes longer than 25 seconds, the agents fall back to rules and say so in the trace.

**Cost protection:** each visitor can ask up to 30 questions a minute, repeated questions are answered from a cache (the agents' steps are replayed), and model-written answers are capped at 400 an hour across all visitors. Past the cap the rule-based agents answer for free. All three limits can be changed with environment variables (`MATCHMIND_RATE_LIMIT`, `MATCHMIND_MODEL_BUDGET`, `MATCHMIND_MODEL_TIMEOUT`).

## The player rating

Most ratings add up a player's actions. MatchMind's asks **who drove the moments that mattered, and who caused the bad ones**:

- **Chances:** every move that ends in a shot shares its value (10 points for a goal, otherwise 10 × xG) between:
  - the shooter (50%);
  - the player who set it up (25%);
  - the rest of the move, including whoever won the ball back to start it (25%).

  This shows who orchestrates.
- **Costly mistakes:** every chance the opponent creates straight after a player loses the ball is charged to that player.
- **Stopping chances:** a keeper's save earns 80% of the chance it stopped, a block 50%. Winning the ball or clearing it near your own goal is worth the danger it took away, the mirror image of moving the ball forward.
- **Everyday actions** count for less: passes and carries that move the ball towards goal, beating a defender, pressing that forces an error, losing the ball, fouls and bookings.

Each action is worth −10 to +10 impact points. The total becomes a rating that starts at 6.0 and moves with the match. Players earn tags such as *Orchestrator*, *Ball winner*, *Shot stopper* and *Costly mistakes*. Substitutes appear once they come on. The model is transparent and rule-based, in the spirit of action-value metrics like VAEP and expected threat.

## The match data

All clubs, players and events are **fictional**. [`backend/app/synthetic.py`](backend/app/synthetic.py) simulates three matches possession by possession, each from a fixed seed:

| Match | Result | Story |
|---|---|---|
| Northbridge City v Riverside United | 2-1 | Riverside's spell before half-time; Northbridge press them into mistakes after the hour |
| Ashford Rovers v Kingsport Athletic | 2-3 | Ashford race into a 2-0 lead; Kingsport take over after half-time and turn it round |
| Hollowmere FC v Stanton Vale | 0-0 | Hollowmere dominate the ball for an hour; both keepers keep it goalless |

Each match has about 1,900 events: passes, carries, dribbles, crosses, set pieces (corners, free kicks, throw-ins, goal kicks), pressing, tackles, interceptions, clearances, blocks, shots with xG, saves, keeper claims, fouls, yellow cards and offsides.

**Like real football, play stops.** Injuries, VAR checks, goal celebrations and substitutions stop the game, and the time lost becomes added time, announced at 45:00 and 90:00 (45+2', 90+5'). In real matches the team on top loses about 11 points of its share of play in the five minutes after an injury stoppage (we measured this in 102 stoppages), so the simulation breaks the momentum the same way. Substitutes bring fresh legs and press harder for ten minutes. Questions like "after 60", "since half-time" or "between 45+1 and 45+2" are read as football minutes.

It's calibrated against [StatsBomb Open Data](https://github.com/statsbomb/open-data) from the most recent men's football available there: 38 matches from the 2023/24 Bundesliga and Euro 2024. Only aggregate per-match averages are used, and a test keeps the three matches within range:

| Per match | Real (StatsBomb, 2023/24) | MatchMind (average of 3) |
|---|---|---|
| Passes / completion | 1,076 / 85% | 936 / 82% |
| Shots / xG | 26.4 / 2.8 | 24.7 / 2.8 |
| Pressures | 297 | 299 |
| Interceptions / tackles | 17 / 31 | 18 / 33 |
| Fouls / yellow cards | 23 / 4.1 | 26 / 4.7 |
| Corners / crosses | 10.7 / 23 | 11 / 24 |
| Saves / clearances | 6.2 / 38 | 6.0 / 36 |
| Possessions | 157 | 161 |
| Substitutions / injury stoppages | 9.1 / 4.4 | 8.3 / 5.0 |
| Added time (1st / 2nd half) | +2.3 / +4.9 | +2.7 / +5.0 |

The matches are in [`data/`](data/) as CSV (opens in Excel) and JSON, with a guide to every column. No real Premier League data or footage is used, and xG values are illustrative, not a trained model.

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

Then pick a match, drag the timeline to a minute, and ask a question or click a key moment.

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

The tests cover: no future events leaking into any feature, the Skeptic's verdicts, the revision loop, the grounding guard, the Pundit being usually right (not a straw man), plain-language mode having no jargon, the rating's range and fairness, key moments, every match, added time and stoppages, the rate limit, cache, model budget and timeout, the streaming endpoint, and the simulation staying close to real match averages.

A browser test ([`frontend/e2e/smoke.mjs`](frontend/e2e/smoke.mjs)) clicks through the whole app in Chromium. It runs on GitHub Actions for every change, and locally with the app running:

```powershell
cd frontend
npm install --no-save playwright; npx playwright install chromium
$env:APP_URL="http://127.0.0.1:8000"; node e2e/smoke.mjs
```

## API

Every endpoint takes `match` (`northbridge-riverside`, `ashford-kingsport` or `hollowmere-stanton`; the first is the default). Minutes are minutes of play from kick-off, including added time, so the timeline runs past 90; `/api/config` gives the label for each (`45+2'`, `90+4'`).

| Endpoint | What it returns |
|---|---|
| `GET /api/matches` | The matches you can switch between |
| `GET /api/config?match=` | Teams, suggested questions, match length, added time, minute labels, active model provider |
| `GET /api/state?minute=&match=` | Score, stats and recent events up to that minute |
| `POST /api/analyze` | The agents' answer: `{minute, mode, focus, question, match}` → answer, checked takes, trace |
| `POST /api/analyze/stream` | The same, streamed: each agent step as it happens (newline-delimited JSON), then the result |
| `GET /api/moments?minute=&match=` | Goals and big chances so far, with each move's path |
| `GET /api/players?minute=&match=` | Every player's rating, impact points and biggest moments |
| `GET /api/compare?a=&b=&minute=&mode=&match=` | Two players side by side, with a verdict |
| `GET /api/events?minute=&match=` | Raw events up to that minute |

## Project layout

```
backend/app/
  synthetic.py     match simulator (three fictional matches, seeded, calibrated)
  analysis.py      match stats
  agents/          the five agents and their Agent Framework workflow
  players.py       player rating
  moments.py       key moments
  main.py          FastAPI app
  export.py        writes data/ (python -m app.export)
frontend/app/      Next.js dashboard (served by the API in the container)
Dockerfile         builds the dashboard, then runs everything in one container
frontend/e2e/      browser test
data/              the matches as CSV and JSON
```
