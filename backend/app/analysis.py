"""Auditable match aggregation and explainability engine.

These are deterministic computations and templates, NOT LLM-generated content.
Model-written narration lives in the agent workflow (app/agents).
"""

from .synthetic import EVENTS, TEAMS


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
        "possession": round(100 * seconds[team] / total, 1) if total else None,
        "event_share": round(100 * len(own) / len(events), 1) if events else 0,
    }


def _evidence(events: list[dict], team: str, kind: str, limit: int = 4) -> list[str]:
    return [e["id"] for e in events if e["team"] == team and e["type"] == kind][-limit:]


def _insights(events: list[dict], minute: int, mode: str, focus: str) -> list[dict]:
    recent = [e for e in events if minute - 10 < e["minute"] <= minute]
    previous = [e for e in events if minute - 20 < e["minute"] <= minute - 10]
    focus_stats = _team_stats(recent, focus)
    other = "away" if focus == "home" else "home"
    other_stats = _team_stats(recent, other)
    previous_stats = _team_stats(previous, focus)
    team_name = TEAMS[focus]["name"]
    cards = []

    if minute < 5 or len(recent) < 4:
        return [{
            "title": "Waiting for match context",
            "body": "Let the simulated event stream build a few minutes of evidence before drawing tactical conclusions.",
            "evidence_ids": [], "kind": "neutral", "window": "No sufficient sample",
        }]

    if focus_stats["pressures"] >= 2 and focus_stats["pressures"] > other_stats["pressures"]:
        detailed = (f"{team_name} registered {focus_stats['pressures']} pressure events in the last 10 minutes "
                    f"versus {other_stats['pressures']} from the opposition. That is evidence of a higher pressing workload, "
                    "not proof of successful recoveries.")
        casual = f"{team_name} is applying more pressure lately. The match may be tilting in their direction."
        cards.append({
            "title": "Pressure rising", "body": detailed if mode == "analyst" else casual,
            "evidence_ids": _evidence(recent, focus, "pressure"),
            "kind": "pressure", "window": f"Minutes {max(1, minute - 9)}–{minute}",
        })

    if focus_stats["shots"] >= 2:
        cards.append({
            "title": "Attacking momentum",
            "body": (f"{team_name} has {focus_stats['shots']} shots and {focus_stats['xg']:.2f} synthetic xG "
                     "in the last 10 minutes. xG measures chance quality, not a guaranteed goal.") if mode == "analyst" else
                    f"{team_name} is finding shooting chances. The attack is becoming more dangerous.",
            "evidence_ids": _evidence(recent, focus, "shot"),
            "kind": "attack", "window": f"Minutes {max(1, minute - 9)}–{minute}",
        })

    if focus_stats["pass_accuracy"] is not None and previous_stats["pass_accuracy"] is not None:
        change = round(focus_stats["pass_accuracy"] - previous_stats["pass_accuracy"], 1)
        if change <= -12 and focus_stats["passes"] >= 4 and previous_stats["passes"] >= 4:
            cards.append({
                "title": "Passing under stress",
                "body": (f"{team_name}'s completion rate dropped {abs(change):.1f} percentage points across successive "
                         "10-minute windows. This indicates declining execution, but does not by itself identify the cause.") if mode == "analyst" else
                        f"{team_name} is completing fewer passes than earlier. They're struggling to keep their rhythm.",
                "evidence_ids": _evidence(recent, focus, "pass"),
                "kind": "warning", "window": f"Minutes {max(1, minute - 19)}–{minute}",
            })

    if not cards:
        cards.append({
            "title": "Match rhythm", "body": (f"Over the last 10 minutes, {team_name} produced "
              f"{focus_stats['passes']} passes, {focus_stats['shots']} shots and {focus_stats['pressures']} pressure events. "
              "These are observed counts rather than predictive claims.") if mode == "analyst" else
              f"{team_name} is building its play. Watch how they move the ball and create chances.",
            "evidence_ids": _evidence(recent, focus, "pass", 3),
            "kind": "neutral", "window": f"Minutes {max(1, minute - 9)}–{minute}",
        })
    return cards[:3]


def build_state(minute: int = 0, mode: str = "fan", focus: str = "home") -> dict:
    """State is derived strictly from actions at or before requested minute."""
    minute = max(0, min(90, int(minute)))
    mode = mode if mode in ("fan", "analyst") else "fan"
    focus = focus if focus in ("home", "away") else "home"
    observed = [e for e in EVENTS if e["minute"] <= minute]
    recent = [e for e in observed if minute - 10 < e["minute"] <= minute]
    key_moments = [e for e in observed if e["is_goal"]]
    return {
        "is_synthetic": True,
        "minute": minute,
        "teams": TEAMS,
        "score": {side: _team_stats(observed, side)["goals"] for side in TEAMS},
        "stats": {side: _team_stats(observed, side) for side in TEAMS},
        "recent_events": list(reversed(observed[-9:])),
        "goal_events": key_moments,
        "insights": _insights(observed, minute, mode, focus),
        "mode": mode,
        "focus": focus,
        "observed_event_count": len(observed),
        "recent_event_count": len(recent),
        "method": "Deterministic calculations over a simulated, fictional match. Possession is time on the ball.",
    }
