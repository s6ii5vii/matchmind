"""MatchMind player rating: who drove the moments that mattered, and who caused the bad ones.

Most ratings add up a player's actions. This one starts from the match's moments:

- Every move that ends in a shot is a *chance*. Its value (10 x xG, or 10 for a goal) is shared
  between the players who made it: the shooter, the player who set them up, everyone else who
  passed in the move, and whoever won the ball back to start it. That shows who orchestrates.
- Every chance the opponent creates straight after a player loses the ball is charged to that
  player. That shows who causes the bad moments.
- Everyday actions still count, for less: passes that move the ball towards goal, winning the ball
  back (worth more near your own goal), pressing that forces an error, losing the ball, fouls.

Each action is worth between -10 and +10 impact points (10 points = one goal's worth). The total
becomes a rating out of 10 that starts at 6.0 and moves with the match, like familiar ratings.
It's transparent and rule-based, not a trained model.
"""

import math

from .synthetic import EVENTS, SQUADS, TEAMS

CATEGORIES = ("chances", "build_up", "defending", "ball_security", "costly")
CATEGORY_LABELS = {
    "chances": "Driving the team's chances", "build_up": "Moving the ball forward",
    "defending": "Winning the ball back", "ball_security": "Looking after the ball",
    "costly": "Mistakes that led to chances",
}
LOST = {"intercepted", "pass misplaced", "pass out of play", "dispossessed", "tackled", "miscontrol"}
WINS = {"interception", "tackle", "recovery"}
# where it happens matters: mistakes and ball wins near your own goal count double
DANGER = {"defensive": 2.0, "middle": 1.3, "attacking": 1.0}
SHARES = {"shooter": 0.50, "creator": 0.25, "others": 0.25}
BLAME = 0.6  # a defence can still stop a chance after a loose pass, so the passer carries most, not all
RATING_BASE, RATING_SCALE = 6.0, 0.12


def other(team: str) -> str:
    return "away" if team == "home" else "home"


def threat(depth: float) -> float:
    """Rough value of having the ball at this depth (0 = own goal line, 100 = opponent's), in points."""
    return 0.03 * math.exp(depth / 22)


def depth(team: str, x: float) -> float:
    return x if team == "home" else 100 - x


def cap(points: float) -> float:
    return max(-10.0, min(10.0, points))


def rating(points: float) -> float:
    return round(max(3.0, min(10.0, RATING_BASE + RATING_SCALE * points)), 1)


def _blank(team: str, number: int, position: str, name: str) -> dict:
    return {
        "name": name, "team": team, "team_name": TEAMS[team]["name"], "number": number, "position": position,
        "values": dict.fromkeys(CATEGORIES, 0.0),
        "counts": {"goals": 0, "assists": 0, "shots": 0, "xg": 0.0, "chances_involved": 0, "goals_involved": 0,
                   "team_chances": 0, "chances_after_loss": 0, "goals_after_loss": 0, "progressive_passes": 0,
                   "ball_wins": 0, "wins_near_own_goal": 0, "forced_errors": 0, "times_lost_ball": 0,
                   "fouls": 0},
        "moments": [],  # (points, event id, description)
    }


