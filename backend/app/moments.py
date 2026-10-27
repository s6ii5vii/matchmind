"""Key moments: the goals and big chances, how each move was built, and who gave the ball away first.

Uses the same idea as the player rating: a chance is a move that ends in a shot, and an opponent
chance straight after a player loses the ball is that player's bad moment.
"""

from .players import LOST, WINS, other
from .synthetic import EVENTS, TEAMS, tidy

BIG_CHANCE_XG = 0.07


def _name(team: str) -> str:
    return TEAMS[team]["name"]


def key_moments(minute: int = 90) -> list[dict]:
    """Goals and big chances up to this minute, newest first."""
    events = [e for e in EVENTS if e["minute"] <= minute]
    possessions: dict[int, list[dict]] = {}
    for e in events:
        possessions.setdefault(e["possession"], []).append(e)
    order = sorted(possessions)
    moments = []
    for idx, pid in enumerate(order):
        move = possessions[pid]
        team = move[0]["possession_team"]
        shot = next((e for e in move if e["type"] == "shot" and e["team"] == team), None)
        if shot is None or not (shot["is_goal"] or shot["xg"] >= BIG_CHANCE_XG):
            continue
        before = possessions[order[idx - 1]] if idx > 0 else []
        won_by = next((e for e in reversed(before) if e["team"] == team and e["type"] in WINS
                       and e["outcome"] == "won"), None)
        ended = next((e["possession_end"] for e in reversed(before) if e["possession_end"]), None)
        culprit = next((e for e in reversed(before) if e["team"] == other(team)), None) \
            if before and before[0]["possession_team"] == other(team) and ended in LOST else None
        passes = [e for e in move if e["team"] == team and e["type"] == "pass" and e["outcome"] == "complete"
                  and e["t"] <= shot["t"]]
        creator = next((p for p in reversed(passes) if p["receiver"] == shot["player"]), None)

        goal = shot["is_goal"]
        stop = next((e for e in move if e["type"] in ("save", "block") and e["t"] >= shot["t"]), None)
        outcome = "scores" if goal else {
            "saved": f"is denied by {stop['player'] if stop else 'the keeper'}", "off_target": "shoots wide",
            "blocked": f"has the shot blocked by {stop['player']}" if stop else "has the shot blocked",
        }[shot["outcome"]]
        title = f"{shot['player']} {outcome}"
        story = [f"{n_passes(len(passes))} move" + (f", set up by {creator['player']}" if creator else "")]
        if culprit:
            story.insert(0, f"{culprit['player']} loses the ball"
                            + (" near their own goal" if culprit["zone"] == "defensive" else ""))
        elif won_by:
            story.insert(0, f"{won_by['player']} wins the ball back")

        path = ([{"x": won_by["x"], "y": won_by["y"], "player": won_by["player"], "kind": "win"}] if won_by else [])
        path += [{"x": p["x"], "y": p["y"], "player": p["player"], "kind": "pass"} for p in passes]
        path.append({"x": shot["x"], "y": shot["y"], "player": shot["player"], "kind": "goal" if goal else "shot"})

        moments.append({
            "id": shot["id"], "minute": shot["minute"], "label": shot["label"], "clock": shot["clock"], "team": team,
            "kind": "goal" if goal else "chance", "title": title, "story": " → ".join(story),
            "xg": shot["xg"], "shooter": shot["player"], "creator": creator["player"] if creator else None,
            "won_by": won_by["player"] if won_by else None, "lost_by": culprit["player"] if culprit else None,
            "lost_by_team": other(team) if culprit else None, "path": path,
            "stopped_by": stop["player"] if stop else None,
            "question": tidy(f"What led to {_name(team)}'s {'goal' if goal else 'chance'} at {shot['label']}?"),
            "event_ids": [e["id"] for e in move if e["t"] <= shot["t"]], "passes": len(passes),
        })
    return list(reversed(moments))


def n_passes(count: int) -> str:
    return "a one-pass" if count == 1 else "a quick" if count == 0 else f"a {count}-pass"


WORDS = {0: "straight away", 1: "one pass later", 2: "two passes later", 3: "three passes later",
         4: "four passes later", 5: "five passes later", 6: "six passes later"}


def moment_sentence(m: dict) -> str:
    """What happened, in one sentence: how the ball was won or lost, and what came of it."""
    team = _name(m["team"])
    if m["lost_by"]:
        start = f"{m['lost_by']} gave the ball away"
    elif m["won_by"]:
        start = f"{m['won_by']} won the ball back for {team}"
    else:
        start = f"{team} built a move"
    later = WORDS.get(m["passes"], f"{m['passes']} passes later")
    setup = f" (set up by {m['creator']})" if m["creator"] else ""
    outcome = m["title"].replace(" scores", " scored").replace(" is denied", " was denied") \
        .replace(" shoots wide", " shot wide").replace(" has the shot", " had the shot")
    return f"At {m['clock']}, {start}; {later}, {outcome}{setup}."


def moment_at(minute: int, asked: int, team: str | None = None) -> dict | None:
    """The key moment a question like "...at 72?" refers to (never one that hasn't happened yet)."""
    if asked > minute:
        return None
    return next((m for m in key_moments(minute) if m["minute"] == asked and (team is None or m["team"] == team)),
                None)
