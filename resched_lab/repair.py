"""Rescheduling (repair) methods (register: M6, D1, N5, I8).

All methods start from the state at the decision time t (committed operations
fixed, known downtimes) and return a new published Plan.

RS – right-shift: the plan's machine sequences and assignments are kept; the
     disruption is propagated (execution projection) and the shifted times are
     published as the new plan.
MU – match-up (N5a, soft): CP-SAT re-optimises operations whose reference start
     < T_mu = t + 2·D; operations with reference start ≥ T_mu keep machine and
     sequence and cannot start before their planned start, so the schedule rejoins
     the plan where the window absorbs the delay and is right-shifted otherwise.
FR – full rescheduling: CP-SAT re-optimises all not-yet-started operations.
Instability in the repair objective is measured against the currently published
plan (I8).
"""
from __future__ import annotations

import time
from .execution import Plan, project
from .schedule import Slot
from .optimize import solve, list_schedule, sgs_schedule
from .schedule import metrics, lex_key


def plan_as_ref(inst, plan: Plan) -> dict:
    return {oid: Slot(plan.assign[oid], plan.pstart[oid], plan.pstart[oid] + inst.op(oid).p)
            for oid in plan.pstart if oid[0] in inst.jobs}


def repair(method, inst, plan: Plan, state, gamma, norm, D, time_limit, workers=2):
    """Returns (new_plan, info dict)."""
    t = state.t
    t0 = time.perf_counter()
    rs_sched = project(inst, plan, state)
    if method == "RS":
        new = Plan.from_schedule(inst, rs_sched)
        return new, dict(method="RS", rt=time.perf_counter() - t0, status="RS", T_mu=None)
    ref = plan_as_ref(inst, plan)
    if method == "FR":
        # I15: construction heuristics (priority rules decoded from the current state);
        # the best of them and the RS projection is the CP-SAT hint, and FR returns the
        # better of CP-SAT and that incumbent (portfolio) – never worse than its hint
        cands = {"RS": rs_sched}
        rem = [j.id for j in inst.jobs.values() if any(o.id not in state.committed for o in j.ops)]
        first = {jid: min((rs_sched[o.id].start for o in inst.jobs[jid].ops
                           if o.id not in state.committed), default=0) for jid in rem}
        orders = {
            "EDD": sorted(rem, key=lambda j: (inst.jobs[j].due, j)),
            "HARD-EDD": sorted(rem, key=lambda j: (not inst.jobs[j].hard, inst.jobs[j].due, j)),
            "PLAN+RUSH-EDD": sorted(rem, key=lambda j: ((inst.jobs[j].due - 10**9) if inst.jobs[j].rush
                                                        else first[j], j)),
        }
        for k, order in orders.items():
            cands[k] = list_schedule(inst, order, t, state.committed, state.downtimes)
        score = lambda sch: lex_key(metrics(inst, sch, ref), norm, gamma)
        inc_name, inc = min(cands.items(), key=lambda kv: score(kv[1]))
        r = solve(inst, t, state.committed, state.downtimes, gamma, norm, ref=ref,
                  time_limit=time_limit, hint=inc, workers=workers)
        rt = time.perf_counter() - t0
        best, src = inc, inc_name
        if r.sched is not None and score(r.sched) <= score(inc):
            best, src = r.sched, "CPSAT"
        return Plan.from_schedule(inst, best), dict(method="FR", rt=rt, det=r.det_time,
                                                    status=f"{r.status}|{src}", T_mu=None)
    if method == "MU":
        T_mu = t + max(1, 2 * D)
        # I15: match-up-compatible construction heuristics (SGS respecting the tail
        # constraints: machine, machine order and no start before plan after T_mu)
        tail = {o: sl for o, sl in ref.items()
                if sl.start >= T_mu and o not in state.committed and not inst.jobs[o[0]].rush}
        chains = {}
        for o, sl in sorted(tail.items(), key=lambda kv: kv[1].start):
            chains.setdefault(sl.machine, []).append(o)
        fixed = {o: sl.machine for o, sl in tail.items()}
        mins = {o: sl.start for o, sl in tail.items()}
        pstart = lambda o: ref[o].start if o in ref else t
        rush_due = lambda o: inst.jobs[o[0]].due if inst.jobs[o[0]].rush else None
        prios = {
            "PLAN": lambda o: (pstart(o), o),
            "PLAN+RUSH-EDD": lambda o: ((0, rush_due(o), o) if rush_due(o) is not None
                                        else (1, pstart(o), o)),
        }
        cands = {"RS": rs_sched}
        for k, pr in prios.items():
            cands[k] = sgs_schedule(inst, t, state.committed, state.downtimes, pr, fixed, mins, chains)
        score = lambda sch: lex_key(metrics(inst, sch, ref), norm, gamma)
        inc_name, inc = min(cands.items(), key=lambda kv: score(kv[1]))
        r = solve(inst, t, state.committed, state.downtimes, gamma, norm, ref=ref,
                  T_mu=T_mu, time_limit=time_limit, hint=inc, workers=workers)
        rt = time.perf_counter() - t0
        best, src = inc, inc_name
        if r.sched is not None and score(r.sched) <= score(inc):
            best, src = r.sched, "CPSAT"
        return Plan.from_schedule(inst, best), dict(method="MU", rt=rt, det=r.det_time,
                                                    status=f"{r.status}|{src}", T_mu=T_mu)
    raise ValueError(method)
