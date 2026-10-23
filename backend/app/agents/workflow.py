"""The MatchMind agent team, wired as a Microsoft Agent Framework workflow.

Orchestrator -> Stats -> Tactics -> Skeptic -> Narrator, with the Skeptic able to send
rejected claims back to Tactics for one revision round.
"""

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler
from typing_extensions import Never

from ..synthetic import TEAMS
from . import llm, offline
from .models import Job
from .tools import verify_claim, window_events, window_stats

MAX_REVISIONS = 1
MIN_WINDOW_EVENTS = 4


class Orchestrator(Executor):
    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        offline.plan(job)
        start, end = job.window
        focus = TEAMS[job.focus]["name"]
        detail = f"Following {focus}, minutes {start}-{end}"
        if job.priorities:
            detail += f", prioritising {', '.join(job.priorities)}"
        job.log("Orchestrator", "Planned the investigation", detail + ".")
        await ctx.send_message(job)


class Stats(Executor):
    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        start, end = job.window
        job.stats = {side: window_stats(side, start, end) for side in TEAMS}
        h, a = job.stats["home"], job.stats["away"]
        job.log("Stats", "Computed window stats from the event log",
                f"Shots {h['shots']}-{a['shots']}, pressures {h['pressures']}-{a['pressures']}, "
                f"turnovers {h['turnovers']}-{a['turnovers']} ({len(window_events(start, end))} events).", "ok")
        await ctx.send_message(job)


class Tactics(Executor):
    def __init__(self, client=None):
        super().__init__(id="tactics")
        self.client = client

    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        start, end = job.window
        if not job.needs_revision and len(window_events(start, end)) < MIN_WINDOW_EVENTS:
            job.log("Tactics", "Declined to speculate", "Too few events in this window to propose anything.", "warn")
            await ctx.send_message(job)
            return
        rejected = [c for c in job.claims if c.verdict == "rejected" and not c.revision_of]
        try:
            if job.needs_revision:
                new = (await llm.propose(self.client, job, rejected)) if self.client else offline.revise(rejected)
            else:
                new = (await llm.propose(self.client, job)) if self.client else offline.propose(job)
        except Exception as exc:  # model outage must not take the dashboard down
            job.log("Tactics", "Model call failed, using rule-based hypotheses", type(exc).__name__, "warn")
            job.engine = "offline"
            self.client = None
            new = offline.revise(rejected) if job.needs_revision else offline.propose(job)
        seen = {c.key() for c in job.claims}
        repeats = [c for c in new if c.key() in seen]
        new = [c for c in new if c.key() not in seen]
        if repeats:
            job.log("Tactics", "Dropped repeated claims", f"{len(repeats)} claim(s) were already reviewed.", "warn")
        if job.needs_revision:
            job.rounds += 1
            job.needs_revision = False
            job.log("Tactics", f"Revised after Skeptic feedback (round {job.rounds})",
                    "; ".join(c.text for c in new) or "No revision is defensible; dropping the rejected claims.")
        else:
            job.log("Tactics", f"Proposed {len(new)} claim(s)", "; ".join(c.text for c in new))
        job.claims += new
        await ctx.send_message(job)


class Skeptic(Executor):
    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        for claim in [c for c in job.claims if c.verdict == "pending"]:
            verify_claim(claim, job.minute)
            status = {"verified": "ok", "corrected": "warn", "rejected": "reject"}[claim.verdict]
            job.log("Skeptic", f"{claim.verdict.capitalize()} {claim.id}: {claim.text}", claim.reason, status)
        unrevised = [c for c in job.claims if c.verdict == "rejected" and not c.revision_of]
        job.needs_revision = bool(unrevised) and job.rounds < MAX_REVISIONS
        if job.needs_revision:
            job.log("Skeptic", "Sent rejected claims back to Tactics", f"{len(unrevised)} claim(s) to revise.", "warn")
        # route explicitly: the job is shared and mutable, so edge conditions would see later state
        await ctx.send_message(job, target_id="tactics" if job.needs_revision else "narrator")


class Narrator(Executor):
    def __init__(self, client=None):
        super().__init__(id="narrator")
        self.client = client

    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Never, Job]) -> None:
        accepted = [c for c in job.claims if c.verdict in ("verified", "corrected")]
        job.narrative, job.narrative_source = offline.narrate(job, accepted), "template"
        if self.client and accepted:
            try:
                text = await llm.narrate(self.client, job, accepted)
                bad = llm.ungrounded_numbers(text, job, accepted)
                if bad:
                    job.log("Narrator", "Grounding guard blocked the model's draft",
                            f"Numbers not in any verified claim: {', '.join(bad)}. Using the template.", "reject")
                elif text:
                    job.narrative, job.narrative_source = text, "model"
            except Exception as exc:
                job.log("Narrator", "Model call failed, using the template", type(exc).__name__, "warn")
        job.log("Narrator", f"Wrote the {job.mode} explanation",
                f"From {len(accepted)} verified claim(s) ({job.narrative_source}).", "ok")
        await ctx.yield_output(job)


def build_workflow(client=None):
    orchestrator, stats, skeptic = Orchestrator(id="orchestrator"), Stats(id="stats"), Skeptic(id="skeptic")
    tactics, narrator = Tactics(client), Narrator(client)
    return (
        WorkflowBuilder(name="matchmind-analysis", start_executor=orchestrator)
        .add_edge(orchestrator, stats)
        .add_edge(stats, tactics)
        .add_edge(tactics, skeptic)
        .add_edge(skeptic, tactics)
        .add_edge(skeptic, narrator)
        .build()
    )


async def run_analysis(minute: int, mode: str = "fan", focus: str = "home", question: str = "",
                       client=None, provider: str = "offline") -> dict:
    job = Job(minute=minute, mode=mode, focus=focus, question=question.strip()[:300],
              engine=provider if client else "offline")
    if minute < 1:
        job.log("Orchestrator", "Waiting for kick-off", "No events have happened yet.", "warn")
        job.narrative, job.narrative_source = "The match hasn't started yet.", "template"
        return job.to_dict()
    result = await build_workflow(client).run(job)
    return result.get_outputs()[-1].to_dict()
