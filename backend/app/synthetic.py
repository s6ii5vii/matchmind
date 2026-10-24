"""Deterministic, completely fictional football match simulator.

No real teams, logos, footage or third-party sports data are used.
Each match is simulated from its own fixed seed, so it is identical on every run.

Matches are simulated possession by possession: a team wins the ball somewhere on the pitch,
passes and carries it forward (or doesn't), and the move ends in a shot, an interception, a
tackle, a clearance, a foul, offside or the ball going out. Restarts follow the laws: kick-offs,
goal kicks, throw-ins, free kicks and corners. Pressing makes errors more likely, so a pressing
spell shows up as more ball recoveries, not just more pressure events. Goalkeepers save, claim
crosses and distribute. Rates are calibrated against StatsBomb Open Data averages.

Coordinates are absolute, 0-100 on both axes: home attacks towards x=100, away towards x=0.

Several fictional matches are available (MATCHES). EVENTS, TEAMS, SQUADS and GOALS always refer
to the match the current request is about (see use_match), so the rest of the app is unchanged.
"""

import math
import random
import re
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class MatchSpec:
    id: str
    teams: dict
    squads: dict  # side -> [(shirt number, position, name)], the starting eleven
    bench: dict  # side -> substitutes
    # scripted shots that tell the match's story: (minute, second, team, player, xG, outcome "goal"|"saved"),
    # optionally followed by the opponent who is pressed off the ball to start the move
    script: list
    style: dict
    phases: list = field(default_factory=list)  # [(first minute, last minute, {home_ball, press, error})]
    seed: int = 2026
    story: str = ""
    questions: tuple = ()


NEUTRAL = {"home_ball": 0.54, "press": {"home": 1.0, "away": 1.0}, "error": {"home": 1.0, "away": 1.0}}

