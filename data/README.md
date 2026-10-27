# MatchMind match data

Three **fictional** matches, each simulated possession by possession by `backend/app/synthetic.py`. No real
Premier League data. Regenerate with `python -m app.export` from `backend/`.

| Match | Result | Story |
|---|---|---|
| `northbridge-riverside` | Northbridge City 2-1 Riverside United | Riverside's spell before half-time; Northbridge press them into mistakes after the hour |
| `ashford-kingsport` | Ashford Rovers 2-3 Kingsport Athletic | Ashford race into a 2-0 lead; Kingsport take over after half-time and turn it round |
| `hollowmere-stanton` | Hollowmere FC 0-0 Stanton Vale | Hollowmere dominate the ball against a deep block; both keepers keep it goalless |

For each match:

- `<match>.csv`: one row per event, opens in Excel or Google Sheets.
- `<match>.json`: the same events plus teams, squads, benches, added time and goals.

About 1,900 events over 160 possessions per match, with substitutions, injuries, VAR checks and added time.
Per-match totals are calibrated against [StatsBomb Open Data](https://github.com/statsbomb/open-data)
averages from recent men's football (2023/24 Bundesliga and Euro 2024, see the main README).

| Column | Meaning |
|---|---|
| `id` | Event ID (`SIM-0001`...). The agents cite these as evidence. |
| `period` | 1 or 2 (half) |
| `clock`, `label` | The TV clock (`47:13`, `92:05`) and the minute as football writes it (`72'`, `45+2'`, `90+4'`) |
| `minute`, `second`, `t` | Minute of play counted from kick-off including first-half added time (the app's timeline), second within it, seconds of play since kick-off |
| `team` | `home` or `away`: the team of the player making the action |
| `player`, `number`, `position` | Who did it (GK, DF, MF, FW) |
| `type` | `pass`, `carry`, `dribble`, `pressure`, `tackle`, `interception`, `recovery`, `clearance`, `block`, `shot`, `save`, `claim`, `turnover`, `foul`, `card`, `offside`, `substitution`, `stoppage` |
| `outcome` | `complete`/`incomplete` (pass, dribble), `won`/`lost` (tackle), `saved`/`off_target`/`blocked`/`goal` (shot), `yellow` (card), `off` (substitution), `injury`/`var_check` (stoppage)... |
| `x`, `y` | Where it happened, 0-100. Home attack towards x=100, away towards x=0 |
| `end_x`, `end_y` | Where a pass or carry ended |
| `zone` | `defensive`, `middle` or `attacking` third, from the acting team's point of view |
| `receiver` | Who received a completed pass; for a substitution, who came on |
| `pass_type` | Restarts and crosses: `kick_off`, `goal_kick`, `keeper`, `throw_in`, `free_kick`, `corner`, `cross` |
| `under_pressure` | Whether an opponent was pressing at the time |
| `distance_m`, `difficulty` | Pass length in metres and how hard it was (0-1) |
| `xg`, `body_part` | Shot quality (expected goals) and foot/head; on a save or block, the xG of the shot stopped |
| `is_goal` | True for goals |
| `duration_s` | How long play was stopped (injuries, VAR checks); stoppages become added time |
| `possession`, `possession_team` | Which possession (passing move) the event belongs to, and who had the ball |
| `possession_end` | On the last event of a move: how it ended (`intercepted`, `tackled`, `shot saved`, `goal`...) |
