# MatchMind match data

A full **fictional** match (Northbridge City vs Riverside United), simulated possession by possession by
`backend/app/synthetic.py`. No real Premier League data. Regenerate with `python -m app.export` from `backend/`.

- `match_events.csv`: one row per event, opens in Excel or Google Sheets.
- `match.json`: the same events plus teams, squads and goals.

About 1,500 events over 220 possessions. Per-match totals are calibrated against
[StatsBomb Open Data](https://github.com/statsbomb/open-data) averages (see the main README).

| Column | Meaning |
|---|---|
| `id` | Event ID (`SIM-0001`...). The agents cite these as evidence. |
| `clock`, `minute`, `second`, `t` | Elapsed time as on TV (71:36), the match minute it falls in (72), second within that minute, seconds since kick-off |
| `team` | `home` or `away`: the team of the player making the action |
| `player`, `number`, `position` | Who did it (GK, DF, MF, FW) |
| `type` | `pass`, `pressure`, `tackle`, `interception`, `recovery`, `shot`, `turnover`, `foul` |
| `outcome` | `complete`/`incomplete` (pass), `won`/`lost` (tackle), `saved`/`off_target`/`blocked`/`goal` (shot)... |
| `x`, `y` | Where it happened, 0-100. Home attack towards x=100, away towards x=0 |
| `end_x`, `end_y` | Where a pass ended |
| `zone` | `defensive`, `middle` or `attacking` third, from the acting team's point of view |
| `receiver` | Who received a completed pass |
| `under_pressure` | Whether an opponent was pressing at the time |
| `distance_m`, `difficulty` | Pass length in metres and how hard it was (0-1) |
| `xg`, `body_part` | Shot quality (expected goals) and foot/head |
| `is_goal` | True for the three goals (18', 42', 72') |
| `possession`, `possession_team` | Which possession (passing move) the event belongs to, and who had the ball |
| `possession_end` | On the last event of a move: how it ended (`intercepted`, `tackled`, `shot saved`, `goal`...) |