MATCHES: dict[str, MatchSpec] = {m.id: m for m in [
    MatchSpec(
        id="northbridge-riverside",
        teams={"home": {"name": "Northbridge City", "abbr": "NBR", "color": "#6bd8c2"},
               "away": {"name": "Riverside United", "abbr": "RSU", "color": "#f4ac73"}},
        squads={
            "home": [(1, "GK", "P. Lindqvist"), (2, "DF", "S. Walker"), (4, "DF", "J. Ortega"), (5, "DF", "T. Reed"),
                     (3, "DF", "E. Park"), (6, "MF", "M. Diallo"), (8, "MF", "L. Costa"), (10, "MF", "A. Okafor"),
                     (7, "FW", "D. Asante"), (9, "FW", "K. Mensah"), (11, "FW", "R. Novak")],
            "away": [(1, "GK", "G. Ferreira"), (2, "DF", "I. Brown"), (5, "DF", "F. Bauer"), (6, "DF", "O. Haddad"),
                     (3, "DF", "C. Murphy"), (4, "MF", "N. Patel"), (8, "MF", "Y. Chen"), (10, "MF", "D. Silva"),
                     (7, "FW", "P. Adams"), (9, "FW", "R. Kamara"), (11, "FW", "H. Moore")],
        },
        bench={"home": [(14, "DF", "O. Bergström"), (15, "MF", "F. Ibáñez"), (17, "MF", "N. Achebe"),
                        (18, "FW", "T. Holm"), (19, "FW", "J. Rahman")],
               "away": [(13, "DF", "L. Moreau"), (16, "MF", "B. Agyei"), (17, "MF", "S. Varga"),
                        (19, "FW", "E. Nilsen"), (20, "FW", "K. Obi")]},
        script=[(18, 20, "home", "K. Mensah", 0.27, "goal"), (42, 14, "away", "R. Kamara", 0.18, "goal"),
                (72, 36, "home", "A. Okafor", 0.33, "goal", "I. Brown")],
        style={"home": {"pass_acc": 0.85, "press": 0.34, "direct": 0.85, "shoot": 0.16},
               "away": {"pass_acc": 0.80, "press": 0.27, "direct": 1.15, "shoot": 0.18}},
        phases=[(30, 42, {"home_ball": 0.42, "press": {"home": 0.8, "away": 1.3}, "error": {"home": 1.15, "away": 1.0}}),
                (60, 80, {"home_ball": 0.75, "press": {"home": 3.0, "away": 0.5}, "error": {"home": 0.9, "away": 1.8}}),
                (86, 90, {"home_ball": 0.45, "press": {"home": 0.8, "away": 1.2}, "error": {"home": 1.1, "away": 1.0}})],
        seed=2026,
        story="Riverside have their spell before half-time; Northbridge press them into mistakes after the hour.",
        questions=("Who is controlling the game?", "Why did Riverside lose control after 60?",
                   "Is Northbridge's press working?"),
    ),
    MatchSpec(
        id="ashford-kingsport",
        teams={"home": {"name": "Ashford Rovers", "abbr": "ASH", "color": "#8fb3ff"},
               "away": {"name": "Kingsport Athletic", "abbr": "KGA", "color": "#ffb36b"}},
        squads={
            "home": [(1, "GK", "T. Oyelaran"), (2, "DF", "M. Castillo"), (4, "DF", "B. Whitfield"), (5, "DF", "K. Nakamura"),
                     (3, "DF", "L. Fontaine"), (6, "MF", "S. Adeyemi"), (8, "MF", "J. Kowalski"), (10, "MF", "E. Rossi"),
                     (7, "FW", "C. Mbeki"), (9, "FW", "D. Harlow"), (11, "FW", "V. Petrov")],
            "away": [(1, "GK", "A. Lindgren"), (2, "DF", "R. Okonkwo"), (5, "DF", "H. Duarte"), (6, "DF", "N. Brennan"),
                     (3, "DF", "F. Aziz"), (4, "MF", "O. Vasquez"), (8, "MF", "Y. Tanaka"), (10, "MF", "G. Mensah-Bonsu"),
                     (7, "FW", "I. Sorensen"), (9, "FW", "P. Kaur"), (11, "FW", "W. Dimitrov")],
        },
        bench={"home": [(13, "DF", "P. Okafor-Grant"), (14, "MF", "A. Laine"), (16, "MF", "R. Esposito"),
                        (18, "FW", "M. Quaye"), (20, "FW", "J. Brandt")],
               "away": [(12, "DF", "T. Ivanova-Marsh"), (14, "MF", "C. Ruiz"), (15, "MF", "D. Asamoah"),
                        (17, "FW", "L. Hartmann"), (21, "FW", "S. Bello")]},
        script=[(12, 40, "home", "D. Harlow", 0.31, "goal"), (34, 5, "home", "E. Rossi", 0.22, "goal"),
                (58, 30, "away", "P. Kaur", 0.29, "goal"), (74, 12, "away", "G. Mensah-Bonsu", 0.24, "goal", "B. Whitfield"),
                (81, 44, "home", "D. Harlow", 0.38, "saved"), (88, 47, "away", "P. Kaur", 0.41, "goal")],
        style={"home": {"pass_acc": 0.83, "press": 0.32, "direct": 1.05, "shoot": 0.18},
               "away": {"pass_acc": 0.82, "press": 0.30, "direct": 0.95, "shoot": 0.16}},
        phases=[(1, 40, {"home_ball": 0.60, "press": {"home": 1.6, "away": 0.8}, "error": {"home": 1.0, "away": 1.3}}),
                (46, 90, {"home_ball": 0.40, "press": {"home": 0.7, "away": 2.4}, "error": {"home": 1.45, "away": 0.95}})],
        seed=4471,
        story="Ashford race into a 2-0 lead; Kingsport take control after half-time and turn it round.",
        questions=("Who is controlling the game?", "Why did Ashford lose control after half-time?",
                   "Is Kingsport's press working?"),
    ),
    MatchSpec(
        id="hollowmere-stanton",
        teams={"home": {"name": "Hollowmere FC", "abbr": "HOL", "color": "#7fd6a0"},
               "away": {"name": "Stanton Vale", "abbr": "STV", "color": "#e59ad0"}},
        squads={
            "home": [(1, "GK", "M. Varga"), (2, "DF", "A. Quist"), (4, "DF", "T. Abara"), (5, "DF", "C. Doyle"),
                     (3, "DF", "R. Silva-Mendes"), (6, "MF", "K. Osei"), (8, "MF", "B. Lindholm"), (10, "MF", "F. Haddad"),
                     (7, "FW", "J. Marchetti"), (9, "FW", "S. Ndiaye"), (11, "FW", "L. Pereira")],
            "away": [(1, "GK", "E. Kowal"), (2, "DF", "D. Achterberg"), (5, "DF", "O. Mwangi"), (6, "DF", "P. Gallagher"),
                     (3, "DF", "Z. Hussain"), (4, "MF", "T. Ferreira-Lima"), (8, "MF", "H. Kim"), (10, "MF", "A. Novak"),
                     (7, "FW", "G. Tshabalala"), (9, "FW", "M. Ortiz"), (11, "FW", "C. Lund")],
        },
        bench={"home": [(12, "DF", "V. Laurent"), (14, "MF", "E. Saka-Mensah"), (16, "MF", "I. Rojas"),
                        (18, "FW", "B. Keane"), (19, "FW", "U. Demir")],
               "away": [(13, "DF", "F. Lindqvist"), (15, "MF", "R. Thapa"), (16, "MF", "Q. Adebayo"),
                        (18, "FW", "N. Petersen"), (22, "FW", "A. Kariuki")]},
        script=[(23, 10, "home", "S. Ndiaye", 0.44, "saved"), (51, 33, "home", "F. Haddad", 0.36, "saved"),
                (77, 2, "away", "M. Ortiz", 0.39, "saved"), (89, 18, "home", "S. Ndiaye", 0.47, "saved")],
        style={"home": {"pass_acc": 0.86, "press": 0.33, "direct": 0.8, "shoot": 0.15},
               "away": {"pass_acc": 0.79, "press": 0.22, "direct": 1.25, "shoot": 0.13}},
        phases=[(1, 69, {"home_ball": 0.63, "press": {"home": 1.1, "away": 0.7}, "error": {"home": 1.0, "away": 1.05}}),
                (70, 90, {"home_ball": 0.50, "press": {"home": 0.9, "away": 1.3}, "error": {"home": 1.15, "away": 0.95}})],
        seed=9013,
        story="Hollowmere dominate the ball against a deep Stanton Vale block; both keepers keep it goalless.",
        questions=("Who is controlling the game?", "Why can't Hollowmere break Stanton Vale down?",
                   "Are Stanton Vale defending well?"),
    ),
]}
DEFAULT_MATCH = "northbridge-riverside"

