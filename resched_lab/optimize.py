"""CP-SAT (OR-Tools) scheduling engine – baseline σ0, Full Rescheduling, Match-Up
(register: Z2, U1, N5, N6, I8, I12, I13).

Model (flexible job shop with fixed/committed intervals and downtimes):
  * committed (already started) operations are fixed intervals; the part of an
    operation lying inside a downtime window is excluded (resume policy);
  * downtime windows are fixed intervals on their machines;
  * every free operation chooses one eligible machine (optional intervals),
    starts not before max(t0, release, predecessor end), is non-preemptive;
  * Match-Up (N5a, soft): operations whose reference start is ≥ T_mu keep their
    reference machine and machine sequence and may not start before their reference
    start – the repair optimises the window [t, T_mu) and rejoins the plan where slack allows;
  * deterministic search (I13): interleave_search + max_deterministic_time;
  * lexicographic objective (N6): stage 1 minimises Σ w·T over hard-due-date jobs,
    stage 2 minimises f (D7) subject to stage-1 optimum.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from ortools.sat.python import cp_model

from .schedule import Slot, Norm


@dataclass
class SolveResult:
    sched: dict | None
    status: str
    wall_time: float
    det_time: float
    hard_obj: float
    obj: float


def _pieces(s, e, m, downtimes):
    """[s,e) minus downtime windows of machine m."""
    cuts = sorted((d0, d1) for (mm, d0, d1) in downtimes if mm == m and d0 < e and d1 > s)
    out, cur = [], s
    for d0, d1 in cuts:
        if d0 > cur:
            out.append((cur, min(d0, e)))
        cur = max(cur, d1)
    if cur < e:
        out.append((cur, e))
    return out


def solve(inst, t0: int, committed: dict, downtimes: list, gamma: float, norm: Norm,
          ref: dict | None = None, T_mu: int | None = None, time_limit: float = 10.0,
          hint: dict | None = None, workers: int = 2) -> SolveResult:
    t_start = time.perf_counter()
    free = [o for o in inst.ops() if o.id not in committed]
    horizon = (max([t0] + [sl.end for sl in committed.values()] + [d1 for (_, _, d1) in downtimes]
                   + [j.release for j in inst.jobs.values()])
               + sum(o.p for o in free) + 1)

    def build(stage, hard_bound=None, hint_sched=None):
        md = cp_model.CpModel()
        per_m = {m: [] for m in inst.machines}
        for (m, d0, d1) in downtimes:
            if d1 > t0 or True:
                per_m[m].append(md.NewFixedSizeIntervalVar(d0, d1 - d0, f"dt_{m}_{d0}"))
        for oid, sl in committed.items():
            for a, b in _pieces(sl.start, sl.end, sl.machine, downtimes):
                per_m[sl.machine].append(md.NewFixedSizeIntervalVar(a, b - a, f"c_{oid}_{a}"))
        S, E, X = {}, {}, {}
        post = {}
        for o in free:
            job = inst.jobs[o.job]
            lb = max(t0, job.release)
            post_mu = (T_mu is not None and ref is not None and o.id in ref
                       and ref[o.id].start >= T_mu and not job.rush)
            if post_mu:
                # N5a (soft match-up): beyond T_mu the operation keeps its machine and its
                # machine sequence and may not start before its planned start (I1); the
                # repair can therefore rejoin the plan but is never infeasible
                s = md.NewIntVar(max(lb, ref[o.id].start), horizon, f"s_{o.id}")
                machines = (ref[o.id].machine,)
                post.setdefault(ref[o.id].machine, []).append((ref[o.id].start, o.id))
            else:
                s = md.NewIntVar(lb, horizon, f"s_{o.id}")
                machines = o.machines
            e = md.NewIntVar(lb, horizon + o.p, f"e_{o.id}")
            md.Add(e == s + o.p)
            S[o.id], E[o.id] = s, e
            if len(machines) == 1:
                per_m[machines[0]].append(md.NewIntervalVar(s, o.p, e, f"i_{o.id}"))
                X[o.id] = {machines[0]: None}
            else:
                lits = {}
                for m in machines:
                    x = md.NewBoolVar(f"x_{o.id}_{m}")
                    per_m[m].append(md.NewOptionalIntervalVar(s, o.p, e, x, f"i_{o.id}_{m}"))
                    lits[m] = x
                md.AddExactlyOne(lits.values())
                X[o.id] = lits
        for m, ivs in per_m.items():
            if len(ivs) > 1:
                md.AddNoOverlap(ivs)
        for m, lst in post.items():                      # keep plan sequence after T_mu
            lst.sort()
            for (_, a), (_, b) in zip(lst, lst[1:]):
                md.Add(S[b] >= E[a])
        # precedence
        for j in inst.jobs.values():
            for k in range(1, len(j.ops)):
                a, b = j.ops[k - 1].id, j.ops[k].id
                if b in S:
                    prev_end = E[a] if a in E else committed[a].end
                    md.Add(S[b] >= prev_end)
        # completion, tardiness
        C, T = {}, {}
        for j in inst.jobs.values():
            last = j.ops[-1].id
            C[j.id] = E[last] if last in E else md.NewConstant(committed[last].end)
            T[j.id] = md.NewIntVar(0, horizon + 10**7, f"T_{j.id}")
            md.AddMaxEquality(T[j.id], [0, C[j.id] - j.due])
        cmax = md.NewIntVar(0, horizon + 10**7, "cmax")
        md.AddMaxEquality(cmax, list(C.values()))
        w_int = {j.id: int(round(j.weight * 100)) for j in inst.jobs.values()}
        hard_expr = sum(w_int[j.id] * T[j.id] for j in inst.jobs.values() if j.hard)
        A = (1 - gamma) * 0.5 / norm.cmax0
        B = (1 - gamma) * 0.5 / norm.sum_p
        G = gamma / norm.delta_scale
        terms = [(A, cmax)] + [(B * j.weight, T[j.id]) for j in inst.jobs.values() if not j.hard]
        if gamma > 0 and ref is not None:
            for oid in S:
                if oid in ref and not inst.jobs[oid[0]].rush:
                    dv = md.NewIntVar(0, horizon + 10**7, f"d_{oid}")
                    md.AddAbsEquality(dv, S[oid] - ref[oid].start)
                    terms.append((G, dv))
        nz = [c for c, _ in terms if c > 0]
        scale = 1000.0 / min(nz)
        coefs = [(int(round(c * scale)), v) for c, v in terms if c > 0]
        f_expr = sum(c * v for c, v in coefs)
        if stage == 1:
            # N6a: stage 1 minimises hard tardiness with f as a subordinate term
            # (weight K = 100 × largest f coefficient per weighted-hard second), so that
            # the stage-1 solution is also reasonable on f; exact lexicographic order is
            # enforced by the stage-2 constraint below
            K = 100 * max(c for c, _ in coefs)
            md.Minimize(K * hard_expr + f_expr)
        else:
            if hard_bound is not None:
                md.Add(hard_expr <= hard_bound)
            md.Minimize(f_expr)
        if hint_sched:
            for oid in S:
                if oid in hint_sched:
                    md.AddHint(S[oid], hint_sched[oid].start)
                    lits = X[oid]
                    for m, x in lits.items():
                        if x is not None:
                            md.AddHint(x, hint_sched[oid].machine == m)
        return md, S, E, X, hard_expr

    def run(md, limit):
        sv = cp_model.CpSolver()
        sv.parameters.num_workers = workers
        # I13: deterministic mode – interleaved search + deterministic time limit
        # (reproducible results); wall-clock time is measured separately as RT.
        sv.parameters.interleave_search = True
        sv.parameters.max_deterministic_time = limit
        sv.parameters.max_time_in_seconds = 20 * limit + 5   # safety cap only
        sv.parameters.random_seed = 0
        st = sv.Solve(md)
        return sv, st

    # stage 1: hard tardiness
    md1, S1, E1, X1, h1 = build(1, hint_sched=hint)
    sv1, st1 = run(md1, 0.3 * time_limit)
    if st1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SolveResult(None, sv1.StatusName(st1), time.perf_counter() - t_start,
                           sv1.deterministic_time, float("nan"), float("nan"))
    hard_best = int(sv1.Value(h1))
    stage1_sched = _extract(sv1, S1, E1, X1)
    md2, S2, E2, X2, _ = build(2, hard_bound=hard_best, hint_sched=stage1_sched)
    sv2, st2 = run(md2, 0.7 * time_limit)
    if st2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        sched = _extract(sv2, S2, E2, X2)
        status = f"{sv1.StatusName(st1)}/{sv2.StatusName(st2)}"
        obj = sv2.ObjectiveValue()
        det = sv1.deterministic_time + sv2.deterministic_time
    else:
        sched, status, obj = stage1_sched, f"{sv1.StatusName(st1)}/stage2-{sv2.StatusName(st2)}", float("nan")
        det = sv1.deterministic_time
    full = dict(committed)
    full.update(sched)
    return SolveResult(full, status, time.perf_counter() - t_start, det, hard_best / 100.0, obj)


def _extract(sv, S, E, X):
    out = {}
    for oid in S:
        lits = X[oid]
        if len(lits) == 1:
            m = next(iter(lits))
        else:
            m = next(mm for mm, x in lits.items() if sv.Value(x))
        out[oid] = Slot(m, sv.Value(S[oid]), sv.Value(E[oid]))
    return out


def _fit(m, s, p, downtimes):
    """Earliest start >= s such that [s, s+p) does not overlap a downtime of m."""
    moved = True
    while moved:
        moved = False
        for (mm, d0, d1) in downtimes:
            if mm == m and s < d1 and s + p > d0:
                s, moved = d1, True
    return s


def list_schedule(inst, job_order, t0=0, committed=None, downtimes=()):
    """Greedy permutation decoder (as in the ACO notebook of the gear-line study):
    jobs in `job_order`, each operation on the eligible machine where it can finish
    earliest (append-only, non-preemptive, avoiding known downtimes). Used as a
    construction heuristic / warm start for CP-SAT (register I14)."""
    committed = committed or {}
    mready = {m: t0 for m in inst.machines}
    for sl in committed.values():
        mready[sl.machine] = max(mready[sl.machine], sl.end)
    out = dict(committed)
    for jid in job_order:
        j = inst.jobs[jid]
        r = max(t0, j.release)
        for o in j.ops:
            if o.id in committed:
                r = committed[o.id].end
                continue
            best = None
            for mm in o.machines:
                st = _fit(mm, max(mready[mm], r), o.p, downtimes)
                if best is None or (st, mm) < best:
                    best = (st, mm)
            s_, m = best
            out[o.id] = Slot(m, s_, s_ + o.p)
            mready[m] = r = s_ + o.p
    return out


def sgs_schedule(inst, t0, committed, downtimes, prio, fixed=None, min_start=None, chains=None):
    """Serial schedule-generation scheme (append-only per machine). At each step the
    ready operation (technological predecessor scheduled and – for chained operations –
    its machine-chain predecessor scheduled) with the smallest priority key is placed at
    its earliest feasible start on its best machine, avoiding known downtimes.
      prio(oid) -> sortable key; fixed: oid -> machine; min_start: oid -> earliest start;
      chains: machine -> ordered list of oids that must keep this order (match-up tail).
    Used as match-up-compatible construction heuristic (I15)."""
    fixed, min_start, chains = fixed or {}, min_start or {}, chains or {}
    chain_prev = {}
    for m, lst in chains.items():
        for a, b in zip(lst, lst[1:]):
            chain_prev[b] = a
    mready = {m: t0 for m in inst.machines}
    for sl in committed.values():
        mready[sl.machine] = max(mready[sl.machine], sl.end)
    out = dict(committed)
    todo = [o for o in inst.ops() if o.id not in committed]
    while todo:
        ready = [o for o in todo
                 if (o.k == 0 or (o.job, o.k - 1) in out) and (o.id not in chain_prev or chain_prev[o.id] in out)]
        if not ready:
            raise RuntimeError("SGS deadlock")
        o = min(ready, key=lambda x: prio(x.id))
        j = inst.jobs[o.job]
        r = max(t0, j.release, out[(o.job, o.k - 1)].end if o.k > 0 else 0, min_start.get(o.id, 0))
        best = None
        for mm in ((fixed[o.id],) if o.id in fixed else o.machines):
            st = _fit(mm, max(mready[mm], r), o.p, downtimes)
            if best is None or (st, mm) < best:
                best = (st, mm)
        st, m = best
        out[o.id] = Slot(m, st, st + o.p)
        mready[m] = st + o.p
        todo.remove(o)
    return out
