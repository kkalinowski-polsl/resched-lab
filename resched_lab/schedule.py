"""Schedule representation, feasibility validator and evaluation metrics
(register: M1, M2, D7, D7a, I8).

A schedule maps operation id (job, k) -> Slot(machine, start, end).
With the `resume` interruption policy (D4) an operation may span a machine
downtime window; its net processing time end - start - overlap(downtime) must
then equal p.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Slot:
    machine: str
    start: int
    end: int


def overlap(a0, a1, b0, b1):
    return max(0, min(a1, b1) - max(a0, b0))


def downtime_overlap(machine, s, e, downtimes):
    return sum(overlap(s, e, d0, d1) for (m, d0, d1) in downtimes if m == machine)


class InfeasibleSchedule(Exception):
    pass


def validate(inst, sched: dict, downtimes=(), eps=0) -> list:
    """Returns list of violations (empty = feasible). Checks: completeness,
    eligibility, net processing time, release, precedence, machine capacity,
    no processing during downtime."""
    err = []
    for o in inst.ops():
        if o.id not in sched:
            err.append(f"missing {o.id}")
            continue
        sl = sched[o.id]
        if sl.machine not in o.machines:
            err.append(f"{o.id} on ineligible {sl.machine}")
        net = sl.end - sl.start - downtime_overlap(sl.machine, sl.start, sl.end, downtimes)
        if abs(net - o.p) > eps:
            err.append(f"{o.id} net time {net} != p {o.p}")
        # an operation may not START inside a downtime window
        for (m, d0, d1) in downtimes:
            if m == sl.machine and d0 <= sl.start < d1:
                err.append(f"{o.id} starts in downtime of {m} [{d0},{d1})")
    for j in inst.jobs.values():
        prev_end = j.release
        for o in j.ops:
            if o.id not in sched:
                continue
            if sched[o.id].start < prev_end - eps:
                err.append(f"{o.id} starts {sched[o.id].start} before {prev_end}")
            prev_end = sched[o.id].end
    by_m = {}
    for oid, sl in sched.items():
        by_m.setdefault(sl.machine, []).append((sl.start, sl.end, oid))
    for m, lst in by_m.items():
        lst.sort()
        for a, b in zip(lst, lst[1:]):
            if b[0] < a[1] - eps:
                err.append(f"{m}: {a[2]} [{a[0]},{a[1]}) overlaps {b[2]} [{b[0]},{b[1]})")
    return err


def assert_feasible(inst, sched, downtimes=()):
    err = validate(inst, sched, downtimes)
    if err:
        raise InfeasibleSchedule("; ".join(err[:10]))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def completion_times(inst, sched):
    return {j.id: sched[j.ops[-1].id].end for j in inst.jobs.values()}


def metrics(inst, sched, ref=None) -> dict:
    """Raw metrics. `ref`: reference schedule for instability Δ (I8);
    only operations present in both and of non-rush jobs are compared."""
    C = completion_times(inst, sched)
    cmax = max(C.values())
    t_hard = t_soft = n_tardy_hard = 0.0
    for j in inst.jobs.values():
        T = max(0, C[j.id] - j.due)
        if j.hard:
            t_hard += j.weight * T
            n_tardy_hard += T > 0
        else:
            t_soft += j.weight * T
    delta = 0
    n_seq_changes = 0
    if ref is not None:
        for oid, sl in sched.items():
            if oid in ref and not inst.jobs[oid[0]].rush:
                delta += abs(sl.start - ref[oid].start)
                n_seq_changes += sl.machine != ref[oid].machine
    return dict(cmax=cmax, wt_hard=t_hard, wt_soft=t_soft, n_tardy_hard=int(n_tardy_hard),
                delta=delta, n_machine_changes=n_seq_changes)


@dataclass
class Norm:
    """Normalisation constants (D7a)."""
    cmax0: float      # Cmax(σ0)  (or LB when σ0 is being built, I12)
    sum_p: float      # Σ p over all ops
    delta_scale: float  # n_ops * mean p

    @classmethod
    def from_instance(cls, inst, cmax0):
        return cls(cmax0=float(cmax0), sum_p=float(inst.total_p()),
                   delta_scale=float(inst.n_ops() * inst.mean_p()))


def objective(m: dict, norm: Norm, gamma: float) -> float:
    """D7: f = (1-γ)·½(Ĉmax + T̂soft) + γ·Δ̂. Hard tardiness is handled
    lexicographically and reported separately (m['wt_hard'])."""
    c_hat = m["cmax"] / norm.cmax0
    t_hat = m["wt_soft"] / norm.sum_p
    d_hat = m["delta"] / norm.delta_scale
    return (1 - gamma) * 0.5 * (c_hat + t_hat) + gamma * d_hat


def lex_key(m, norm, gamma):
    """Lexicographic comparison: hard weighted tardiness first, then f."""
    return (round(m["wt_hard"], 6), objective(m, norm, gamma))


def machine_loads(inst, sched):
    load = {}
    for oid, sl in sched.items():
        load[sl.machine] = load.get(sl.machine, 0) + inst.op(oid).p
    return load
