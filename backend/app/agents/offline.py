"""Rule-based agent behaviour, used when no model provider is configured.

The Tactics hypotheses here are deliberately eager: they are drafted without checking
whether they hold, exactly like a model's would be, and the Skeptic decides.
"""

import re

from ..synthetic import TEAMS
from .models import METRIC_LABELS, Claim, Job
from .tools import other, pick_evidence, window_stats

KEYWORDS = {
    "press": ["pressures", "turnovers"], "pressur": ["pressures", "turnovers"],
    "tackl": ["tackles_won"], "shot": ["shots", "xg"], "chance": ["xg", "shots"], "xg": ["xg", "shots"],
    "attack": ["shots", "xg"], "dangerous": ["xg", "shots"], "pass": ["pass_accuracy"],
    "control": ["pass_accuracy", "pressures"], "possession": ["pass_accuracy"], "rhythm": ["pass_accuracy"],
    "turnover": ["turnovers"], "lose the ball": ["turnovers"], "lost the ball": ["turnovers"],
    "giving the ball": ["turnovers"], "momentum": ["shots", "pressures"], "goal": ["xg", "shots"],
}
ALIASES = {"home": ("northbridge", "nbr"), "away": ("riverside", "rsu")}

# (whose: focus|opponent, metric, relation, compare, template)
HYPOTHESES = [
    ("focus", "pressures", "more", "opponent", "{F} is out-pressing {O}"),
    ("focus", "xg", "more", "opponent", "{F} is creating the better chances"),
    ("focus", "shots", "more", "previous", "{F} is shooting more than in the previous spell"),
    ("focus", "pass_accuracy", "less", "previous", "{F}'s passing has slipped compared with the previous spell"),
    ("opponent", "turnovers", "more", "previous", "{O} is giving the ball away more often than before"),
    ("focus", "tackles_won", "more", "opponent", "{F} is winning more tackles than {O}"),
]


def plan(job: Job) -> None:
    """Orchestrator: choose the team, minute window and metrics to investigate."""
    q = job.question.lower()
    for side, names in ALIASES.items():
        if any(n in q for n in names):
            job.focus = side

    start, end = max(1, job.minute - 9), job.minute
    if m := re.search(r"(?:between|from)\s*(\d{1,2})\D{1,8}?(\d{1,2})", q):
        start, end = int(m[1]), int(m[2])
    elif m := re.search(r"(?:after|since)\s*(?:the\s*)?(\d{1,2})", q):
        start, end = int(m[1]), job.minute
    elif m := re.search(r"before\s*(?:the\s*)?(\d{1,2})", q):
        start, end = 1, int(m[1])
    elif m := re.search(r"(?:last|past)\s*(\d{1,2})\s*min", q):
        start, end = job.minute - int(m[1]) + 1, job.minute
    elif "first half" in q:
        start, end = 1, 45
    elif "second half" in q:
        start, end = 46, 90
    start, end = max(1, min(start, end)), max(start, end)
    if end > job.minute:
        job.log("Orchestrator", "Clamped window",
                f"Question asks about minute {end}, but only {job.minute} minutes have been played.", "warn")
        end = job.minute
    job.window = (start, end)

    seen = []
    for key, metrics in KEYWORDS.items():
        if key in q:
            seen += [m for m in metrics if m not in seen]
    job.priorities = seen


def propose(job: Job) -> list[Claim]:
    focus, opp = job.focus, other(job.focus)
    names = {"F": TEAMS[focus]["name"], "O": TEAMS[opp]["name"]}
    start, end = job.window
    ranked = sorted(HYPOTHESES, key=lambda h: (h[1] not in job.priorities, HYPOTHESES.index(h)))
    claims = []
    for idx, (whose, metric, relation, compare, template) in enumerate(ranked[:4], start=1):
        team = focus if whose == "focus" else opp
        claims.append(Claim(
            id=f"C{idx}", team=team, metric=metric, start=start, end=end,
            value=window_stats(team, start, end)[metric], relation=relation, compare=compare,
            text=template.format(**names), evidence_ids=pick_evidence(team, metric, start, end),
        ))
    return claims


def revise(rejected: list[Claim]) -> list[Claim]:
    """Turn a rejected comparison around when the data shows the opposite (never when level)."""
    revised = []
    for c in rejected:
        if c.actual_value is None or c.compare_value is None or c.actual_value == c.compare_value:
            continue
        label = METRIC_LABELS[c.metric]
        if c.compare == "opponent":
            team = other(c.team)
            text = f"{TEAMS[team]['name']} has the edge in {label}, not {TEAMS[c.team]['name']}"
            relation = c.relation
        else:
            team = c.team
            relation = "less" if c.relation == "more" else "more"
            text = f"{TEAMS[team]['name']}'s {label} {'rose' if relation == 'more' else 'fell'} compared with the previous spell"
        revised.append(Claim(
            id=f"{c.id}R", team=team, metric=c.metric, start=c.start, end=c.end,
            value=window_stats(team, c.start, c.end)[c.metric], relation=relation, compare=c.compare,
            text=text, evidence_ids=pick_evidence(team, c.metric, c.start, c.end),
            proposed_by="Tactics (revision)", revision_of=c.id,
        ))
    return revised


def _number(claim: Claim) -> str:
    if claim.metric == "xg":
        return f"{claim.value:.2f} vs {claim.compare_value:.2f}"
    if claim.metric == "pass_accuracy":
        return f"{claim.value:.1f}% vs {claim.compare_value:.1f}%"
    return f"{claim.value:g} vs {claim.compare_value:g}"


def narrate(job: Job, accepted: list[Claim]) -> str:
    start, end = job.window
    if not accepted:
        return (f"None of the tactical claims for minutes {start}-{end} survived verification, "
                "so MatchMind won't read more into this spell than the events themselves.")
    if job.mode == "fan":
        lead = f"Minutes {start}-{end}: " if not job.question else ""
        return lead + " ".join(f"{c.text}." for c in accepted[:3])
    rejected = sum(c.verdict == "rejected" for c in job.claims)
    lines = [f"{c.text} ({METRIC_LABELS[c.metric]} {_number(c)}, {len(c.evidence_ids)} source events)."
             for c in accepted[:3]]
    tail = f" {rejected} other claim(s) were rejected by the Skeptic." if rejected else ""
    return f"Minutes {start}-{end}. " + " ".join(lines) + tail
