"""Messages that flow between the MatchMind agents."""

from dataclasses import asdict, dataclass, field

# metric -> event type that can serve as evidence for it
METRIC_EVIDENCE = {
    "goals": "shot", "shots": "shot", "xg": "shot",
    "passes": "pass", "completed_passes": "pass", "pass_accuracy": "pass",
    "pressures": "pressure", "tackles_won": "tackle", "turnovers": "turnover",
}
METRIC_LABELS = {
    "goals": "goals", "shots": "shots", "xg": "synthetic xG",
    "passes": "passes", "completed_passes": "completed passes", "pass_accuracy": "pass accuracy",
    "pressures": "pressure events", "tackles_won": "tackles won", "turnovers": "turnovers",
}


@dataclass
class Claim:
    """A pundit's take, phrased so the Skeptic can check its numbers mechanically.

    compare="opponent": team's metric vs the other team over the same window.
    compare="previous": team's metric vs the equally long window just before.
    """
    id: str
    team: str
    metric: str
    start: int
    end: int
    value: float
    relation: str  # "more" | "less"
    compare: str  # "opponent" | "previous"
    text: str
    evidence_ids: list[str] = field(default_factory=list)
    proposed_by: str = "Pundit"
    revision_of: str | None = None
    premise: bool = False  # tests an assumption hidden in the viewer's question
    verdict: str = "pending"  # verified | corrected | unproven | rejected
    reason: str = ""
    finding: str = ""  # what the event log actually shows, written by the Skeptic
    actual_value: float | None = None
    compare_value: float | None = None

    def key(self) -> tuple:
        return (self.team, self.metric, self.start, self.end, self.relation, self.compare)


@dataclass
class TraceStep:
    agent: str
    action: str
    detail: str
    status: str = "info"  # info | ok | warn | reject


@dataclass
class Job:
    """The shared case file passed along the workflow; each agent adds to it."""
    minute: int
    mode: str
    focus: str
    question: str = ""
    engine: str = "offline"
    window: tuple[int, int] = (0, 0)
    priorities: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    claims: list[Claim] = field(default_factory=list)
    rounds: int = 0
    needs_revision: bool = False
    narrative: str = ""
    narrative_source: str = ""
    trace: list[TraceStep] = field(default_factory=list)

    def log(self, agent: str, action: str, detail: str, status: str = "info") -> None:
        self.trace.append(TraceStep(agent, action, detail, status))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["window"] = list(self.window)
        return data
