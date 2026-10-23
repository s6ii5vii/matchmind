"""Player impact: credit for everything a player does, not just goals and assists.

Every action is valued in goal-equivalents (how much it changed the chance of a goal), then
shown as impact points (x100). It's a transparent, rule-based model in the spirit of
action-value metrics such as VAEP and expected threat, not a trained model.
"""

import math

from .synthetic import EVENTS, SQUADS, TEAMS

CATEGORIES = ("scoring", "creating", "progression", "defending", "ball_security")
CATEGORY_LABELS = {
    "scoring": "Scoring", "creating": "Creating chances", "progression": "Moving the ball forward",
    "defending": "Defending", "ball_security": "Looking after the ball",
}
# how much an action matters by where it happens, from the acting player's point of view
DANGER = {"defensive": 2.0, "middle": 1.3, "attacking": 1.0}
LOST = {"intercepted", "pass misplaced", "pass out of play", "dispossessed", "tackled", "miscontrol"}


def threat(depth: float) -> float:
    """Rough value of having the ball at this depth (0 = own goal line, 100 = opponent's)."""
    return 0.003 * math.exp(depth / 22)


def depth(e: dict, x: float) -> float:
    return x if e["team"] == "home" else 100 - x


def _blank(team: str, number: int, position: str, name: str) -> dict:
    return {
        "name": name, "team": team, "team_name": TEAMS[team]["name"], "number": number, "position": position,
        "values": dict.fromkeys(CATEGORIES, 0.0),
        "counts": {"goals": 0, "shots": 0, "xg": 0.0, "key_passes": 0, "assists": 0, "passes": 0,
                   "passes_completed": 0, "progressive_passes": 0, "interceptions": 0, "tackles_won": 0,
                   "recoveries": 0, "pressures": 0, "forced_errors": 0, "times_lost_ball": 0, "fouls": 0},
        "moments": [],  # (value, event id, description)
    }


def player_impact(minute: int = 90) -> dict[str, dict]:
    """Impact of every player using only events up to this minute."""
    events = [e for e in EVENTS if e["minute"] <= minute]
    players = {name: _blank(side, number, position, name)
               for side, squad in SQUADS.items() for number, position, name in squad}

    def credit(name: str, category: str, value: float, e: dict, what: str) -> None:
        p = players[name]
        p["values"][category] += value
        p["moments"].append((value, e["id"], f"{e['clock']} {what}"))

    for i, e in enumerate(events):
        p, c = players[e["player"]], players[e["player"]]["counts"]
        danger = DANGER[e["zone"]]
        if e["type"] == "shot":
            c["shots"] += 1
            c["xg"] += e["xg"]
            if e["is_goal"]:
                c["goals"] += 1
                credit(e["player"], "scoring", 0.8, e, "scored")
            else:
                credit(e["player"], "scoring", 0.3 * e["xg"], e, f"shot ({e['xg']:.2f} xG)")
            # the pass that set it up
            setup = next((s for s in reversed(events[max(0, i - 4):i])
                          if s["type"] == "pass" and s["outcome"] == "complete" and s["team"] == e["team"]
                          and s["possession"] == e["possession"] and s["receiver"] == e["player"]), None)
            if setup:
                players[setup["player"]]["counts"]["key_passes"] += 1
                if e["is_goal"]:
                    players[setup["player"]]["counts"]["assists"] += 1
                credit(setup["player"], "creating", 0.6 * e["xg"] + (0.4 if e["is_goal"] else 0), setup,
                       "assist" if e["is_goal"] else "set up a shot")
        elif e["type"] == "pass":
            c["passes"] += 1
            if e["outcome"] == "complete":
                c["passes_completed"] += 1
                gain = threat(depth(e, e["end_x"])) - threat(depth(e, e["x"]))
                if gain > 0.004:
                    c["progressive_passes"] += 1
                    credit(e["player"], "progression", gain, e, "moved the ball forward")
        elif e["type"] in ("interception", "tackle", "recovery") and e["outcome"] == "won":
            key = {"interception": "interceptions", "tackle": "tackles_won", "recovery": "recoveries"}[e["type"]]
            c[key] += 1
            base = 0.012 if e["type"] == "recovery" else 0.035
            credit(e["player"], "defending", base * danger, e, {"interceptions": "interception",
                   "tackles_won": "tackle won", "recoveries": "won the ball back"}[key])
        elif e["type"] == "pressure":
            c["pressures"] += 1
            # did the opponent lose the ball within a few seconds of this press?
            forced = next((n for n in events[i + 1:i + 4] if n["t"] - e["t"] <= 6
                           and n["possession_team"] != e["team"] and n["possession_end"] in LOST), None)
            if forced:
                c["forced_errors"] += 1
                credit(e["player"], "defending", 0.02 * danger, e, "pressed and forced an error")
        elif e["type"] == "foul":
            c["fouls"] += 1
            credit(e["player"], "ball_security", -0.02, e, "gave away a foul")

        if e["possession_end"] in LOST and e["team"] == e["possession_team"]:
            c["times_lost_ball"] += 1
            credit(e["player"], "ball_security", -0.025 * danger, e, "lost the ball")

    for p in players.values():
        p["counts"]["xg"] = round(p["counts"]["xg"], 2)
        p["values"] = {k: round(100 * v, 1) for k, v in p["values"].items()}
        p["impact"] = round(sum(p["values"].values()), 1)
        p["moments"] = [{"event_id": i, "what": w, "points": round(100 * v, 1)}
                        for v, i, w in sorted(p["moments"], key=lambda m: -abs(m[0]))[:4]]
    return players


