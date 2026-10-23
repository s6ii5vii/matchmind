"""Deterministic tools the agents call. Numbers only ever come from here, never from a model."""

from ..analysis import _team_stats
from ..synthetic import EVENTS, TEAMS
from .models import METRIC_EVIDENCE, METRIC_LABELS, Claim

EVENTS_BY_ID = {e["id"]: e for e in EVENTS}
TOLERANCE = {"xg": 0.05, "pass_accuracy": 2.0}
MIN_PASSES_FOR_ACCURACY = 4
MIN_SAMPLE = 3  # combined events (or shots, for xG) needed before a comparison means anything


def other(team: str) -> str:
    return "away" if team == "home" else "home"


def window_events(start: int, end: int) -> list[dict]:
    return [e for e in EVENTS if start <= e["minute"] <= end]


def window_stats(team: str, start: int, end: int) -> dict:
    """Event counts for one team between two minutes, inclusive."""
    return _team_stats(window_events(start, end), team)


def pick_evidence(team: str, metric: str, start: int, end: int, limit: int = 4) -> list[str]:
    kind = METRIC_EVIDENCE[metric]
    events = [e for e in window_events(start, end) if e["team"] == team and e["type"] == kind]
    if metric == "goals":
        events = [e for e in events if e["is_goal"]]
    return [e["id"] for e in events][-limit:]


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
    if metric == "pass_accuracy":
        return f"{value:.1f}%"
    return f"{value:g}"


def verify_claim(claim: Claim, minute: int) -> Claim:
    """Skeptic's check: recompute the claim from the event log and accept, correct or reject it."""
    def reject(reason: str) -> Claim:
        claim.verdict, claim.reason = "rejected", reason
        return claim

    if (claim.team not in TEAMS or claim.metric not in METRIC_EVIDENCE
            or claim.relation not in ("more", "less") or claim.compare not in ("opponent", "previous")):
        return reject("Malformed claim: unknown team, metric, relation or comparison.")
    if claim.end > minute:
        return reject(f"Refers to minute {claim.end}, but only {minute} minutes have been played.")
    if not 1 <= claim.start <= claim.end:
        return reject("Invalid minute window.")

    team_name, label = TEAMS[claim.team]["name"], METRIC_LABELS[claim.metric]
    actual = _metric(claim.team, claim.metric, claim.start, claim.end)
    if actual is None:
        return reject(f"Too few passes by {team_name} in minutes {claim.start}-{claim.end} to judge accuracy.")

    if claim.compare == "opponent":
        baseline = _metric(other(claim.team), claim.metric, claim.start, claim.end)
        baseline_shots = _metric(other(claim.team), "shots", claim.start, claim.end)
        baseline_label = f"{TEAMS[other(claim.team)]['name']} {_fmt(claim.metric, baseline)}"
    else:
        length = claim.end - claim.start + 1
        if claim.start - length < 1:
            return reject("No earlier window of the same length to compare against.")
        baseline = _metric(claim.team, claim.metric, claim.start - length, claim.start - 1)
        baseline_shots = _metric(claim.team, "shots", claim.start - length, claim.start - 1)
        baseline_label = f"{_fmt(claim.metric, baseline)} in minutes {claim.start - length}-{claim.start - 1}"
    if baseline is None:
        return reject("Comparison window has too few passes to judge accuracy.")

    claim.actual_value, claim.compare_value = actual, baseline
    if claim.metric == "xg":  # xG sums are always non-zero-ish; judge the sample by shot count
        sample = _metric(claim.team, "shots", claim.start, claim.end) + baseline_shots
    else:
        sample = MIN_SAMPLE if claim.metric == "pass_accuracy" else actual + baseline
    if sample < MIN_SAMPLE:
        return reject(f"{team_name} {label}: {_fmt(claim.metric, actual)} vs {baseline_label}. "
                      "Too few events to call it a pattern.")
    holds = actual > baseline if claim.relation == "more" else actual < baseline
    if not holds:
        return reject(f"{team_name} {label}: {_fmt(claim.metric, actual)} vs {baseline_label}. "
                      f"The data does not show {claim.relation}.")

    notes = []
    tolerance = TOLERANCE.get(claim.metric, 0)
    if abs(float(claim.value) - actual) > tolerance:
        notes.append(f"stated {_fmt(claim.metric, claim.value)}, log shows {_fmt(claim.metric, actual)}")
        claim.value = actual

    kind = METRIC_EVIDENCE[claim.metric]
    valid = [i for i in claim.evidence_ids
             if (e := EVENTS_BY_ID.get(i)) and e["team"] == claim.team and e["type"] == kind
             and claim.start <= e["minute"] <= claim.end]
    if len(valid) < len(claim.evidence_ids):
        notes.append(f"dropped {len(claim.evidence_ids) - len(valid)} evidence ID(s) that don't support it")
    claim.evidence_ids = valid or pick_evidence(claim.team, claim.metric, claim.start, claim.end)

    if notes:
        claim.verdict, claim.reason = "corrected", "Direction holds; " + "; ".join(notes) + "."
    else:
        claim.verdict = "verified"
        claim.reason = f"{team_name} {label}: {_fmt(claim.metric, actual)} vs {baseline_label}."
    return claim
