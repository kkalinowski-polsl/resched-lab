"""Plan execution / projection – the digital-twin emulator (register: M3, D1, D4, I1, I9, I11).

Execution semantics (I1): operations are processed on each machine in the
sequence of the published plan; an operation starts at
    max(planned start, machine ready, job predecessor end, release, t_now),
moved to the end of any downtime window it would start in; with the `resume`
policy (D4) it is paused by a downtime and continues afterwards.

Because execution between two disruption events is deterministic, the realised
schedule is obtained by projecting the current plan from the current state and
committing every operation whose projected start precedes the next event time.
This is equivalent to a discrete-event simulation of the shop floor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from .schedule import Slot, downtime_overlap


@dataclass
class Plan:
    """Published plan: machine assignment, planned start, machine sequences."""
    assign: dict                       # oid -> machine
    pstart: dict                       # oid -> planned start
    seq: dict                          # machine -> [oid, ...]

    @classmethod
    def from_schedule(cls, inst, sched: dict):
        seq = {m: [] for m in inst.machines}
        for oid, sl in sorted(sched.items(), key=lambda kv: (kv[1].start, kv[1].end)):
            seq[sl.machine].append(oid)
        return cls(assign={o: s.machine for o, s in sched.items()},
                   pstart={o: s.start for o, s in sched.items()}, seq=seq)

    def copy(self):
        return Plan(dict(self.assign), dict(self.pstart), {m: list(v) for m, v in self.seq.items()})


@dataclass
class State:
    """Shop-floor state at time t: committed (started) operations with their slots,
    known machine downtime windows."""
    t: int = 0
    committed: dict = field(default_factory=dict)   # oid -> Slot
    downtimes: list = field(default_factory=list)   # (machine, d0, d1)

    def copy(self):
        return State(self.t, dict(self.committed), list(self.downtimes))


class Deadlock(Exception):
    pass


def _start_after_downtime(m, s, downtimes):
    moved = True
    while moved:
        moved = False
        for (mm, d0, d1) in downtimes:
            if mm == m and d0 <= s < d1:
                s, moved = d1, True
    return s


def _end_with_resume(m, s, p, downtimes):
    e = s + p
    while True:
        e2 = s + p + downtime_overlap(m, s, e, downtimes)
        if e2 == e:
            return e
        e = e2


def project(inst, plan: Plan, state: State) -> dict:
    """Projects the plan from `state`; returns the complete schedule
    (committed slots + projected slots of not-yet-started operations)."""
    sched = dict(state.committed)
    job_ready = {}
    for j in inst.jobs.values():
        r = j.release
        for o in j.ops:
            if o.id in sched:
                r = sched[o.id].end
        job_ready[j.id] = r
    mach_ready = {m: 0 for m in inst.machines}
    for oid, sl in state.committed.items():
        mach_ready[sl.machine] = max(mach_ready[sl.machine], sl.end)
    queues = {m: [o for o in plan.seq.get(m, []) if o not in sched] for m in inst.machines}
    ptr = {m: 0 for m in inst.machines}
    remaining = sum(len(q) for q in queues.values())
    while remaining:
        progress = False
        for m in inst.machines:
            q = queues[m]
            while ptr[m] < len(q):
                oid = q[ptr[m]]
                job, k = oid
                if k > 0 and (job, k - 1) not in sched:
                    break
                o = inst.op(oid)
                s = max(plan.pstart.get(oid, 0), mach_ready[m], job_ready[job], state.t)
                s = _start_after_downtime(m, s, state.downtimes)
                e = _end_with_resume(m, s, o.p, state.downtimes)
                sched[oid] = Slot(m, s, e)
                mach_ready[m], job_ready[job] = e, e
                ptr[m] += 1
                remaining -= 1
                progress = True
        if not progress:
            raise Deadlock("plan sequences inconsistent with precedence")
    return sched


def commit_until(inst, plan: Plan, state: State, t: int) -> tuple:
    """Advances execution to time t: every operation whose projected start is < t
    becomes committed. Returns (new_state, projected_schedule)."""
    sched = project(inst, plan, state)
    new = state.copy()
    for oid, sl in sched.items():
        if sl.start < t:
            new.committed[oid] = sl
    new.t = t
    return new, sched


# ---------------------------------------------------------------------------
# Disruption events (M3)
# ---------------------------------------------------------------------------
@dataclass
class Breakdown:
    t: int
    machine: str
    duration: int
    kind: str = "breakdown"

    @property
    def D(self):                # disruption duration for T_mu (N5)
        return self.duration


@dataclass
class RushOrder:
    t: int
    jobs: list                  # list[instance.Job] (rush=True, release = t); >1 for multi-unit orders
    kind: str = "rush"

    @property
    def D(self):
        return sum(o.p for j in self.jobs for o in j.ops)


@dataclass
class DueDateChange:
    t: int
    job_id: str
    new_due: int
    new_hard: bool = True
    new_weight: float | None = None
    kind: str = "duedate"
    D: int = 0                   # set when applied (tardiness created)


def apply_event(inst, plan: Plan, state: State, ev, interrupt_policy="resume"):
    """Applies event at state.t == ev.t under IGNORE semantics (D1, I11):
    the plan's sequences are kept; the event is absorbed by execution.
    Mutates inst (rush job / due date) and returns (plan, state)."""
    plan, state = plan.copy(), state.copy()
    if isinstance(ev, Breakdown):
        d0, d1 = ev.t, ev.t + ev.duration
        # operation in progress on the failed machine
        for oid, sl in list(state.committed.items()):
            if sl.machine == ev.machine and sl.start < d0 < sl.end:
                if interrupt_policy == "resume":
                    state.committed[oid] = Slot(sl.machine, sl.start, sl.end + (d1 - d0))
                else:  # restart: whole operation re-processed after repair
                    del state.committed[oid]
                    plan.pstart[oid] = d1
        state.downtimes.append((ev.machine, d0, d1))
    elif isinstance(ev, RushOrder):
        # append each op to the end of a machine queue (I11); FFS: machine whose
        # queue currently ends earliest
        proj = project(inst, plan, state)
        ends = {m: 0 for m in inst.machines}
        for sl in proj.values():
            ends[sl.machine] = max(ends[sl.machine], sl.end)
        for job in ev.jobs:
            inst.jobs[job.id] = job
            for o in job.ops:
                m = min(o.machines, key=lambda mm: (ends[mm], mm))
                ends[m] += o.p
                plan.seq[m].append(o.id)
                plan.assign[o.id] = m
                plan.pstart[o.id] = ev.t
    elif isinstance(ev, DueDateChange):
        j = inst.jobs[ev.job_id]
        j.due, j.hard = ev.new_due, ev.new_hard
        if ev.new_weight is not None:
            j.weight = ev.new_weight
    else:
        raise TypeError(ev)
    return plan, state
