"""Problem instance model (register: M1, U2, U3, I5, I10).

An instance is a set of jobs; each job is an ordered chain of operations.
Each operation has a set of eligible machines (JSP: one machine; flexible
flow shop: the parallel machines of its stage) and an integer processing time.
All times are integers in the instance time unit (`time_unit`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import csv
import math
import random


@dataclass(frozen=True)
class Op:
    job: str
    k: int                      # position in job route (0-based)
    machines: tuple             # eligible machines
    p: int                      # processing time

    @property
    def id(self) -> tuple:
        return (self.job, self.k)


@dataclass
class Job:
    id: str
    ops: list                   # list[Op]
    release: int = 0
    due: int = 10**12
    weight: float = 1.0
    hard: bool = False          # hard due date (lexicographic priority, D7)
    rush: bool = False          # arrived as rush order during execution
    order: str = ""             # customer order (gear line: product type batch)


@dataclass
class Instance:
    name: str
    machines: list
    jobs: dict = field(default_factory=dict)   # job id -> Job
    time_unit: str = "min"
    stage_of: dict = field(default_factory=dict)  # machine -> stage name (FFS)

    # ---- helpers -------------------------------------------------------
    def ops(self):
        for j in self.jobs.values():
            yield from j.ops

    def op(self, oid):
        return self.jobs[oid[0]].ops[oid[1]]

    def total_p(self):
        return sum(o.p for o in self.ops())

    def n_ops(self):
        return sum(len(j.ops) for j in self.jobs.values())

    def mean_p(self):
        return self.total_p() / self.n_ops()

    def mean_weight(self):
        ws = [j.weight for j in self.jobs.values()]
        return sum(ws) / len(ws)

    def lower_bound_cmax(self):
        """Simple LB (I12): max(job chain length + release, machine load / #machines of stage)."""
        lb_job = max(j.release + sum(o.p for o in j.ops) for j in self.jobs.values())
        load = {}
        for o in self.ops():
            key = tuple(sorted(o.machines))
            load[key] = load.get(key, 0) + o.p
        lb_mach = max(math.ceil(v / len(k)) for k, v in load.items())
        return max(lb_job, lb_mach)

    def copy(self):
        import copy
        return copy.deepcopy(self)


# ---------------------------------------------------------------------------
# Illustrative job-shop instance (5 machines x 10 jobs), data from build_case.py
# ---------------------------------------------------------------------------
_ROUTES_5x10 = {
    "J01": [("M1", 45), ("M2", 30), ("M1", 25), ("M3", 40)],
    "J02": [("M2", 50), ("M4", 35), ("M4", 20), ("M3", 30)],
    "J03": [("M1", 45), ("M2", 30), ("M1", 25), ("M3", 40)],
    "J04": [("M5", 55), ("M4", 35), ("M4", 20), ("M3", 30)],
    "J05": [("M5", 60), ("M5", 35), ("M5", 35), ("M3", 40)],
    "J06": [("M2", 50), ("M4", 35), ("M4", 20), ("M3", 30)],
    "J07": [("M1", 45), ("M2", 30), ("M1", 25), ("M3", 40)],
    "J08": [("M5", 55), ("M4", 35), ("M4", 20), ("M3", 30)],
    "J09": [("M5", 60), ("M2", 30), ("M5", 35), ("M3", 40)],
    "J10": [("M2", 50), ("M4", 35), ("M4", 20), ("M3", 30)],
}
# job: (release, due, hard, priority)  -- priority 1 = most important
_META_5x10 = {
    "J01": (0, 240, True, 2), "J02": (0, 300, True, 1), "J03": (0, 360, False, 3),
    "J04": (0, 420, True, 2), "J05": (30, 300, True, 1), "J06": (30, 360, False, 3),
    "J07": (60, 480, False, 2), "J08": (60, 420, True, 1), "J09": (90, 480, False, 3),
    "J10": (90, 480, False, 2),
}


def priority_to_weight(priority: int) -> float:
    """I5: w = 4 - priority (priority 1 -> w = 3; rush priority 0 -> w = 4)."""
    return float(4 - priority)


def load_js5x10() -> Instance:
    inst = Instance(name="JS5x10", machines=["M1", "M2", "M3", "M4", "M5"], time_unit="min")
    for j, route in _ROUTES_5x10.items():
        r, d, hard, pr = _META_5x10[j]
        ops = [Op(j, k, (m,), p) for k, (m, p) in enumerate(route)]
        inst.jobs[j] = Job(j, ops, release=r, due=d, weight=priority_to_weight(pr), hard=hard)
    return inst


# ---------------------------------------------------------------------------
# Production case: automated gear-wheel line (flexible flow shop), zautomatyzowany2.csv
# ---------------------------------------------------------------------------
STAGES = ["CNC", "Hobbing", "Broaching", "Deburring", "Washing", "Inspection"]
MACHINES_AUTOMATED = [2, 2, 1, 1, 1, 1]
TIME_SCALE_LINE = 1           # I10: 1 s units (rounding error < 0.5 s per operation)


def load_gear_line(csv_path: str, machines_per_stage=MACHINES_AUTOMATED,
                   scale: int = TIME_SCALE_LINE, name="GearLineAutomated") -> Instance:
    """Loads the flexible-flow-shop line. Each unit of 'liczba sztuk' becomes a job.
    Due dates, releases, weights and hard/soft flags are generated separately
    (generate_due_dates, register U3)."""
    machines, stage_of, stage_m = [], {}, []
    for s, n in zip(STAGES, machines_per_stage):
        ms = [f"{s}{i + 1}" for i in range(n)]
        machines += ms
        stage_m.append(tuple(ms))
        for m in ms:
            stage_of[m] = s
    inst = Instance(name=name, machines=machines, time_unit="s", stage_of=stage_of)
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f, delimiter=";"))
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        base, reps = row[0].strip(), int(row[1])
        times = [round(float(x.replace(",", ".")) * scale) for x in row[2:8]]
        for r in range(1, reps + 1):
            jid = base if reps == 1 else f"{base}_{r}"
            ops = [Op(jid, k, stage_m[k], times[k]) for k in range(6)]
            inst.jobs[jid] = Job(jid, ops, order=base)
    return inst