def ranking(minute: int = 90) -> list[dict]:
    return sorted(player_impact(minute).values(), key=lambda p: -p["impact"])


ROLE = {"GK": "goalkeeper", "DF": "defender", "MF": "midfielder", "FW": "forward"}
def n(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else plural or word + 's'}"


EVIDENCE = {
    "scoring": lambda c: f"{n(c['goals'], 'goal')} from {n(c['shots'], 'shot')} ({c['xg']:.2f} xG)",
    "creating": lambda c: f"{n(c['key_passes'], 'pass', 'passes')} that set up a shot, {n(c['assists'], 'assist')}",
    "progression": lambda c: f"{n(c['progressive_passes'], 'pass', 'passes')} that moved the ball forward",
    "defending": lambda c: f"{n(c['interceptions'], 'interception')}, {n(c['tackles_won'], 'tackle')} won, "
                           f"{n(c['recoveries'], 'ball')} won back, {n(c['forced_errors'], 'error')} forced by pressing",
    "ball_security": lambda c: f"lost the ball {n(c['times_lost_ball'], 'time')}, {n(c['fouls'], 'foul')}",
}
PLAIN_EVIDENCE = {
    "scoring": lambda c: f"scored {n(c['goals'], 'goal')} and had {n(c['shots'], 'shot')}",
    "creating": lambda c: f"set up {n(c['key_passes'], 'shot')} for teammates",
    "progression": lambda c: f"moved the ball towards goal {n(c['progressive_passes'], 'time')}",
    "defending": lambda c: f"won the ball back {n(c['interceptions'] + c['tackles_won'] + c['recoveries'], 'time')}",
    "ball_security": lambda c: f"lost the ball only {n(c['times_lost_ball'], 'time')}",
}


def compare(a: str, b: str, minute: int = 90, mode: str = "fan") -> dict:
    players = player_impact(minute)
    if a not in players or b not in players:
        raise KeyError("Unknown player")
    pa, pb = players[a], players[b]
    edges = sorted(CATEGORIES, key=lambda k: -abs(pa["values"][k] - pb["values"][k]))
    winner, loser = (pa, pb) if pa["impact"] >= pb["impact"] else (pb, pa)
    gap = winner["impact"] - loser["impact"]
    main = next((k for k in edges if winner["values"][k] > loser["values"][k]), edges[0])
    simple = mode == "simple"
    detail = (PLAIN_EVIDENCE if simple else EVIDENCE)[main](winner["counts"])
    if gap < 3:
        verdict = (f"Too close to call: {winner['name']} and {loser['name']} have had about the same impact "
                   f"({winner['impact']:g} vs {loser['impact']:g}).")
    elif simple:
        verdict = (f"{winner['name']} has helped their team more so far. The biggest difference: "
                   f"{winner['name']} {detail}.")
    else:
        verdict = (f"{winner['name']} ({ROLE[winner['position']]}) has had more impact: {winner['impact']:g} vs "
                   f"{loser['impact']:g} impact points. The biggest edge is {CATEGORY_LABELS[main].lower()}: "
                   f"{detail}.")
        if loser["values"]["scoring"] > winner["values"]["scoring"] and loser["counts"]["goals"]:
            verdict += f" {loser['name']} scored, but goals aren't the whole story."
    return {"minute": minute, "a": pa, "b": pb, "winner": None if gap < 3 else winner["name"],
            "verdict": verdict, "categories": [{"key": k, "label": CATEGORY_LABELS[k]} for k in CATEGORIES]}
