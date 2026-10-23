"""The MatchMind agent team, wired as a Microsoft Agent Framework workflow.

Orchestrator -> Stats -> Pundit -> Skeptic -> Narrator. The Pundit voices the popular takes (plus
the assumption inside the viewer's question); the Skeptic checks each against the event log and can
send busted takes back to the Pundit for one revision round.
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
        job.log("Stats", "Computed the spell's numbers from the event log",
                f"Possession {h['possession'] or 0:.0f}%-{a['possession'] or 0:.0f}%, shots {h['shots']}-{a['shots']}, "
                f"pressures {h['pressures']}-{a['pressures']}, recoveries {h['recoveries']}-{a['recoveries']} "
                f"({len(window_events(start, end))} events).", "ok")
        await ctx.send_message(job)


class Pundit(Executor):
    def __init__(self, client=None):
        super().__init__(id="pundit")
        self.client = client

    async def _takes(self, job: Job, rejected) -> list:
        if job.needs_revision:
            return (await llm.propose(self.client, job, rejected)) if self.client else offline.revise(rejected)
        covered = tuple(c.metric for c in job.claims if c.premise)  # the question's own topic is already checked
        return (await llm.propose(self.client, job)) if self.client else offline.propose(job, limit=3, skip=covered)

    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        start, end = job.window
        if not job.needs_revision and len(window_events(start, end)) < MIN_WINDOW_EVENTS:
            job.log("Pundit", "Held back", "Too little has happened in this spell to have a take.", "warn")
            await ctx.send_message(job)
            return
        if not job.needs_revision and (premise := offline.premise_take(job)):
            job.claims.append(premise)
            job.log("Pundit", "Picked out the assumption in your question", premise.text)
        rejected = [c for c in job.claims if c.verdict == "rejected" and not c.revision_of and not c.premise]
        try:
            new = await self._takes(job, rejected)
        except Exception as exc:  # model outage must not take the dashboard down
            job.log("Pundit", "Model call failed, using rule-based takes", type(exc).__name__, "warn")
            job.engine = "offline"
            self.client = None
            new = await self._takes(job, rejected)
        seen = {c.key() for c in job.claims}
        repeats = [c for c in new if c.key() in seen]
        new = [c for c in new if c.key() not in seen]
        if repeats:
            job.log("Pundit", "Dropped repeated takes", f"{len(repeats)} take(s) were already checked.", "warn")
        if job.needs_revision:
            job.rounds += 1
            job.needs_revision = False
            job.log("Pundit", f"Rethought after the Skeptic's pushback (round {job.rounds})",
                    "; ".join(c.text for c in new) or "No better take; letting the busted ones go.")
        else:
            job.log("Pundit", f"Gave {len(new)} take(s)", "; ".join(c.text for c in new))
        job.claims += new
        await ctx.send_message(job)


class Skeptic(Executor):
    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        for claim in [c for c in job.claims if c.verdict == "pending"]:
            verify_claim(claim, job.minute)
            offline.explain_simply(claim)
            status = {"verified": "ok", "corrected": "warn", "unproven": "info", "rejected": "reject"}[claim.verdict]
            label = {"verified": "Holds up", "corrected": "Half-right", "unproven": "Not enough evidence",
                     "rejected": "Doesn't hold up"}[claim.verdict]
            job.log("Skeptic", f"{label}: {claim.text}", f"{claim.finding} {claim.reason}".strip(), status)
        unrevised = [c for c in job.claims if c.verdict == "rejected" and not c.revision_of and not c.premise]
        job.needs_revision = bool(unrevised) and job.rounds < MAX_REVISIONS
        if job.needs_revision:
            job.log("Skeptic", "Pushed back to the Pundit", f"{len(unrevised)} take(s) don't hold up.", "warn")
        # route explicitly: the job is shared and mutable, so edge conditions would see later state
        await ctx.send_message(job, target_id="pundit" if job.needs_revision else "narrator")


class Narrator(Executor):
    def __init__(self, client=None):
        super().__init__(id="narrator")
        self.client = client

    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Never, Job]) -> None:
        checked = [c for c in job.claims if c.verdict != "pending"]
        job.narrative, job.narrative_source = offline.narrate(job), "template"
        if self.client and any(c.finding for c in checked):
            try:
                text = await llm.narrate(self.client, job, checked)
                bad = llm.ungrounded_numbers(text, job, checked)
                if bad:
                    job.log("Narrator", "Grounding guard blocked the model's draft",
                            f"Numbers the Skeptic never produced: {', '.join(bad)}. Using the template.", "reject")
                elif text:
                    job.narrative, job.narrative_source = text, "model"
            except Exception as exc:
                job.log("Narrator", "Model call failed, using the template", type(exc).__name__, "warn")
        held = sum(c.verdict in ("verified", "corrected") for c in checked)
        job.log("Narrator", f"Wrote the {job.mode} explanation",
                f"{held} of {len(checked)} take(s) held up ({job.narrative_source}).", "ok")
        await ctx.yield_output(job)


def build_workflow(client=None):
    orchestrator, stats, skeptic = Orchestrator(id="orchestrator"), Stats(id="stats"), Skeptic(id="skeptic")
    pundit, narrator = Pundit(client), Narrator(client)
    return (
        WorkflowBuilder(name="matchmind-analysis", start_executor=orchestrator)
        .add_edge(orchestrator, stats)
        .add_edge(stats, pundit)
        .add_edge(pundit, skeptic)
        .add_edge(skeptic, pundit)
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