def player_impact(minute: int = 90) -> dict[str, dict]:
    """Every player's impact using only events up to this minute."""
    events = [e for e in EVENTS if e["minute"] <= minute]
    players = {name: _blank(side, number, position, name)
               for side, squad in SQUADS.items() for number, position, name in squad}

    def credit(name: str, category: str, points: float, e: dict, what: str) -> None:
        points = cap(points)
        players[name]["values"][category] += points
        players[name]["moments"].append((points, e["id"], f"{e['clock']} {what}"))

    possessions: dict[int, list[dict]] = {}
    for e in events:
        possessions.setdefault(e["possession"], []).append(e)
    order = sorted(possessions)

    # 1. chances: shared between the players who made them, charged to whoever gave the ball away first
    for idx, pid in enumerate(order):
        move = possessions[pid]
        team = move[0]["possession_team"]
        shot = next((e for e in move if e["type"] == "shot" and e["team"] == team), None)
        if shot is None:
            continue
        goal = shot["is_goal"]
        value = 10.0 if goal else 10.0 * shot["xg"]
        what = "goal" if goal else "chance"
        for p in players.values():
            if p["team"] == team:
                p["counts"]["team_chances"] += 1

        creator = next((e for e in reversed(move) if e["type"] == "pass" and e["outcome"] == "complete"
                        and e["receiver"] == shot["player"] and e["t"] <= shot["t"]), None)
        starter = None
        if idx > 0:
            before = possessions[order[idx - 1]]
            starter = next((e for e in reversed(before) if e["team"] == team and e["type"] in WINS
                            and e["outcome"] == "won"), None)
        others = {e["player"] for e in move if e["team"] == team and e["type"] == "pass"
                  and e["player"] not in (shot["player"], creator and creator["player"])}
        if starter and starter["player"] not in (shot["player"], creator and creator["player"]):
            others.add(starter["player"])

        shares = {shot["player"]: SHARES["shooter"]}
        if creator:
            shares[creator["player"]] = SHARES["creator"]
        for name in others:
            shares[name] = SHARES["others"] / len(others)
        scale = 1.0 / sum(shares.values())  # nobody else involved: shooter and creator share it all
        for name, share in shares.items():
            role = ("scored" if goal else "shot") if name == shot["player"] else \
                ("assist" if goal else "set up the shot") if creator and name == creator["player"] else \
                ("won the ball back to start a " + what) if starter and name == starter["player"] else \
                ("part of the move for a " + what)
            credit(name, "chances", value * share * scale, shot, role)
            c = players[name]["counts"]
            c["chances_involved"] += 1
            c["goals_involved"] += goal
        players[shot["player"]]["counts"]["shots"] += 1
        players[shot["player"]]["counts"]["xg"] += shot["xg"]
        players[shot["player"]]["counts"]["goals"] += goal
        if creator and goal:
            players[creator["player"]]["counts"]["assists"] += 1

        # the bad moment for the other side: did someone give the ball away to start this?
        if idx > 0:
            before = possessions[order[idx - 1]]
            loser_team = other(team)
            ended = next((e["possession_end"] for e in reversed(before) if e["possession_end"]), None)
            if before[0]["possession_team"] == loser_team and ended in LOST:
                culprit = next((e for e in reversed(before) if e["team"] == loser_team), None)
                if culprit:
                    credit(culprit["player"], "costly", -BLAME * value, culprit,
                           f"lost the ball, then {TEAMS[team]['name']} had a {what}")
                    players[culprit["player"]]["counts"]["chances_after_loss"] += 1
                    players[culprit["player"]]["counts"]["goals_after_loss"] += goal

    # 2. everyday actions
    for i, e in enumerate(events):
        c = players[e["player"]]["counts"]
        danger = DANGER[e["zone"]]
        if e["type"] == "pass" and e["outcome"] == "complete":
            gain = threat(depth(e["team"], e["end_x"])) - threat(depth(e["team"], e["x"]))
            if gain > 0.04:
                c["progressive_passes"] += 1
                credit(e["player"], "build_up", gain, e, "moved the ball forward")
        elif e["type"] in WINS and e["outcome"] == "won":
            c["ball_wins"] += 1
            c["wins_near_own_goal"] += e["zone"] == "defensive"
            base = 0.08 if e["type"] == "recovery" else 0.3
            what = "stopped an attack near goal" if e["zone"] == "defensive" else "won the ball back"
            credit(e["player"], "defending", base * danger, e, what)
        elif e["type"] == "pressure":
            forced = next((n for n in events[i + 1:i + 4] if n["t"] - e["t"] <= 6
                           and n["possession_team"] != e["team"] and n["possession_end"] in LOST), None)
            if forced:
                c["forced_errors"] += 1
                credit(e["player"], "defending", 0.2 * danger, e, "pressed and forced an error")
        elif e["type"] == "foul":
            c["fouls"] += 1
            credit(e["player"], "ball_security", -0.2, e, "gave away a foul")
        if e["possession_end"] in LOST and e["team"] == e["possession_team"]:
            c["times_lost_ball"] += 1
            credit(e["player"], "ball_security", -0.25 * danger, e, "lost the ball")

    for p in players.values():
        p["counts"]["xg"] = round(p["counts"]["xg"], 2)
        p["values"] = {k: round(v, 1) for k, v in p["values"].items()}
        p["impact"] = round(sum(p["values"].values()), 1)
        p["rating"] = rating(p["impact"])
        p["moments"] = [{"event_id": i, "what": w, "points": round(v, 1)}
                        for v, i, w in sorted(p["moments"], key=lambda m: -abs(m[0]))[:4]]
    _tag(players)
    return players


