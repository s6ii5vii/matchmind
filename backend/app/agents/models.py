"""Messages that flow between the MatchMind agents."""

from collections.abc import Callable
from dataclasses import asdict, dataclass, field

METRIC_LABELS = {
    "goals": "goals", "shots": "shots", "xg": "synthetic xG",
    "passes": "passes", "completed_passes": "completed passes", "pass_accuracy": "pass accuracy",
    "possession": "possession", "final_third_entries": "final-third entries",
    "pressures": "pressure events", "recoveries": "ball recoveries", "tackles_won": "tackles won",
    "turnovers": "times losing the ball",
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
    plain: str = ""  # the take in everyday words, for people new to football
    plain_finding: str = ""  # the finding in everyday words
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


class Relay:
    """Passes agent steps to whoever is watching. The workflow may deep-copy messages between agents,
    so this must stay the same object rather than copying whatever it reports to."""
    def __init__(self, send: Callable[[dict], None]):
        self.send = send

    def __call__(self, item: dict) -> None:
        self.send(item)

    def __copy__(self) -> "Relay":
        return self

    def __deepcopy__(self, memo: dict) -> "Relay":
        return self


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
    moment: str = ""  # what happened, when the question asks about a specific key moment
    narrative: str = ""
    narrative_source: str = ""
    trace: list[TraceStep] = field(default_factory=list)
    # called with each step as it happens, so the dashboard can show the agents working live
    listener: Callable[[dict], None] | None = field(default=None, repr=False, compare=False)

    def log(self, agent: str, action: str, detail: str, status: str = "info") -> None:
        step = TraceStep(agent, action, detail, status)
        self.trace.append(step)
        if self.listener:
            self.listener({"type": "step", **asdict(step)})

    def working(self, agent: str, what: str) -> None:
        if self.listener:
            self.listener({"type": "working", "agent": agent, "detail": what})

    def to_dict(self) -> dict:
        listener, self.listener = self.listener, None
        try:
            data = asdict(self)
        finally:
            self.listener = listener
        data.pop("listener")
        data["window"] = list(self.window)
        return data
