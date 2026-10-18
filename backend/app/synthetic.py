"""Deterministic, completely fictional football event generator.

No real teams, logos, footage or third-party sports data are used.
Each rerun with the same seed produces an identical event stream.
"""

import math
import random

TEAMS = {
    "home": {"name": "Northbridge City", "abbr": "NBR", "color": "#6bd8c2"},
    "away": {"name": "Riverside United", "abbr": "RSU", "color": "#f4ac73"},
}

PLAYERS = {
    "home": ["K. Mensah", "J. Ortega", "M. Diallo", "S. Walker", "E. Park", "A. Okafor", "L. Costa", "T. Reed"],
    "away": ["R. Kamara", "D. Silva", "N. Patel", "I. Brown", "F. Bauer", "Y. Chen", "P. Adams", "H. Moore"],
}

GOALS = [
    (18, 20, "home", "K. Mensah", 0.27),
    (42, 14, "away", "R. Kamara", 0.18),
    (72, 36, "home", "A. Okafor", 0.33),
]


def generate_events(seed: int = 2026) -> list[dict]:
    """Generate football-realistic *synthetic* actions; never expose future data as current."""
    rng = random.Random(seed)
    events = []
    for minute in range(1, 91):
        n = rng.randint(2, 5)
        for _ in range(n):
            second = rng.randrange(60)
            home_probability = 0.64 if 60 <= minute <= 80 else 0.52
            team = "home" if rng.random() < home_probability else "away"
            player = rng.choice(PLAYERS[team])
            pressure_phase = 60 <= minute <= 80 and team == "home"
            kind = rng.choices(
                ["pass", "pressure", "tackle", "shot", "turnover"],
                weights=[52, 22 if pressure_phase else 13, 11, 9, 6 if pressure_phase else 15],
                k=1,
            )[0]
            x = round(rng.uniform(9, 92), 1)
            y = round(rng.uniform(5, 95), 1)
            event = {
                "minute": minute,
                "second": second,
                "team": team,
                "player": player,
                "type": kind,
                "x": x,
                "y": y,
                "outcome": None,
                "distance_m": None,
                "difficulty": None,
                "xg": None,
                "is_goal": False,
            }
            if kind == "pass":
                distance = round(rng.uniform(3, 51), 1)
                difficulty = round(min(0.98, 0.22 + distance / 110 + (0.12 if x > 70 else 0)), 2)
                accurate = rng.random() < (0.93 - difficulty * 0.4 - (0.13 if team == "away" and pressure_phase else 0))
                event.update(distance_m=distance, difficulty=difficulty, outcome="complete" if accurate else "incomplete")
            elif kind == "shot":
                xg = round(rng.uniform(0.025, 0.22), 3)
                event.update(xg=xg, outcome="saved" if rng.random() < 0.55 else "off_target")
            elif kind in ("pressure", "tackle"):
                event["outcome"] = "applied" if kind == "pressure" else ("won" if rng.random() < 0.55 else "lost")
            else:
                event["outcome"] = "lost"
            events.append(event)

    for minute, second, team, player, xg in GOALS:
        events.append({
            "minute": minute, "second": second, "team": team, "player": player,
            "type": "shot", "x": 89.4, "y": 48.1,
            "outcome": "goal", "distance_m": None, "difficulty": None,
            "xg": xg, "is_goal": True,
        })

    events.sort(key=lambda e: (e["minute"], e["second"], e["team"]))
    for idx, event in enumerate(events, start=1):
        event["id"] = f"SIM-{idx:04d}"
        event["clock"] = f"{event['minute']:02d}:{event['second']:02d}"
    return events


EVENTS = generate_events()