def _tag(players: dict[str, dict]) -> None:
    """A one-word read on each player's match, when something stands out."""
    for p in players.values():
        p["tag"] = None
    for team in TEAMS:
        squad = [p for p in players.values() if p["team"] == team]
        orchestrator = max(squad, key=lambda p: p["values"]["chances"])
        if orchestrator["values"]["chances"] >= 3:
            orchestrator["tag"] = "Orchestrator"
        wall = max(squad, key=lambda p: p["values"]["defending"])
        if wall["values"]["defending"] >= 3 and not wall["tag"]:
            wall["tag"] = "Ball winner"
        for p in squad:
            if p["values"]["costly"] <= -4 and not p["tag"]:
                p["tag"] = "Costly mistakes"


def ranking(minute: int = 90) -> list[dict]:
    return sorted(player_impact(minute).values(), key=lambda p: (-p["rating"], -p["impact"]))


ROLE = {"GK": "goalkeeper", "DF": "defender", "MF": "midfielder", "FW": "forward"}


def n(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else plural or word + 's'}"


def summary(p: dict, simple: bool = False) -> str:
    """The player's match in one line: the good moments they drove and the bad ones they caused."""
    c, team, opp = p["counts"], p["team_name"], TEAMS[other(p["team"])]["name"]
    parts = []
    if c["chances_involved"]:
        parts.append(f"was involved in {c['chances_involved']} of {team}'s {n(c['team_chances'], 'chance')}"
                     + (f" ({n(c['goals_involved'], 'goal')})" if c["goals_involved"] else ""))
    if c["ball_wins"]:
        near = c["wins_near_own_goal"]
        parts.append(f"won the ball back {n(c['ball_wins'], 'time')}"
                     + (f", {near} near their own goal" if near and not simple else ""))
    if c["chances_after_loss"]:
        parts.append(f"lost the ball before {n(c['chances_after_loss'], 'chance')} for {opp}"
                     + (f", including {n(c['goals_after_loss'], 'goal')}" if c["goals_after_loss"] else ""))
    return ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] if parts \
        else "hasn't had much of the ball yet"


def compare(a: str, b: str, minute: int = 90, mode: str = "fan") -> dict:
    players = player_impact(minute)
    if a not in players or b not in players:
        raise KeyError("Unknown player")
    pa, pb = players[a], players[b]
    simple = mode == "simple"
    for p in (pa, pb):
        p["summary"] = summary(p, simple)
    winner, loser = (pa, pb) if (pa["rating"], pa["impact"]) >= (pb["rating"], pb["impact"]) else (pb, pa)
    edges = sorted(CATEGORIES, key=lambda k: -abs(pa["values"][k] - pb["values"][k]))
    main = next((k for k in edges if winner["values"][k] > loser["values"][k]), edges[0])
    if abs(winner["rating"] - loser["rating"]) < 0.3:
        verdict = (f"Too close to call: {winner['name']} ({winner['rating']}) and {loser['name']} "
                   f"({loser['rating']}) have helped their teams about as much so far.")
    elif simple:
        verdict = (f"{winner['name']} has helped their team more ({winner['rating']} out of 10 vs "
                   f"{loser['rating']}). {winner['name']} {winner['summary']}.")
    else:
        verdict = (f"{winner['name']} ({ROLE[winner['position']]}) rates {winner['rating']}/10 to {loser['name']}'s "
                   f"{loser['rating']}. The biggest difference is {CATEGORY_LABELS[main].lower()}: "
                   f"{winner['name']} {winner['summary']}.")
        if loser["counts"]["goals"] and not winner["counts"]["goals"]:
            verdict += f" {loser['name']} scored, but goals aren't the whole story."
        elif loser["counts"]["chances_after_loss"] > winner["counts"]["chances_after_loss"]:
            lost = loser["counts"]
            verdict += (f" {loser['name']} lost the ball before {n(lost['chances_after_loss'], 'chance')} "
                        f"for {TEAMS[other(loser['team'])]['name']}.")
    return {"minute": minute, "a": pa, "b": pb,
            "winner": None if abs(winner["rating"] - loser["rating"]) < 0.3 else winner["name"],
            "verdict": verdict, "categories": [{"key": k, "label": CATEGORY_LABELS[k]} for k in CATEGORIES]}