def generate_order_attributes(inst: Instance, seed: int, release_span: int,
                              margin=(0.05, 0.35), hard_share: float = 0.3,
                              weights=(1, 2, 3)) -> Instance:
    """U3 (refined 25.09 – due-date quotation): attributes are drawn per customer ORDER
    (all sub-lots of one product batch share them).
      r_o ~ U[0, release_span]
      C_o^q  = completion of order o in a finite-capacity quotation plan
               (FIFO by release, greedy permutation decoder, I14)
      d_o = C_o^q + u_o·(C_o^q − r_o),   u_o ~ U[margin]      (safety allowance)
      hard with probability hard_share, weight uniform from `weights`.
    Rationale: due dates quoted against the shop's actual load (finite-capacity
    planning) – a pure TWK rule ignores congestion and yields unrealistic lateness."""
    from .optimize import list_schedule
    rng = random.Random(seed)
    orders = {}
    for j in inst.jobs.values():
        orders.setdefault(j.order or j.id, []).append(j)
    attrs = {}
    for oid in sorted(orders, key=lambda x: (len(x), x)):
        attrs[oid] = dict(r=int(rng.uniform(0, release_span)), u=rng.uniform(*margin),
                          hard=rng.random() < hard_share, w=float(rng.choice(weights)))
    for oid, js in orders.items():
        for j in js:
            j.release, j.hard, j.weight = attrs[oid]["r"], attrs[oid]["hard"], attrs[oid]["w"]
            j.due = 10 ** 12
    fifo = sorted(inst.jobs, key=lambda jid: (inst.jobs[jid].release, jid))
    q = list_schedule(inst, fifo)
    for oid, js in orders.items():
        c = max(q[j.ops[-1].id].end for j in js)
        r = attrs[oid]["r"]
        for j in js:
            j.due = int(c + attrs[oid]["u"] * (c - r))
    return inst
