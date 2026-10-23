"""Deterministic, completely fictional football match simulator.

No real teams, logos, footage or third-party sports data are used.
Each run with the same seed produces an identical event stream.

The match is simulated possession by possession: a team wins the ball somewhere on the pitch,
passes it forward (or doesn't), and the move ends in a shot, an interception, a tackle, a
miscontrol, a foul or the ball going out. Pressing makes errors more likely, so a pressing
spell shows up as more ball recoveries, not just more pressure events.

Coordinates are absolute, 0-100 on both axes: home attacks towards x=100, away towards x=0.
"""

import math
import random

TEAMS = {
    "home": {"name": "Northbridge City", "abbr": "NBR", "color": "#6bd8c2"},
    "away": {"name": "Riverside United", "abbr": "RSU", "color": "#f4ac73"},
}

# (shirt number, position, name)
SQUADS = {
    "home": [(1, "GK", "P. Lindqvist"), (2, "DF", "S. Walker"), (4, "DF", "J. Ortega"), (5, "DF", "T. Reed"),
             (3, "DF", "E. Park"), (6, "MF", "M. Diallo"), (8, "MF", "L. Costa"), (10, "MF", "A. Okafor"),
             (7, "FW", "D. Asante"), (9, "FW", "K. Mensah"), (11, "FW", "R. Novak")],
    "away": [(1, "GK", "G. Ferreira"), (2, "DF", "I. Brown"), (5, "DF", "F. Bauer"), (6, "DF", "O. Haddad"),
             (3, "DF", "C. Murphy"), (4, "MF", "N. Patel"), (8, "MF", "Y. Chen"), (10, "MF", "D. Silva"),
             (7, "FW", "P. Adams"), (9, "FW", "R. Kamara"), (11, "FW", "H. Moore")],
}
PLAYERS = {side: [name for _, _, name in squad] for side, squad in SQUADS.items()}

# (minute, second, team, scorer, xG): the match story the demo is built around
GOALS = [
    (18, 20, "home", "K. Mensah", 0.27),
    (42, 14, "away", "R. Kamara", 0.18),
    (72, 36, "home", "A. Okafor", 0.33),
]

# how each side plays: home keep the ball, away go direct
STYLE = {
    "home": {"pass_acc": 0.86, "press": 0.30, "direct": 0.9, "shoot": 0.30},
    "away": {"pass_acc": 0.81, "press": 0.22, "direct": 1.25, "shoot": 0.34},
}

# who touches the ball in each third (attacking-direction), weighted by position
TOUCH = {
    "defensive": {"GK": 2, "DF": 6, "MF": 3, "FW": 0.5},
    "middle": {"GK": 0, "DF": 3, "MF": 6, "FW": 2},
    "attacking": {"GK": 0, "DF": 1, "MF": 4, "FW": 6},
}
SHOOTERS = {"GK": 0, "DF": 0.6, "MF": 2.5, "FW": 6}


def phase(minute: int) -> dict:
    """Momentum of the fictional match: away's spell before half-time, home's pressing spell after the hour."""
    if 30 <= minute <= 42:
        return {"home_ball": 0.42, "press": {"home": 0.8, "away": 1.3}, "error": {"home": 1.15, "away": 1.0}}
    if 60 <= minute <= 80:
        return {"home_ball": 0.62, "press": {"home": 3.0, "away": 0.6}, "error": {"home": 1.0, "away": 1.45}}
    if minute > 85:
        return {"home_ball": 0.45, "press": {"home": 0.8, "away": 1.2}, "error": {"home": 1.1, "away": 1.0}}
    return {"home_ball": 0.54, "press": {"home": 1.0, "away": 1.0}, "error": {"home": 1.0, "away": 1.0}}


def other(team: str) -> str:
    return "away" if team == "home" else "home"


def third(depth: float) -> str:
    return "defensive" if depth < 33.3 else "middle" if depth < 66.7 else "attacking"


