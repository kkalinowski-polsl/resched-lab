"""Scenario definitions (register: N3). E1 scenarios are placed relative to σ0
of the illustrative instance so that each represents a qualitatively distinct
class of disruption; see the comments for the local justification."""
from .instance import Job, Op
from .execution import Breakdown, RushOrder, DueDateChange


def rush_shaft(t, slack, jid="JX"):
    """Rush order of product type A (shaft), route M1-M2-M1-M3 (as J01/J03/J07),
    priority 0 -> w = 4 (I5), hard due date t + slack."""
    ops = [Op(jid, k, (m,), p) for k, (m, p) in enumerate([("M1", 45), ("M2", 30), ("M1", 25), ("M3", 40)])]
    return RushOrder(t, [Job(jid, ops, release=t, due=t + slack, weight=4.0, hard=True, rush=True, order=jid)])


def e1_scenarios():
    return {
        # S1 – short failure of a non-bottleneck machine (M4, load 275 of 455 min)
        "S1": [Breakdown(160, "M4", 20)],
        # S2 – rush order (demand-side disruption) in the first half of the shift
        "S2": [rush_shaft(120, 200)],
        # S3 – cascading: failure of the bottleneck M3 (no idle time in σ0 after t=105),
        #      followed by a due-date tightening of J10 (soft -> hard, d = C_σ0 − 60)
        "S3": [Breakdown(200, "M3", 30), DueDateChange(240, "J10", 315, new_hard=True)],
    }


# ---------------------------------------------------------------------------
# E2 – stochastic disruption streams for the production line (register N4)
# ---------------------------------------------------------------------------
import math
import random
from .instance import Job, Op

E2_LEVELS = {        # machine availability A = MTBF / (MTBF + MTTR)
    "low": 0.97, "medium": 0.93, "high": 0.88,
}


def e2_events(inst, horizon: int, level: str, seed: int, mttr: int = 1800, cv_repair: float = 0.5,
              rush_per_shift: float = 1.0, shift: int = 8 * 3600, rush_units=(1, 4),
              rush_margin: float = 1.5):
    """Breakdowns: per machine, time between failures ~ Exp(MTBF) (operating-time
    independent approximation), repair ~ LogNormal(mean MTTR, CV cv_repair);
    MTBF = A/(1−A)·MTTR. Rush orders: Poisson(rush_per_shift per shift), product
    type uniform among the orders of the instance, 1–4 units, hard due date
    t + rush_margin·(flow time of one unit + (n−1)·max stage time), weight 4.
    All streams use independent sub-seeds (common random numbers across policies)."""
    A = E2_LEVELS[level]
    mtbf = A / (1 - A) * mttr
    s2 = math.log(1 + cv_repair ** 2)
    mu = math.log(mttr) - s2 / 2
    events = []
    for idx, m in enumerate(inst.machines):
        rng = random.Random(seed * 1000 + idx)
        t = rng.expovariate(1 / mtbf)
        while t < horizon:
            d = max(60, int(rng.lognormvariate(mu, math.sqrt(s2))))
            events.append(Breakdown(int(t), m, d))
            t += d + rng.expovariate(1 / mtbf)
    rng = random.Random(seed * 1000 + 999)
    templates = {}
    for j in inst.jobs.values():
        templates.setdefault(j.order or j.id, j)
    types = sorted(templates)
    t, k = rng.expovariate(rush_per_shift / shift), 0
    while t < horizon:
        tpl = templates[rng.choice(types)]
        n = rng.randint(*rush_units)
        k += 1
        oid = f"R{k}"
        jobs = []
        for u in range(n):
            jid = f"{oid}_{u + 1}"
            jobs.append(Job(jid, [Op(jid, o.k, o.machines, o.p) for o in tpl.ops], release=int(t),
                            weight=4.0, hard=True, rush=True, order=oid))
        flow = sum(o.p for o in tpl.ops) + (n - 1) * max(o.p for o in tpl.ops)
        for j in jobs:
            j.due = int(t + rush_margin * flow)
        events.append(RushOrder(int(t), jobs))
        t += rng.expovariate(rush_per_shift / shift)
    return sorted(events, key=lambda e: (e.t, e.kind))
