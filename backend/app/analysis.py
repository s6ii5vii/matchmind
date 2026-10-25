"""Auditable match aggregation and explainability engine.

These are deterministic computations and templates, NOT LLM-generated content.
Model-written narration lives in the agent workflow (app/agents).
"""

from .synthetic import EVENTS, TEAMS, current_match, label, match_meta


LOST_BALL = {"intercepted", "pass misplaced", "pass out of play", "dispossessed", "tackled", "miscontrol"}
RECOVERY = {"interception", "tackle", "recovery"}


def possession_seconds(events: list[dict]) -> dict:
    """Seconds on the ball per team, from the simulated possessions that start in these events."""
    spans: dict[int, list] = {}
    for e in events:
        span = spans.setdefault(e["possession"], [e["possession_team"], e["t"], e["t"]])
        span[1], span[2] = min(span[1], e["t"]), max(span[2], e["t"])
    seconds = {"home": 0, "away": 0}
    for team, first, last in spans.values():
        seconds[team] += last - first + 3
    return seconds


def final_third(e: dict) -> bool:
    """A completed pass into the attacking third (home attack towards x=100, away towards x=0)."""
    if e["type"] != "pass" or e["outcome"] != "complete" or e["end_x"] is None:
        return False
    return e["end_x"] > 66.7 and e["x"] <= 66.7 if e["team"] == "home" else e["end_x"] < 33.3 and e["x"] >= 33.3


def _team_stats(events: list[dict], team: str) -> dict:
    own = [e for e in events if e["team"] == team]
    passes = [e for e in own if e["type"] == "pass"]
    completed = sum(e["outcome"] == "complete" for e in passes)
    shots = [e for e in own if e["type"] == "shot"]
    seconds = possession_seconds(events)
    total = sum(seconds.values())
    return {
        "goals": sum(e["is_goal"] for e in own),
        "passes": len(passes),
        "completed_passes": completed,
        "pass_accuracy": round(100 * completed / len(passes), 1) if passes else None,
        "shots": len(shots),
        "xg": round(sum(e["xg"] or 0 for e in shots), 2),
        "pressures": sum(e["type"] == "pressure" for e in own),
        "tackles_won": sum(e["type"] == "tackle" and e["outcome"] == "won" for e in own),
        "recoveries": sum(e["type"] in RECOVERY and e["outcome"] == "won" for e in own),
        "turnovers": sum(e["possession_end"] in LOST_BALL for e in events if e["possession_team"] == team),
        "final_third_entries": sum(final_third(e) for e in passes),
        "saves": sum(e["type"] == "save" for e in own),
        "corners": sum(e["type"] == "pass" and e["pass_type"] == "corner" for e in own),
        "fouls": sum(e["type"] == "foul" for e in own),
        "yellow_cards": sum(e["type"] == "card" for e in own),
        "possession": round(100 * seconds[team] / total, 1) if total else None,
        "event_share": round(100 * len(own) / len(events), 1) if events else 0,
    }


def build_state(minute: int = 0, mode: str = "fan", focus: str = "home") -> dict:
    """State is derived strictly from actions at or before requested minute."""
    meta = match_meta()
    minute = max(0, min(meta["length"], int(minute)))
    mode = mode if mode in ("simple", "fan", "analyst") else "fan"
    focus = focus if focus in ("home", "away") else "home"
    observed = [e for e in EVENTS if e["minute"] <= minute]
    recent = [e for e in observed if minute - 10 < e["minute"] <= minute]
    key_moments = [e for e in observed if e["is_goal"]]
    return {
        "is_synthetic": True,
        "match": current_match().id,
        "minute": minute,
        "label": label(minute),
        "period": 1 if minute <= meta["first_half"] else 2,
        "length": meta["length"],
        "added": meta["added"],
        # added time is announced on the board at 45:00 and 90:00
        "announced": {"1": meta["added"][1] if minute >= 45 else None,
                      "2": meta["added"][2] if minute >= meta["first_half"] + 45 else None},
        "teams": dict(TEAMS),
        "score": {side: _team_stats(observed, side)["goals"] for side in TEAMS},
        "stats": {side: _team_stats(observed, side) for side in TEAMS},
        "recent_events": list(reversed(observed[-60:])),
        "goal_events": key_moments,
        "stoppages": list(reversed([e for e in observed if e["type"] in ("card", "substitution", "stoppage")])),
        "mode": mode,
        "focus": focus,
        "observed_event_count": len(observed),
        "recent_event_count": len(recent),
        "method": "Deterministic calculations over a simulated, fictional match. Possession is time on the ball.",
    }
