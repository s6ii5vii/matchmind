"""Rule-based agent behaviour, used when no model provider is configured.

The rule-based Pundit reads the game like a viewer: it forms each take from the last five minutes
(what you just watched) and states it about the whole spell. That's usually right, but recency bias
sometimes catches it out, and the Skeptic, which checks the whole spell, decides.
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

# what a pundit talks about: (metric, compare, whose: focus|opponent|either)
TOPICS = [
    ("pressures", "opponent", "either"),
    ("xg", "opponent", "either"),
    ("shots", "previous", "focus"),
    ("pass_accuracy", "previous", "focus"),
    ("turnovers", "previous", "opponent"),
    ("tackles_won", "opponent", "either"),
]
EYE_TEST_MINUTES = 5

# assumptions a question can carry: (trigger phrases, metric, relation, compare, take)
PREMISES = [
    (("lose control", "lost control", "losing control"), "passes", "less", "opponent",
     "{T} lost control of the ball"),
    (("press",), "pressures", "more", "opponent", "{T} are pressing harder than {O}"),
    (("struggl", "no chances", "can't create"), "shots", "less", "previous", "{T} are struggling to create"),
    (("dangerous", "better chances", "creating chances"), "xg", "more", "opponent",
     "{T} are creating the better chances"),
    (("sloppy", "careless", "giving the ball away", "giving it away"), "turnovers", "more", "previous",
     "{T} are giving the ball away more"),
    (("fading", "tired", "dropped off", "running out"), "pressures", "less", "previous", "{T} are fading"),
    (("dominat", "on top", "in control", "ran the show", "running the show"), "passes", "more", "opponent",
     "{T} are on top"),
]


# how a pundit would say "<team> has more/less <metric>"
PHRASES = {
    ("pressures", "more"): "{T} are the ones doing the pressing", ("pressures", "less"): "{T} have eased off the press",
    ("xg", "more"): "{T} are creating the better chances", ("xg", "less"): "{T} are creating less",
    ("shots", "more"): "{T} are getting more shots away", ("shots", "less"): "{T}'s shots have dried up",
    ("pass_accuracy", "more"): "{T} are passing it better", ("pass_accuracy", "less"): "{T} are getting sloppy on the ball",
    ("turnovers", "more"): "{T} keep giving the ball away", ("turnovers", "less"): "{T} are looking after the ball",
    ("tackles_won", "more"): "{T} are winning the battles", ("tackles_won", "less"): "{T} are losing the battles",
    ("passes", "more"): "{T} have the ball", ("passes", "less"): "{T} can't get on the ball",
    ("goals", "more"): "{T} are scoring more", ("goals", "less"): "{T} are scoring less",
    ("completed_passes", "more"): "{T} are completing more passes",
    ("completed_passes", "less"): "{T} are completing fewer passes",
}


def named_team(question: str) -> str | None:
    q = question.lower()
    return next((side for side, names in ALIASES.items() if any(n in q for n in names)), None)


def plan(job: Job) -> None:
    """Orchestrator: choose the team, minute window and metrics to investigate."""
    q = job.question.lower()
    job.focus = named_team(q) or job.focus

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


def premise_take(job: Job) -> Claim | None:
    """The assumption inside the viewer's question, as a checkable take (only when a team is named)."""
    team = named_team(job.question)
    q = job.question.lower()
    if team is None:
        return None
    start, end = job.window
    for triggers, metric, relation, compare, take in PREMISES:
        if any(t in q for t in triggers):
            return Claim(
                id="Q1", team=team, metric=metric, start=start, end=end,
                value=window_stats(team, start, end)[metric], relation=relation, compare=compare,
                text=take.format(T=TEAMS[team]["name"], O=TEAMS[other(team)]["name"]),
                evidence_ids=pick_evidence(team, metric, start, end), proposed_by="Your question", premise=True,
            )
    return None