class MatchSim:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.events: list[dict] = []
        self.possession = 0

    # depth is distance up the pitch in the attacking direction; convert to absolute x
    @staticmethod
    def to_x(team: str, depth: float) -> float:
        return round(depth if team == "home" else 100 - depth, 1)

    def pick(self, team: str, weights: dict, exclude: str | None = None) -> tuple[int, str, str]:
        squad = [p for p in SQUADS[team] if p[2] != exclude]
        return self.rng.choices(squad, weights=[weights[p[1]] + 0.01 for p in squad], k=1)[0]

    def add(self, t: float, team: str, player: tuple, kind: str, depth: float, y: float, **extra) -> dict:
        t = min(int(t), 90 * 60 - 1)
        event = {
            "minute": t // 60 + 1, "second": t % 60, "t": t, "team": team,
            "player": player[2], "number": player[0], "position": player[1],
            "type": kind, "x": self.to_x(team, depth), "y": round(y, 1),
            "zone": third(depth), "outcome": None, "end_x": None, "end_y": None, "receiver": None,
            "under_pressure": False, "distance_m": None, "difficulty": None, "xg": None, "is_goal": False,
            "possession": self.possession, "possession_team": self.team_in_possession,
            "possession_end": None,
        }
        event.update(extra)
        self.events.append(event)
        return event

    def xg(self, depth: float, y: float, header: bool) -> float:
        metres = math.hypot((100 - depth) * 1.05, (y - 50) * 0.68)
        value = 0.75 * math.exp(-metres / 7.5) * (0.55 if header else 1.0)
        return round(min(0.85, max(0.015, value)), 3)

    def run_possession(self, t: float, team: str, depth: float, y: float, minute_phase: dict,
                       goal: tuple | None = None) -> tuple[float, str, float, float]:
        """Simulate one possession; return (end time, next team, next depth, next y)."""
        rng, style = self.rng, STYLE[team]
        opp = other(team)
        self.possession += 1
        self.team_in_possession = team
        start = len(self.events)
        holder = self.pick(team, TOUCH[third(depth)])
        press_rate = STYLE[opp]["press"] * minute_phase["press"][opp]
        error_boost = minute_phase["error"][team]

        def finish(reason: str) -> None:
            self.events[-1]["possession_end"] = reason

        for _ in range(rng.randint(6, 18) if goal is None else 4):
            t += rng.uniform(2.0, 5.5) if goal is None else 3.0
            pressed = rng.random() < press_rate * (1.15 if third(depth) == "defensive" else 1.0)
            if pressed:
                presser = self.pick(opp, TOUCH[third(100 - depth)])
                self.add(t, opp, presser, "pressure", 100 - depth, y, outcome="applied")
                # a press can win the ball outright
                if goal is None and rng.random() < 0.13 * error_boost:
                    self.add(t + 0.5, team, holder, "turnover", depth, y, outcome="lost", under_pressure=True)
                    finish("dispossessed")
                    self.add(t + 1, opp, presser, "tackle", 100 - depth, y, outcome="won")
                    return t + 1, opp, 100 - depth, y

            # shoot?
            if goal is None and depth > 72 and rng.random() < style["shoot"] * (depth - 60) / 40:
                shooter = holder if SHOOTERS[holder[1]] else self.pick(team, SHOOTERS)
                header = rng.random() < 0.22
                value = self.xg(depth, y, header)
                outcome = rng.choices(["saved", "off_target", "blocked"], weights=[40, 38, 22], k=1)[0]
                self.add(t, team, shooter, "shot", depth, y, outcome=outcome, xg=value, under_pressure=pressed,
                         body_part="head" if header else "foot")
                finish(f"shot {outcome.replace('_', ' ')}")
                if outcome == "saved":
                    return t + rng.uniform(4, 10), opp, 5.0, 50.0
                return t + rng.uniform(15, 35), opp if outcome == "off_target" else team, \
                    6.0 if outcome == "off_target" else depth - 15, 50.0

            # pass
            forward = rng.uniform(-6, 16) * style["direct"] + (6 if third(depth) == "defensive" else 0)
            if goal is not None:
                forward = (82 - depth) / 3 + rng.uniform(0, 4)
            end_depth = min(97.0, max(3.0, depth + forward))
            end_y = min(97.0, max(3.0, y + rng.uniform(-22, 22)))
            distance = math.hypot((end_depth - depth) * 1.05, (end_y - y) * 0.68)
            difficulty = min(0.95, 0.18 + distance / 95 + (0.12 if end_depth > 70 else 0) + (0.15 if pressed else 0))
            success = goal is not None or rng.random() < style["pass_acc"] + 0.12 - difficulty * 0.45 * error_boost
            receiver = self.pick(team, TOUCH[third(end_depth)], exclude=holder[2])
            self.add(t, team, holder, "pass", depth, y, outcome="complete" if success else "incomplete",
                     end_x=self.to_x(team, end_depth), end_y=round(end_y, 1), receiver=receiver[2] if success else None,
                     under_pressure=pressed, distance_m=round(distance, 1), difficulty=round(difficulty, 2))
            if not success:
                finish("intercepted" if rng.random() < 0.55 else "pass out of play")
                if self.events[-1]["possession_end"] == "intercepted":
                    interceptor = self.pick(opp, TOUCH[third(100 - end_depth)])
                    self.add(t + 1, opp, interceptor, "interception", 100 - end_depth, end_y, outcome="won")
                    return t + 1, opp, 100 - end_depth, end_y
                return t + rng.uniform(8, 18), opp, 100 - end_depth, end_y
            holder, depth, y = receiver, end_depth, end_y

            # duels and fouls on the receiver
            roll = rng.random()
            if goal is None and roll < 0.05 * error_boost:
                tackler = self.pick(opp, TOUCH[third(100 - depth)])
                self.add(t + 1.5, opp, tackler, "tackle", 100 - depth, y, outcome="won")
                finish("tackled")
                return t + 1.5, opp, 100 - depth, y
            if goal is None and roll < 0.07:
                tackler = self.pick(opp, TOUCH[third(100 - depth)])
                self.add(t + 1.5, opp, tackler, "tackle", 100 - depth, y, outcome="lost")
            elif goal is None and roll < 0.085:
                fouler = self.pick(opp, TOUCH[third(100 - depth)])
                self.add(t + 1.5, opp, fouler, "foul", 100 - depth, y, outcome="committed")
                finish("fouled")
                return t + rng.uniform(15, 30), team, depth, y
            elif goal is None and roll < 0.10 * error_boost:
                self.add(t + 1.5, team, holder, "turnover", depth, y, outcome="lost")
                finish("miscontrol")
                return t + 2, opp, 100 - depth, y

        if goal is not None:
            minute, second, _, scorer_name, value = goal
            scorer = next(p for p in SQUADS[team] if p[2] == scorer_name)
            self.add(minute * 60 - 60 + second, team, scorer, "shot", 89.4, 48.1, outcome="goal", xg=value,
                     is_goal=True, body_part="foot")
            finish("goal")
            return minute * 60 - 60 + second + 60, opp, 50.0, 50.0

        # move fizzled out: recycled back and lost, or simply ran out of options
        finish("ball out of play")
        return t + rng.uniform(10, 25), opp, 100 - depth, y

    def play(self) -> list[dict]:
        rng = self.rng
        self.team_in_possession = "home"
        t, team, depth, y = 0.0, "home", 50.0, 50.0
        goals = list(GOALS)
        while t < 90 * 60 - 5:
            minute = int(t // 60) + 1
            goal = goals[0] if goals and t >= (goals[0][0] - 1) * 60 + goals[0][1] - 18 else None
            if goal:
                goals.pop(0)
                team, t = goal[2], (goal[0] - 1) * 60 + goal[1] - 16
                depth, y = 45.0, rng.uniform(30, 70)
            elif rng.random() > 0.35:  # contested restarts and second balls follow the match's momentum
                team = "home" if rng.random() < phase(minute)["home_ball"] else "away"
            t, team, depth, y = self.run_possession(t, team, depth, y, phase(minute), goal)
        return self.events


def generate_events(seed: int = 2026) -> list[dict]:
    """Simulate a full fictional match; never expose future data as current."""
    events = MatchSim(seed).play()
    events.sort(key=lambda e: (e["t"], e["possession"]))
    for idx, event in enumerate(events, start=1):
        event["id"] = f"SIM-{idx:04d}"
        event["clock"] = f"{event['minute']:02d}:{event['second']:02d}"
    return events


EVENTS = generate_events()