# who touches the ball in each third (attacking-direction), weighted by position
TOUCH = {
    "defensive": {"GK": 3.5, "DF": 6, "MF": 3, "FW": 0.5},
    "middle": {"GK": 0, "DF": 3, "MF": 6, "FW": 2},
    "attacking": {"GK": 0, "DF": 1, "MF": 4, "FW": 6},
}
SHOOTERS = {"GK": 0, "DF": 0.6, "MF": 2.5, "FW": 6}
# who presses, tackles, intercepts and clears in each third (from the defending side's point of view)
DEFEND = {
    "defensive": {"GK": 0.1, "DF": 6, "MF": 3, "FW": 0.5},
    "middle": {"GK": 0, "DF": 3, "MF": 6, "FW": 2},
    "attacking": {"GK": 0, "DF": 0.5, "MF": 4, "FW": 6},
}
TAKERS = {"GK": 0, "DF": 1, "MF": 5, "FW": 2}  # corners and wide free kicks
THROWERS = {"GK": 0, "DF": 6, "MF": 3, "FW": 1}
HALF_TIME = 45 * 60
FULL_TIME = 90 * 60
# from 2023/24 Bundesliga and Euro 2024 matches (StatsBomb Open Data): about 4.4 injury stoppages and 9 substitutions
# a match; after a stoppage the team on top loses about 11 points of its share of play for five minutes
INJURY_CHANCE = 0.02  # per possession
STOPPAGE_CALM = 300  # seconds the momentum stays dampened after a stoppage
FRESH_LEGS = 600  # seconds a substitution lifts a team's pressing


def other(team: str) -> str:
    return "away" if team == "home" else "home"


def third(depth: float) -> str:
    return "defensive" if depth < 33.3 else "middle" if depth < 66.7 else "attacking"