def _eye_test(team: str, metric: str, compare: str, end: int) -> tuple[str, str] | None:
    """(team, relation) a viewer would conclude from the last few minutes, or None if nothing stands out."""
    recent_start = max(1, end - EYE_TEST_MINUTES + 1)
    mine = window_stats(team, recent_start, end)
    if compare == "opponent":
        theirs = window_stats(other(team), recent_start, end)
    else:
        if recent_start - EYE_TEST_MINUTES < 1:
            return None
        theirs = window_stats(team, recent_start - EYE_TEST_MINUTES, recent_start - 1)
    if metric == "pass_accuracy" and min(mine["passes"], theirs["passes"]) < 3:
        return None
    a, b = mine[metric] or 0, theirs[metric] or 0
    if a == b:
        return None
    if compare == "opponent":
        return (team, "more") if a > b else (other(team), "more")
    return team, "more" if a > b else "less"


def propose(job: Job, limit: int = 4) -> list[Claim]:
    focus, opp = job.focus, other(job.focus)
    start, end = job.window
    ranked = sorted(TOPICS, key=lambda t: (t[0] not in job.priorities, TOPICS.index(t)))
    claims = []
    for metric, compare, whose in ranked:
        read = _eye_test(opp if whose == "opponent" else focus, metric, compare, end)
        if read is None:
            continue
        team, relation = read
        claims.append(Claim(
            id=f"C{len(claims) + 1}", team=team, metric=metric, start=start, end=end,
            value=window_stats(team, start, end)[metric], relation=relation, compare=compare,
            text=PHRASES[(metric, relation)].format(T=TEAMS[team]["name"]),
            evidence_ids=pick_evidence(team, metric, start, end),
        ))
        if len(claims) == limit:
            break
    return claims


def revise(rejected: list[Claim]) -> list[Claim]:
    """Turn a busted take around when the data shows the opposite (never when level)."""
    revised = []
    for c in rejected:
        if c.actual_value is None or c.compare_value is None or c.actual_value == c.compare_value:
            continue
        if c.compare == "opponent":
            team, relation = other(c.team), c.relation
        else:
            team, relation = c.team, "less" if c.relation == "more" else "more"
        revised.append(Claim(
            id=f"{c.id}R", team=team, metric=c.metric, start=c.start, end=c.end,
            value=window_stats(team, c.start, c.end)[c.metric], relation=relation, compare=c.compare,
            text=PHRASES[(c.metric, relation)].format(T=TEAMS[team]["name"]),
            evidence_ids=pick_evidence(team, c.metric, c.start, c.end),
            proposed_by="Pundit (revision)", revision_of=c.id,
        ))
    return revised


def narrate(job: Job) -> str:
    """Template Narrator: what the question assumed, which takes hold up, which don't and what's really going on."""
    start, end = job.window
    analyst = job.mode == "analyst"
    data = (lambda c: f" ({c.finding.rstrip('.')})") if analyst else (lambda c: "")
    premise = next((c for c in job.claims if c.premise), None)
    revisions = {c.revision_of: c for c in job.claims if c.revision_of and c.verdict in ("verified", "corrected")}
    holds = [c for c in job.claims if c.verdict in ("verified", "corrected") and not c.premise and not c.revision_of]
    busted = [c for c in job.claims if c.verdict == "rejected" and not c.premise and c.finding]
    parts = []
    if premise:
        answer = {"verified": "the data backs that up", "corrected": "the data backs that up",
                  "rejected": "the data says otherwise", "unproven": "it's too early to tell"}[premise.verdict]
        parts.append(f"Your question assumes {premise.text}: {answer}{data(premise)}.")
    for c in holds[:2]:
        parts.append(f"{c.text}, that holds up{data(c)}.")
    for c in busted[:1]:
        fix = revisions.get(c.id)
        parts.append(f"{'But ' if parts else ''}\"{c.text}\" doesn't hold up{data(c)}."
                     + (f" {fix.text}." if fix else ""))
    if not parts:
        return f"Not enough evidence in minutes {start}-{end} to back or bust any take yet."
    return " ".join(parts)
