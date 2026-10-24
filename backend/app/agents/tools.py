"""Deterministic tools the agents call. Numbers only ever come from here, never from a model."""

from ..analysis import LOST_BALL, RECOVERY, _team_stats, final_third
from ..synthetic import EVENTS, EVENTS_BY_ID, TEAMS, label, span
from .models import METRIC_LABELS, Claim

TOLERANCE = {"xg": 0.05, "pass_accuracy": 2.0, "possession": 3.0}
MIN_PASSES_FOR_ACCURACY = 4
MIN_SAMPLE = 3  # combined events (or shots, for xG) needed before a comparison means anything


def other(team: str) -> str:
    return "away" if team == "home" else "home"


def window_events(start: int, end: int) -> list[dict]:
    return [e for e in EVENTS if start <= e["minute"] <= end]


def window_stats(team: str, start: int, end: int) -> dict:
    """Event counts for one team between two minutes, inclusive."""
    return _team_stats(window_events(start, end), team)


def supports(e: dict, team: str, metric: str) -> bool:
    """Whether an event is evidence for team's number on this metric."""
    if metric == "turnovers":
        return e["possession_team"] == team and e["possession_end"] in LOST_BALL
    if e["team"] != team:
        return False
    if metric in ("goals", "shots", "xg"):
        return e["type"] == "shot" and (e["is_goal"] or metric != "goals")
    if metric == "possession":
        return e["type"] == "pass" and e["outcome"] == "complete"
    if metric == "final_third_entries":
        return final_third(e)
    if metric == "recoveries":
        return e["type"] in RECOVERY and e["outcome"] == "won"
    if metric == "tackles_won":
        return e["type"] == "tackle" and e["outcome"] == "won"
    if metric == "pressures":
        return e["type"] == "pressure"
    return e["type"] == "pass"


def pick_evidence(team: str, metric: str, start: int, end: int, limit: int = 4) -> list[str]:
    return [e["id"] for e in window_events(start, end) if supports(e, team, metric)][-limit:]


# differences smaller than this aren't worth a take either way
MIN_GAP = {"possession": 3.0, "pass_accuracy": 3.0, "xg": 0.1}


def too_close(metric: str, a: float, b: float) -> bool:
    return abs(a - b) < MIN_GAP.get(metric, 2)


def _metric(team: str, metric: str, start: int, end: int) -> float | None:
    stats = window_stats(team, start, end)
    if metric == "pass_accuracy" and stats["passes"] < MIN_PASSES_FOR_ACCURACY:
        return None
    return stats[metric]


def _fmt(metric: str, value: float | None) -> str:
    if value is None:
        return "n/a"
    if metric == "xg":
        return f"{value:.2f}"
    if metric in ("pass_accuracy", "possession"):
        return f"{value:.1f}%"
    return f"{value:g}"


def verify_claim(claim: Claim, minute: int) -> Claim:
    """Skeptic's check: recompute the take from the event log.

    verified  - holds up as stated
    corrected - right direction, but a number or evidence ID was wrong (fixed)
    unproven  - too little evidence either way, so neither confirmed nor busted
    rejected  - the data says otherwise (or the take is malformed / looks into the future)
    """
    def verdict(kind: str, reason: str) -> Claim:
        claim.verdict, claim.reason = kind, reason
        return claim

    if (claim.team not in TEAMS or claim.metric not in METRIC_LABELS
            or claim.relation not in ("more", "less") or claim.compare not in ("opponent", "previous")):
        return verdict("rejected", "Malformed claim: unknown team, metric, relation or comparison.")
    if claim.end > minute:
        return verdict("rejected", f"Refers to {label(claim.end)}, but the match is only at {label(minute)}.")
    if not 1 <= claim.start <= claim.end:
        return verdict("rejected", "Invalid minute window.")

    team_name, metric = TEAMS[claim.team]["name"], METRIC_LABELS[claim.metric]
    actual = _metric(claim.team, claim.metric, claim.start, claim.end)
    if actual is None:
        return verdict("unproven", f"Too few passes by {team_name} in {span(claim.start, claim.end)} "
                                   "to judge accuracy.")

    if claim.compare == "opponent":
        baseline = _metric(other(claim.team), claim.metric, claim.start, claim.end)
        baseline_shots = _metric(other(claim.team), "shots", claim.start, claim.end)
    else:
        length = claim.end - claim.start + 1
        if claim.start - length < 1:
            return verdict("unproven", "No earlier spell of the same length to compare against yet.")
        baseline = _metric(claim.team, claim.metric, claim.start - length, claim.start - 1)
        baseline_shots = _metric(claim.team, "shots", claim.start - length, claim.start - 1)
    if baseline is None:
        return verdict("unproven", "The earlier spell has too few passes to judge accuracy.")

    claim.actual_value, claim.compare_value = actual, baseline
    if claim.compare == "opponent":
        claim.finding = (f"{team_name} {_fmt(claim.metric, actual)} vs {TEAMS[other(claim.team)]['name']} "
                         f"{_fmt(claim.metric, baseline)} {metric}, {span(claim.start, claim.end)}.")
    else:
        claim.finding = (f"{team_name} {metric}: {_fmt(claim.metric, actual)} in {span(claim.start, claim.end)}, "
                         f"{_fmt(claim.metric, baseline)} in the {claim.end - claim.start + 1} minutes before.")
    if claim.metric == "xg":  # xG sums are always non-zero-ish; judge the sample by shot count
        sample = _metric(claim.team, "shots", claim.start, claim.end) + baseline_shots
    else:
        sample = MIN_SAMPLE if claim.metric == "pass_accuracy" else actual + baseline
    if sample < MIN_SAMPLE:
        return verdict("unproven", "Too few events to call it a pattern either way.")
    if too_close(claim.metric, actual, baseline):
        return verdict("unproven", "Too close to call.")
    holds = actual > baseline if claim.relation == "more" else actual < baseline
    if not holds:
        return verdict("rejected", "Level." if actual == baseline else "The data points the other way.")

    notes = []
    tolerance = TOLERANCE.get(claim.metric, 0)
    if abs(float(claim.value) - actual) > tolerance:
        notes.append(f"stated {_fmt(claim.metric, claim.value)}, log shows {_fmt(claim.metric, actual)}")
        claim.value = actual

    valid = [i for i in claim.evidence_ids
             if (e := EVENTS_BY_ID.get(i)) and supports(e, claim.team, claim.metric)
             and claim.start <= e["minute"] <= claim.end]
    if len(valid) < len(claim.evidence_ids):
        notes.append(f"dropped {len(claim.evidence_ids) - len(valid)} evidence ID(s) that don't support it")
    claim.evidence_ids = valid or pick_evidence(claim.team, claim.metric, claim.start, claim.end)

    if notes:
        return verdict("corrected", "Right direction; " + "; ".join(notes) + ".")
    return verdict("verified", "Holds up as stated.")
