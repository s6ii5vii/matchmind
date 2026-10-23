"""Rule-based agent behaviour, used when no model provider is configured.

The rule-based Pundit reads the game like a viewer: it forms each take from the last five minutes
(what you just watched) and states it about the whole spell. That's usually right, but recency bias
sometimes catches it out, and the Skeptic, which checks the whole spell, decides.
"""

import re

from ..moments import moment_at, moment_sentence
from ..synthetic import TEAMS
from .models import METRIC_LABELS, Claim, Job
from .tools import other, pick_evidence, too_close, window_stats

KEYWORDS = {
    "press": ["pressures", "recoveries"], "pressur": ["pressures", "recoveries"], "win the ball": ["recoveries"],
    "tackl": ["tackles_won"], "shot": ["shots", "xg"], "chance": ["xg", "shots"], "xg": ["xg", "shots"],
    "attack": ["final_third_entries", "xg"], "dangerous": ["xg", "final_third_entries"], "pass": ["pass_accuracy"],
    "control": ["possession", "pass_accuracy"], "possession": ["possession"], "the ball": ["possession"],
    "rhythm": ["pass_accuracy"], "turnover": ["turnovers"], "lose the ball": ["turnovers"],
    "lost the ball": ["turnovers"], "giving the ball": ["turnovers"], "momentum": ["final_third_entries", "pressures"],
    "goal": ["xg", "shots"],
}
ALIASES = {"home": ("northbridge", "nbr"), "away": ("riverside", "rsu")}

# what a pundit talks about: (metric, compare, whose: focus|opponent|either)
TOPICS = [
    ("possession", "opponent", "either"),
    ("pressures", "opponent", "either"),
    ("recoveries", "opponent", "either"),
    ("xg", "opponent", "either"),
    ("final_third_entries", "previous", "focus"),
    ("pass_accuracy", "previous", "opponent"),
    ("shots", "previous", "focus"),
    ("turnovers", "previous", "opponent"),
]
EYE_TEST_MINUTES = 5