class MatchSim:
    def __init__(self, spec: MatchSpec):
        self.spec = spec
        self.rng = random.Random(spec.seed)
        self.events: list[dict] = []
        self.possession = 0
        self.team_in_possession = "home"
        self.booked: set[str] = set()
        self.period = 1
        self.on_pitch = {side: list(squad) for side, squad in spec.squads.items()}
        self.bench = {side: list(players) for side, players in spec.bench.items()}
        self.calm_until = -1.0
        self.fresh_until = {"home": -1.0, "away": -1.0}
        self.stopped = {1: 0.0, 2: 0.0}  # seconds of stoppages per half, which become added time
        self.added = {1: 0, 2: 0}
        self.script_left: list = []

    def phase(self, t: float) -> dict:
        """The match's momentum at this point, dampened just after a stoppage, lifted by fresh legs."""
        minute = int(t // 60) + 1
        p = next((p for start, end, p in self.spec.phases if start <= minute <= end), NEUTRAL)
        if t < self.calm_until:  # a stoppage breaks the rhythm: halfway back to an even game
            p = {"home_ball": (p["home_ball"] + NEUTRAL["home_ball"]) / 2,
                 "press": {s: (p["press"][s] + 1) / 2 for s in ("home", "away")},
                 "error": {s: (p["error"][s] + 1) / 2 for s in ("home", "away")}}
        lift = {s: 1.15 if t < self.fresh_until[s] else 1.0 for s in ("home", "away")}
        return {**p, "press": {s: p["press"][s] * lift[s] for s in ("home", "away")}}

    # depth is distance up the pitch in the attacking direction; convert to absolute x
    @staticmethod
    def to_x(team: str, depth: float) -> float:
        return round(depth if team == "home" else 100 - depth, 1)

    def pick(self, team: str, weights: dict, exclude: str | None = None) -> tuple[int, str, str]:
        squad = [p for p in self.on_pitch[team] if p[2] != exclude]
        return self.rng.choices(squad, weights=[weights[p[1]] + 0.01 for p in squad], k=1)[0]

    def keeper(self, team: str) -> tuple[int, str, str]:
        return next(p for p in self.on_pitch[team] if p[1] == "GK")

    def player(self, team: str, name: str) -> tuple[int, str, str]:
        return next((p for p in self.on_pitch[team] if p[2] == name),
                    None) or self.pick(team, SHOOTERS)  # scripted player already substituted: someone else

    def stoppage(self, t: float, reason: str, team: str, player: tuple, seconds: float, depth: float = 50.0,
                 y: float = 50.0, **extra) -> float:
        """Play stops (the clock doesn't): the time becomes added time, and the rhythm is broken."""
        self.add(t, team, player, "stoppage", depth, y, outcome=reason, duration_s=round(seconds), **extra)
        self.stopped[self.period] += seconds
        self.calm_until = t + seconds + STOPPAGE_CALM
        return t + seconds

    def substitutions(self, t: float, team: str, count: int) -> float:
        """Bring on fresh legs: forwards and midfielders first, never the keeper."""
        for _ in range(count):
            if not self.bench[team]:
                break
            on = self.bench[team].pop(0)
            # never take off someone the match's story still needs
            protected = {name for sc in self.script_left for name in sc[3:4] + sc[6:7]}
            pitch = [p for p in self.on_pitch[team] if p[2] not in protected]
            candidates = [p for p in pitch if p[1] == on[1]] or \
                [p for p in pitch if p[1] != "GK"]
            off = self.rng.choice(candidates)
            self.on_pitch[team][self.on_pitch[team].index(off)] = on
            self.add(t, team, off, "substitution", 50.0, 0.0, outcome="off", receiver=on[2])
            self.stopped[self.period] += 25
            t += 25
        self.fresh_until[team] = t + FRESH_LEGS
        return t

    def add(self, t: float, team: str, player: tuple, kind: str, depth: float, y: float, **extra) -> dict:
        t = int(t)  # the match clock within this half (45:00 onwards in the second half)
        event = {
            "period": self.period, "game_clock": t, "team": team,
            "player": player[2], "number": player[0], "position": player[1],
            "type": kind, "x": self.to_x(team, depth), "y": round(y, 1),
            "zone": third(depth), "outcome": None, "end_x": None, "end_y": None, "receiver": None,
            "pass_type": None, "under_pressure": False, "distance_m": None, "difficulty": None,
            "xg": None, "is_goal": False, "body_part": None,
            "possession": self.possession, "possession_team": self.team_in_possession,
            "possession_end": None,
        }
        event.update(extra)
        self.events.append(event)
        return event

    def xg(self, depth: float, y: float, header: bool) -> float:
        metres = math.hypot((100 - depth) * 1.05, (y - 50) * 0.68)
        value = 0.45 * math.exp(-metres / 7.5) * (0.55 if header else 1.0)
        return round(min(0.85, max(0.015, value)), 3)

    def finish(self, reason: str) -> None:
        self.events[-1]["possession_end"] = reason

    def foul(self, t: float, team: str, depth: float, y: float) -> None:
        """An opponent fouls `team`'s player; maybe a booking."""
        opp = other(team)
        fouler = self.pick(opp, DEFEND[third(100 - depth)])
        self.add(t, opp, fouler, "foul", 100 - depth, y, outcome="committed")
        self.finish("fouled")
        if self.rng.random() < 0.2 and fouler[2] not in self.booked:  # no second yellows: nobody is sent off
            self.booked.add(fouler[2])
            self.add(t + 20, opp, fouler, "card", 100 - depth, y, outcome="yellow")

    def shot_result(self, t: float, team: str, shooter: tuple, depth: float, y: float, value: float,
                    outcome: str, **extra) -> tuple:
        """Record a shot and what followed; return (end time, next team, depth, y, restart)."""
        rng, opp = self.rng, other(team)
        self.add(t, team, shooter, "shot", depth, y, outcome=outcome, xg=value, **extra)
        self.finish(f"shot {outcome.replace('_', ' ')}")
        if outcome == "saved":
            self.add(t + 0.5, opp, self.keeper(opp), "save", 100 - depth, y, outcome="saved", xg=value)
            if rng.random() < 0.35:  # tipped behind
                return t + rng.uniform(20, 35), team, 99.0, rng.choice([2.0, 98.0]), "corner"
            return t + rng.uniform(4, 10), opp, 5.0, 50.0, "keeper"
        if outcome == "blocked":
            blocker = self.pick(opp, DEFEND["defensive"])
            self.add(t + 0.5, opp, blocker, "block", 100 - depth, y, outcome="won", xg=value)
            roll = rng.random()
            if roll < 0.4:
                return t + rng.uniform(20, 35), team, 99.0, rng.choice([2.0, 98.0]), "corner"
            if roll < 0.75:
                return t + rng.uniform(2, 5), team, depth - 15, 50.0, None
            return t + rng.uniform(2, 5), opp, 100 - depth + 10, y, None
        return t + rng.uniform(15, 30), opp, 6.0, 50.0, "goal_kick"  # off target

    def run_possession(self, t: float, team: str, depth: float, y: float, minute_phase: dict,
                       scripted: tuple | None = None, restart: str | None = None) -> tuple:
        """Simulate one possession; return (end time, next team, next depth, next y, next restart)."""
        rng, style = self.rng, self.spec.style[team]
        opp = other(team)
        # a free kick or corner for the side already on the ball is the same possession (as StatsBomb counts it)
        if not (team == self.team_in_possession and restart in ("free_kick", "corner") and self.possession):
            self.possession += 1
        self.team_in_possession = team
        press_rate = self.spec.style[opp]["press"] * minute_phase["press"][opp]
        error_boost = minute_phase["error"][team]

        if restart in ("goal_kick", "keeper"):
            holder = self.keeper(team)
        elif restart == "corner":
            holder = self.pick(team, TAKERS)
        elif restart == "throw_in":
            holder = self.pick(team, THROWERS)
        else:
            holder = self.pick(team, TOUCH[third(depth)])

        steps = 4 if scripted else rng.randint(10, 32)
        for step in range(steps):
            t += 3.0 if scripted else rng.uniform(1.6, 4.2)
            first = step == 0 and restart is not None
            pressed = not first and rng.random() < press_rate * (1.15 if third(depth) == "defensive" else 1.0)
            if pressed:
                presser = self.pick(opp, DEFEND[third(100 - depth)])
                self.add(t, opp, presser, "pressure", 100 - depth, y, outcome="applied")
                # a press can win the ball outright
                if not scripted and rng.random() < 0.035 * error_boost:
                    self.add(t + 0.5, team, holder, "turnover", depth, y, outcome="lost", under_pressure=True)
                    self.finish("dispossessed")
                    self.add(t + 1, opp, presser, "tackle", 100 - depth, y, outcome="won")
                    return t + 1, opp, 100 - depth, y, None

            # shoot?
            if not scripted and not first and depth > 72 and rng.random() < 0.65 * style["shoot"] * (depth - 60) / 40:
                shooter = holder if SHOOTERS[holder[1]] else self.pick(team, SHOOTERS)
                header = rng.random() < 0.22
                outcome = rng.choices(["saved", "off_target", "blocked"], weights=[22, 50, 28], k=1)[0]
                return self.shot_result(t, team, shooter, depth, y, self.xg(depth, y, header), outcome,
                                        under_pressure=pressed, body_part="head" if header else "foot")

            # take on a defender?
            if not scripted and not first and depth > 45 and holder[1] != "GK" and rng.random() < 0.038:
                beaten = rng.random() < 0.54
                self.add(t, team, holder, "dribble", depth, y, outcome="complete" if beaten else "failed",
                         under_pressure=pressed)
                if not beaten:
                    self.finish("dispossessed")
                    self.add(t + 0.5, opp, self.pick(opp, DEFEND[third(100 - depth)]), "tackle", 100 - depth, y,
                             outcome="won")
                    return t + 0.5, opp, 100 - depth, y, None
                depth = min(95.0, depth + rng.uniform(4, 9))
                t += 1.5

            # pass (or cross, or the restart itself)
            wide = y < 22 or y > 78
            cross = restart == "corner" and first or (
                not scripted and depth > 70 and wide and rng.random() < 0.26) or (
                first and restart == "free_kick" and depth > 70)
            if cross:
                end_depth, end_y = rng.uniform(86, 96), rng.uniform(35, 65)
            else:
                forward = rng.uniform(-6, 16) * style["direct"] + (6 if third(depth) == "defensive" else 0)
                if restart == "goal_kick" and first:
                    forward = rng.uniform(15, 45)
                if scripted:
                    forward = (82 - depth) / 3 + rng.uniform(0, 4)
                end_depth = min(97.0, max(3.0, depth + forward))
                end_y = min(97.0, max(3.0, y + rng.uniform(-22, 22)))
            distance = math.hypot((end_depth - depth) * 1.05, (end_y - y) * 0.68)
            difficulty = min(0.95, 0.18 + distance / 95 + (0.12 if end_depth > 70 else 0) + (0.15 if pressed else 0))
            if cross:
                success = scripted is not None or rng.random() < 0.26
            elif first and restart in ("throw_in", "free_kick", "kick_off", "keeper"):
                success = rng.random() < 0.93
            else:
                success = scripted is not None or \
                    rng.random() < style["pass_acc"] + 0.21 - difficulty * 0.45 * error_boost
            offside = success and not scripted and not first and end_depth > 80 and rng.random() < 0.035
            receiver = self.pick(team, TOUCH[third(end_depth)], exclude=holder[2])
            if scripted and step == steps - 1:  # the final ball goes to the shooter
                receiver = self.player(team, scripted[3])
                if receiver[2] == holder[2]:  # nobody passes to themselves: someone else plays it
                    holder = self.pick(team, TOUCH[third(depth)], exclude=receiver[2])
            pass_type = restart if first else "cross" if cross else None
            self.add(t, team, holder, "pass", depth, y, outcome="complete" if success and not offside else "incomplete",
                     end_x=self.to_x(team, end_depth), end_y=round(end_y, 1),
                     receiver=receiver[2] if success and not offside else None, pass_type=pass_type,
                     under_pressure=pressed, distance_m=round(distance, 1), difficulty=round(difficulty, 2))
            if offside:
                self.add(t + 1, team, receiver, "offside", end_depth, end_y, outcome="flagged")
                self.finish("offside")
                return t + rng.uniform(15, 25), opp, 100 - end_depth, end_y, "free_kick"
            if not success:
                if cross and end_depth > 83:  # a ball into the box: keeper claims or a defender clears
                    if rng.random() < 0.25:
                        self.finish("claimed by the keeper")
                        self.add(t + 1, opp, self.keeper(opp), "claim", 100 - end_depth, end_y, outcome="won")
                        return t + rng.uniform(4, 8), opp, 8.0, 50.0, "keeper"
                    self.finish("cleared")
                    clearer = self.pick(opp, DEFEND["defensive"])
                    self.add(t + 1, opp, clearer, "clearance", 100 - end_depth, end_y, outcome="won")
                    if rng.random() < 0.25:
                        return t + rng.uniform(20, 35), team, 99.0, rng.choice([2.0, 98.0]), "corner"
                    return t + rng.uniform(3, 8), opp, 100 - end_depth + 25, end_y, None
                fate = rng.random()
                if fate < 0.5:  # loose ball, but the passing side gets there first
                    t += 2
                    holder = self.pick(team, TOUCH[third(end_depth)])
                    self.add(t, team, holder, "recovery", end_depth, end_y, outcome="won")
                    depth, y = end_depth, end_y
                    continue
                if fate < 0.66:
                    self.finish("intercepted")
                    interceptor = self.pick(opp, DEFEND[third(100 - end_depth)])
                    self.add(t + 1, opp, interceptor, "interception", 100 - end_depth, end_y, outcome="won")
                    return t + 1, opp, 100 - end_depth, end_y, None
                if fate < 0.82 and end_depth > 66:
                    self.finish("cleared")
                    clearer = self.pick(opp, DEFEND["defensive"])
                    self.add(t + 1, opp, clearer, "clearance", 100 - end_depth, end_y, outcome="won")
                    return t + rng.uniform(3, 8), opp, 100 - end_depth + 25, end_y, None
                if fate < 0.90:
                    self.finish("pass misplaced")
                    collector = self.pick(opp, TOUCH[third(100 - end_depth)])
                    self.add(t + 2, opp, collector, "recovery", 100 - end_depth, end_y, outcome="won")
                    return t + 2, opp, 100 - end_depth, end_y, None
                self.finish("pass out of play")
                if end_depth > 92:
                    return t + rng.uniform(15, 25), opp, 6.0, 50.0, "goal_kick"
                return t + rng.uniform(8, 18), opp, 100 - end_depth, rng.choice([1.0, 99.0]), "throw_in"
            holder, depth, y = receiver, end_depth, end_y

            # carry it forward
            if not scripted and holder[1] != "GK" and rng.random() < 0.45:
                carry_to = min(97.0, depth + rng.uniform(1, 10))
                carry_y = min(97.0, max(3.0, y + rng.uniform(-6, 6)))
                t += rng.uniform(0.5, 1.5)
                self.add(t, team, holder, "carry", depth, y, outcome="complete",
                         end_x=self.to_x(team, carry_to), end_y=round(carry_y, 1))
                depth, y = carry_to, carry_y

            # duels and fouls on the ball carrier
            roll = rng.random()
            if scripted:
                continue
            if roll < 0.008 * error_boost:
                tackler = self.pick(opp, DEFEND[third(100 - depth)])
                self.add(t + 1.5, opp, tackler, "tackle", 100 - depth, y, outcome="won")
                self.finish("tackled")
                return t + 1.5, opp, 100 - depth, y, None
            if roll < 0.017:
                tackler = self.pick(opp, DEFEND[third(100 - depth)])
                self.add(t + 1.5, opp, tackler, "tackle", 100 - depth, y, outcome="lost")
            elif roll < 0.050:
                self.foul(t + 1.5, team, depth, y)
                return t + rng.uniform(15, 30), team, depth, y, "free_kick"
            elif roll < 0.050 + 0.010 * error_boost:
                self.add(t + 1.5, team, holder, "turnover", depth, y, outcome="lost")
                self.finish("miscontrol")
                collector = self.pick(opp, TOUCH[third(100 - depth)])
                self.add(t + 2.5, opp, collector, "recovery", 100 - depth, y, outcome="won")
                return t + 2.5, opp, 100 - depth, y, None

        if scripted:
            minute, second, _, name, value, outcome = scripted[:6]
            at = minute * 60 - 60 + second
            shooter = self.player(team, name)
            if outcome == "goal":
                self.add(at, team, shooter, "shot", 89.4, 48.1, outcome="goal", xg=value, is_goal=True,
                         body_part="foot")
                self.finish("goal")
                self.stopped[self.period] += 45  # the celebration
                restart_at = at + 60
                if self.rng.random() < 0.35:  # a VAR check before the goal stands
                    restart_at = self.stoppage(at + 30, "var_check", team, shooter, self.rng.uniform(60, 150),
                                               89.4, 48.1, decision="goal stands")
                return restart_at, opp, 50.0, 50.0, "kick_off"
            return self.shot_result(at, team, shooter, 90.5, 46.0, value, "saved", body_part="foot")

        # move fizzled out: the ball runs out of play
        self.finish("ball out of play")
        return t + rng.uniform(10, 25), opp, 100 - depth, rng.choice([1.0, 99.0]), "throw_in"

    def pressed_off(self, t: float, team: str, name: str, depth: float, y: float) -> None:
        """A scripted mistake: `name` (the other side) is pressed off the ball, and `team` attack from there."""
        opp = other(team)
        loser = next((p for p in self.on_pitch[opp] if p[2] == name), None) or self.pick(opp, DEFEND["middle"])
        presser = self.pick(team, DEFEND["middle"])
        self.possession += 1
        self.team_in_possession = opp
        self.add(t - 1, team, presser, "pressure", depth, y, outcome="applied")
        self.add(t - 0.5, opp, loser, "turnover", 100 - depth, y, outcome="lost", under_pressure=True)
        self.finish("dispossessed")
        self.add(t, team, presser, "tackle", depth, y, outcome="won")

    def sub_plan(self) -> list[tuple[float, str, int]]:
        """When each side makes its changes: maybe one at half-time, the rest after the hour."""
        rng, plan = self.rng, []
        for team in ("home", "away"):
            left = rng.choice([4, 5, 5, 5])
            if rng.random() < 0.3:
                plan.append((HALF_TIME, team, 1))
                left -= 1
            for window in ((55, 64), (65, 75), (76, 86)):
                n = min(left, rng.choice([1, 2]))
                if n:
                    plan.append((rng.uniform(*window) * 60, team, n))
                    left -= n
        return sorted(plan)

    def added_time(self, period: int) -> int:
        """Announced added time, built from the stoppages in this half (2023/24 averages: +2.3 and +4.9)."""
        minutes = 0.6 + 0.4 * self.stopped[period] / 60 + (1.2 if period == 2 else 0)  # plus time-wasting late on
        return int(min(max(round(minutes), 1 if period == 1 else 2), 7 if period == 1 else 10))

    def play(self) -> list[dict]:
        rng = self.rng
        script = self.script_left = sorted(self.spec.script)
        subs = self.sub_plan()
        for period, kick_off, start in ((1, "home", 0.0), (2, "away", float(HALF_TIME))):
            self.period = period
            t, team, depth, y, restart = start, kick_off, 50.0, 50.0, "kick_off"
            regulation, end = start + HALF_TIME, None
            while True:
                if end is None and t >= regulation:
                    self.added[period] = self.added_time(period)
                    end = regulation + self.added[period] * 60
                if end is not None and t >= end:
                    break
                while subs and subs[0][0] <= t and (period == 2 or subs[0][0] < HALF_TIME):
                    _, side, n = subs.pop(0)
                    t = self.substitutions(t, side, n)
                if restart != "kick_off" and rng.random() < INJURY_CHANCE:
                    side = rng.choice(["home", "away"])
                    hurt = self.pick(side, {"GK": 0.3, "DF": 1, "MF": 1, "FW": 1})
                    t = self.stoppage(t, "injury", side, hurt, rng.uniform(40, 110), depth, y)
                minute = int(t // 60) + 1
                in_half = [sc for sc in script if (sc[0] <= 45) == (period == 1)]
                nxt = in_half[0] if in_half and t >= (in_half[0][0] - 1) * 60 + in_half[0][1] - 18 else None
                if nxt:
                    script.remove(nxt)
                    team, t = nxt[2], (nxt[0] - 1) * 60 + nxt[1] - 16
                    depth, y, restart = 45.0, rng.uniform(30, 70), None
                    if len(nxt) > 6:
                        self.pressed_off(t - 3, team, nxt[6], depth, y)
                elif restart is None and rng.random() > 0.35:  # contested second balls follow the momentum
                    team = "home" if rng.random() < self.phase(t)["home_ball"] else "away"
                t, team, depth, y, restart = self.run_possession(t, team, depth, y, self.phase(t), nxt, restart)
            # the referee blows at the end of added time, even mid-move
            self.events = [e for e in self.events if e["period"] != period or e["game_clock"] < end]
            last = self.events[-1]
            last["possession_end"] = last["possession_end"] or ("half time" if period == 1 else "full time")
        return self.events


def tidy(text: str) -> str:
    """English possessives for names ending in s: "Ashford Rovers's" -> "Ashford Rovers'"."""
    return re.sub(r"\b(\w+s)'s\b", r"\1'", text)


def label_for(period: int, game_clock: int) -> str:
    """The minute as football writes it: 45+2' in first-half added time, 90+4' in the second."""
    m = game_clock // 60 + 1
    cap = 45 if period == 1 else 90
    return f"{m}'" if m <= cap else f"{cap}+{m - cap}'"


@lru_cache(maxsize=None)
def _simulate(match_id: str) -> tuple:
    sim = MatchSim(MATCHES[match_id])
    events = sim.play()
    first_half = (45 + sim.added[1]) * 60  # seconds actually played before half-time
    for e in events:
        # one continuous timeline across both halves; "minute" counts minutes of play from kick-off
        e["t"] = e["game_clock"] if e["period"] == 1 else first_half + e["game_clock"] - HALF_TIME
        e["minute"] = e["t"] // 60 + 1
        e["second"] = e["t"] % 60
        e["clock"] = f"{e['game_clock'] // 60:02d}:{e['game_clock'] % 60:02d}"  # the TV clock, 47:13 or 92:05
        e["label"] = label_for(e["period"], e["game_clock"])
    events.sort(key=lambda e: (e["t"], e["possession"]))
    for idx, event in enumerate(events, start=1):
        event["id"] = f"SIM-{idx:04d}"
    length = (45 + sim.added[1] + 45 + sim.added[2])
    labels = ["0'"] + [label_for(1, (i - 1) * 60) if i <= 45 + sim.added[1]
                       else label_for(2, HALF_TIME + (i - 46 - sim.added[1]) * 60) for i in range(1, length + 1)]
    meta = {"added": dict(sim.added), "first_half": 45 + sim.added[1], "length": length, "labels": labels}
    return tuple(events), meta


def _generate(match_id: str) -> tuple:
    return _simulate(match_id)[0]


def generate_events(match_id: str = DEFAULT_MATCH) -> list[dict]:
    """Simulate a full fictional match; never expose future data as current."""
    return list(_generate(match_id))


# --- which match the current request is about -------------------------------------------------

_CURRENT: ContextVar[str] = ContextVar("matchmind_match", default=DEFAULT_MATCH)


def current_match() -> MatchSpec:
    return MATCHES[_CURRENT.get()]


@contextmanager
def use_match(match_id: str):
    """Everything inside (agents, stats, ratings, moments) works on this match."""
    if match_id not in MATCHES:
        raise KeyError(match_id)
    token = _CURRENT.set(match_id)
    try:
        yield MATCHES[match_id]
    finally:
        _CURRENT.reset(token)


def match_meta() -> dict:
    """The current match's length in minutes of play, added time and minute labels."""
    return _simulate(_CURRENT.get())[1]


def label(minute: int) -> str:
    """Minute of play (1, 2 ... 98) as football writes it ("72'", "45+2'", "90+4'")."""
    labels = match_meta()["labels"]
    return labels[max(0, min(minute, len(labels) - 1))]


def span(start: int, end: int) -> str:
    return label(start) if start == end else f"{label(start)}–{label(end)}"


def minute_of(football_minute: int, extra: int = 0) -> int:
    """Turn a football minute ("60", "90+3") into a minute of play on the timeline."""
    meta = match_meta()
    if football_minute <= 45:
        return football_minute + (extra if football_minute == 45 else 0)
    return football_minute + meta["added"][1] + extra


class _CurrentEvents(Sequence):
    def __getitem__(self, i):
        return _generate(_CURRENT.get())[i]

    def __len__(self) -> int:
        return len(_generate(_CURRENT.get()))

    def __eq__(self, other) -> bool:
        return list(self) == list(other)

    def __repr__(self) -> str:
        return f"<events of {_CURRENT.get()}: {len(self)}>"


class _CurrentMapping(Mapping):
    def __init__(self, attr: str):
        self.attr = attr

    def _data(self) -> dict:
        return getattr(current_match(), self.attr)

    def __getitem__(self, key):
        return self._data()[key]

    def __iter__(self):
        return iter(self._data())

    def __len__(self) -> int:
        return len(self._data())


class _CurrentScript(Sequence):
    """The current match's goals as (minute, second, team, scorer, xG)."""
    def _goals(self) -> list:
        return [s[:5] for s in current_match().script if s[5] == "goal"]

    def __getitem__(self, i):
        return self._goals()[i]

    def __len__(self) -> int:
        return len(self._goals())


@lru_cache(maxsize=None)
def _by_id(match_id: str) -> dict:
    return {e["id"]: e for e in _generate(match_id)}


class _CurrentById(Mapping):
    def __getitem__(self, key):
        return _by_id(_CURRENT.get())[key]

    def __iter__(self):
        return iter(_by_id(_CURRENT.get()))

    def __len__(self) -> int:
        return len(_by_id(_CURRENT.get()))


EVENTS = _CurrentEvents()
EVENTS_BY_ID = _CurrentById()
TEAMS = _CurrentMapping("teams")
SQUADS = _CurrentMapping("squads")
GOALS = _CurrentScript()