# assumptions a question can carry: (trigger phrases, metric, relation, compare, take)
PREMISES = [
    (("lose control", "lost control", "losing control"), "possession", "less", "opponent",
     "{T} lost control of the ball"),
    (("press work", "press is work", "pressing work", "press pay", "pressing pay"), "recoveries", "more", "opponent",
     "{T}'s press is winning the ball back"),
    (("press",), "pressures", "more", "opponent", "{T} are pressing harder than {O}"),
    (("struggl", "no chances", "can't create"), "final_third_entries", "less", "previous",
     "{T} are struggling to get forward"),
    (("dangerous", "better chances", "creating chances"), "xg", "more", "opponent",
     "{T} are creating the better chances"),
    (("sloppy", "careless", "giving the ball away", "giving it away"), "turnovers", "more", "previous",
     "{T} are giving the ball away more"),
    (("fading", "tired", "dropped off", "running out"), "pressures", "less", "previous", "{T} are fading"),
    (("dominat", "on top", "in control", "ran the show", "running the show"), "possession", "more", "opponent",
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
    ("passes", "more"): "{T} are seeing more of the ball", ("passes", "less"): "{T} can't get on the ball",
    ("possession", "more"): "{T} have taken control of the ball", ("possession", "less"): "{T} can't keep the ball",
    ("recoveries", "more"): "{T} keep winning the ball back", ("recoveries", "less"): "{T} can't win the ball back",
    ("final_third_entries", "more"): "{T} are getting into the final third more",
    ("final_third_entries", "less"): "{T} can't get into the final third",
    ("goals", "more"): "{T} are scoring more", ("goals", "less"): "{T} are scoring less",
    ("completed_passes", "more"): "{T} are completing more passes",
    ("completed_passes", "less"): "{T} are completing fewer passes",
}


# the same ideas for someone who has never watched football
PLAIN = {
    ("pressures", "more"): "{T} are chasing the other team hard to win the ball back",
    ("pressures", "less"): "{T} have stopped chasing the ball as hard",
    ("xg", "more"): "{T} are getting the better chances to score",
    ("xg", "less"): "{T} are getting worse chances to score",
    ("shots", "more"): "{T} are shooting at goal more", ("shots", "less"): "{T} are hardly shooting at goal",
    ("pass_accuracy", "more"): "{T}'s passes are finding a teammate more often",
    ("pass_accuracy", "less"): "{T}'s passes keep going to the wrong place",
    ("turnovers", "more"): "{T} keep losing the ball", ("turnovers", "less"): "{T} are keeping hold of the ball",
    ("tackles_won", "more"): "{T} are winning more challenges", ("tackles_won", "less"): "{T} are losing challenges",
    ("passes", "more"): "{T} are passing the ball around more", ("passes", "less"): "{T} are barely getting a pass in",
    ("completed_passes", "more"): "{T} are passing the ball around more",
    ("completed_passes", "less"): "{T} are barely getting a pass in",
    ("possession", "more"): "{T} have had the ball most of the time",
    ("possession", "less"): "{T} have hardly had the ball",
    ("recoveries", "more"): "{T} keep winning the ball back", ("recoveries", "less"): "{T} can't win the ball back",
    ("final_third_entries", "more"): "{T} are getting near the other team's goal more often",
    ("final_third_entries", "less"): "{T} can't get near the other team's goal",
    ("goals", "more"): "{T} are scoring more", ("goals", "less"): "{T} are scoring less",
}
PLAIN_UNITS = {
    "possession": "of the time on the ball", "pressures": "times chasing down an opponent",
    "recoveries": "balls won back", "turnovers": "times losing the ball", "xg": "goals' worth of chances",
    "final_third_entries": "trips near the other team's goal", "shots": "shots", "goals": "goals",
    "pass_accuracy": "of passes reaching a teammate", "tackles_won": "challenges won", "passes": "passes",
    "completed_passes": "passes reaching a teammate",
}


def _plain_number(metric: str, value: float) -> str:
    if metric in ("possession", "pass_accuracy"):
        return f"{value:.0f}%"
    if metric == "xg":
        return f"{value:.1f}"
    return f"{value:g}"


def explain_simply(claim: Claim) -> None:
    """Fill in the everyday-words version of a checked take."""
    team, opp = TEAMS[claim.team]["name"], TEAMS[other(claim.team)]["name"]
    claim.plain = PLAIN[(claim.metric, claim.relation)].format(T=team)
    if claim.actual_value is None or claim.compare_value is None:
        claim.plain_finding = "Too little has happened yet to say either way."
        return
    a, b = _plain_number(claim.metric, claim.actual_value), _plain_number(claim.metric, claim.compare_value)
    unit = PLAIN_UNITS[claim.metric]
    if claim.compare == "opponent":
        claim.plain_finding = f"{team}: {a} {unit}. {opp}: {b}."
    else:
        trend = "up from" if claim.actual_value > claim.compare_value else \
            "down from" if claim.actual_value < claim.compare_value else "the same as"
        claim.plain_finding = f"{team}: {a} {unit}, {trend} {b} in the minutes before."


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
    elif m := re.search(r"\bat\s*(\d{1,2})\b", q):  # "what led to the goal at 72?": the ten minutes up to it
        start, end = int(m[1]) - 9, int(m[1])
        if found := moment_at(job.minute, int(m[1]), named_team(q)):
            job.moment = moment_sentence(found)
    elif "first half" in q:
        start, end = 1, 45
    elif "second half" in q:
        start, end = 46, 90
    start, end = max(1, min(start, end)), max(start, end)
    if end > job.minute:
        job.log("Orchestrator", "Clamped window",
                f"Question asks about minute {end}, but only {job.minute} minutes have been played.", "warn")
        end = job.minute
    if start > end:  # the whole period asked about is still to come
        start = max(1, end - 9)
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


def _eye_test(team: str, metric: str, compare: str, end: int,
              minutes: int = EYE_TEST_MINUTES) -> tuple[str, str] | None:
    """(team, relation) a viewer would conclude from the last few minutes, or None if nothing stands out."""
    recent_start = max(1, end - minutes + 1)
    mine = window_stats(team, recent_start, end)
    if compare == "opponent":
        theirs = window_stats(other(team), recent_start, end)
    else:
        if recent_start - minutes < 1:
            return None
        theirs = window_stats(team, recent_start - minutes, recent_start - 1)
    if metric == "pass_accuracy" and min(mine["passes"], theirs["passes"]) < 3:
        return None
    a, b = mine[metric] or 0, theirs[metric] or 0
    if too_close(metric, a, b):
        return None
    if compare == "opponent":
        return (team, "more") if a > b else (other(team), "more")
    return team, "more" if a > b else "less"


def propose(job: Job, limit: int = 4, skip: tuple[str, ...] = ()) -> list[Claim]:
    focus, opp = job.focus, other(job.focus)
    start, end = job.window
    ranked = sorted((t for t in TOPICS if t[0] not in skip),
                    key=lambda t: (t[0] not in job.priorities, TOPICS.index(t)))
    claims = []
    # a pundit goes on the last five minutes; if they were quiet, on the last ten
    reads = [(t, _eye_test(opp if t[2] == "opponent" else focus, t[0], t[1], end)) for t in ranked]
    if sum(r is not None for _, r in reads) < 2:
        reads = [(t, _eye_test(opp if t[2] == "opponent" else focus, t[0], t[1], end, 2 * EYE_TEST_MINUTES))
                 for t in ranked]
    for (metric, compare, _), read in reads:
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


def _they(first: Claim, second: Claim) -> str:
    """Second reason about the same team reads better as 'they'."""
    if second.team != first.team:
        return second.plain
    name = TEAMS[second.team]["name"]
    rest = second.plain[len(name):]
    return ("their" + rest[2:]) if rest.startswith("'s") else "they" + rest


def narrate_simply(job: Job) -> str:
    """For people new to football: a short answer first, then the reasons, no jargon."""
    premise = next((c for c in job.claims if c.premise), None)
    revisions = {c.revision_of: c for c in job.claims if c.revision_of and c.verdict in ("verified", "corrected")}
    holds = [c for c in job.claims if c.verdict in ("verified", "corrected") and not c.premise and not c.revision_of]
    busted = [c for c in job.claims if c.verdict == "rejected" and not c.premise and c.finding]
    parts = []
    if premise:
        answer = {"verified": "you're right", "corrected": "you're right", "rejected": "not really",
                  "unproven": "it's too early to tell"}[premise.verdict]
        parts.append(f"Short answer: {answer}. {premise.plain_finding}")
    if holds:
        reasons = [holds[0].plain] + [_they(holds[0], c) for c in holds[1:2]]
        parts.append(("Here's why: " if premise else "What's happening: ") + " and ".join(reasons) + ".")
    for c in busted[:1]:
        if fix := revisions.get(c.id):
            parts.append(f"You might hear that {c.plain}, but it's the other way round: {fix.plain}.")
    if not parts:
        return "Not much has happened yet, so there's nothing clear to say."
    return " ".join(parts)


def narrate(job: Job) -> str:
    """Template Narrator: what the question assumed, which takes hold up, which don't and what's really going on.
    A question about a specific moment starts with what actually happened."""
    text = narrate_simply(job) if job.mode == "simple" else _narrate(job)
    if not job.moment:
        return text
    return f"{job.moment} In the ten minutes before it: {text.removeprefix("What's happening: ")}"


def _narrate(job: Job) -> str:
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
