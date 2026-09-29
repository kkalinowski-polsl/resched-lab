"""Closed-loop simulation of a rescheduling policy (register: M3, M5, M7, D1, D2, I6, I7, U8).

Decision epochs are disruption events and DEFER review times (τ after the first
deferred event). At every epoch the shop is advanced to the epoch time, the
event is absorbed (IGNORE semantics), features are computed and the policy
decides. The realised schedule is the concatenation of committed operations.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .execution import Plan, State, commit_until, project, apply_event
from .features import compute_features
from .fuzzy import FuzzyParams, fis1, fis2
from .repair import repair
from .schedule import metrics, objective, validate, Norm, lex_key


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------
class Policy:
    name = "base"

    def action(self, f, ev, ctx):          # -> IGNORE / DEFER / RESCHEDULE
        raise NotImplementedError

    def method(self, f, ev, ctx):          # -> RS / MU / FR
        raise NotImplementedError


class Static(Policy):
    name = "STATIC"

    def action(self, f, ev, ctx):
        return "IGNORE", {}


class Always(Policy):
    def __init__(self, m):
        self.m, self.name = m, f"ALWAYS-{m}"

    def action(self, f, ev, ctx):
        return "RESCHEDULE", {}

    def method(self, f, ev, ctx):
        return self.m, {}


class Crisp(Policy):
    """I6: thresholds on Im (θ1, θ2 given in minutes-equivalent of the conference
    version, converted to the relative scale by the caller); method from a
    look-up table by event type."""
    name = "CRISP"
    TABLE = {"breakdown": "MU", "rush": "FR", "duedate": "FR"}

    def __init__(self, th1, th2):
        self.th1, self.th2 = th1, th2

    def action(self, f, ev, ctx):
        a = "IGNORE" if f.Im < self.th1 else ("DEFER" if f.Im < self.th2 else "RESCHEDULE")
        return a, {}

    def method(self, f, ev, ctx):
        kinds = [e.kind for e in ctx["events"]]
        kind = "rush" if "rush" in kinds else ("duedate" if "duedate" in kinds else "breakdown")
        return self.TABLE[kind], {}


class Fuzzy(Policy):
    """variant: '' (base), 'A' (delivery risk Dr replaces Cr in FIS-1),
    'B' (hard due-date threat H -> rule R16 in FIS-2), 'AB' (both)."""

    def __init__(self, params: FuzzyParams | None = None, variant: str = ""):
        self.p = params or FuzzyParams()
        self.p.check()
        self.v = variant
        self.name = "FUZZY" + (f"-{variant}" if variant else "")

    def action(self, f, ev, ctx):
        o = fis1(f.Im, f.Dr if "A" in self.v else f.Cr, self.p)
        return o.action, dict(A=o.A, fis1_rules=o.rules)

    def method(self, f, ev, ctx):
        o = fis2(f.Im, f.W_rel, ctx["gamma"], self.p, H=f.H if "B" in self.v else None)
        return o.method, dict(S=o.S, fis2_rules=o.rules)


class Oracle(Policy):
    """U8: myopic oracle – at every event evaluates RS, MU and FR and keeps the
    best lexicographic result (hard tardiness, then f with Δ vs σ0), assuming no
    further disruptions. A reference, not an implementable policy."""
    name = "ORACLE"

    def action(self, f, ev, ctx):
        return "RESCHEDULE", {}

    def method(self, f, ev, ctx):
        return "ORACLE", {}


# ---------------------------------------------------------------------------
@dataclass
class SimConfig:
    gamma: float = 0.5
    L_FR: float = 20.0              # I4
    tau: float = 30.0               # U6 DEFER review period
    time_limit: float = 10.0        # U9 (deterministic-time units)
    workers: int = 2
    interrupt_policy: str = "resume"


@dataclass
class SimResult:
    policy: str
    realised: dict
    metrics: dict
    f: float
    log: list = field(default_factory=list)
    n_interventions: int = 0
    cpu: float = 0.0


def simulate(inst0, sigma0: dict, events: list, policy: Policy, cfg: SimConfig,
             norm: Norm) -> SimResult:
    inst = copy.deepcopy(inst0)
    plan = Plan.from_schedule(inst, sigma0)
    state = State()
    w_bar = inst0.mean_weight()
    events = sorted(events, key=lambda e: e.t)
    ei = 0
    deferred, defer_ref, review_t = [], None, None
    log, n_int, cpu = [], 0, 0.0

    while ei < len(events) or review_t is not None:
        next_ev_t = events[ei].t if ei < len(events) else None
        is_review = review_t is not None and (next_ev_t is None or review_t < next_ev_t)
        t = review_t if is_review else next_ev_t
        state, _ = commit_until(inst, plan, state, t)
        inst_ref, P_ref = copy.deepcopy(inst), project(inst, plan, state)
        ev = None
        if not is_review:
            ev = copy.deepcopy(events[ei])
            ei += 1
            plan, state = apply_event(inst, plan, state, ev, cfg.interrupt_policy)
        P_dis = project(inst, plan, state)
        if ev is not None and ev.kind == "duedate":        # D of a due-date change = tardiness created
            j = inst.jobs[ev.job_id]
            ev.D = max(1, P_dis[j.ops[-1].id].end - j.due)
        # aggregated features when deferred events are pending (D2)
        if deferred:
            r_inst, r_P = defer_ref
            ctx_events = deferred + ([ev] if ev else [])
        else:
            r_inst, r_P = inst_ref, P_ref
            ctx_events = [ev]
        feats = compute_features(r_inst, r_P, inst, P_dis, t, norm.cmax0, cfg.L_FR, w_bar)
        ctx = dict(gamma=cfg.gamma, events=ctx_events, t=t)
        action, info = policy.action(feats, ev, ctx)
        if is_review and action == "DEFER":
            action = "IGNORE"                      # I7
        entry = dict(t=t, event=(ev.kind if ev else "review"), Im=feats.Im, Cr=feats.Cr,
                     W=feats.W, W_rel=feats.W_rel, Dr=feats.Dr, H=feats.H, action=action, **{k: v for k, v in info.items()
                                                                    if k == "A"})
        if action == "RESCHEDULE":
            D = max(e.D for e in ctx_events if e is not None)
            method, minfo = policy.method(feats, ev, ctx)
            if method == "ORACLE":
                best = None
                for m in ("RS", "MU", "FR"):
                    p_m, rinfo = repair(m, inst, plan, state, cfg.gamma, norm, D,
                                        cfg.time_limit, cfg.workers)
                    cpu += rinfo["rt"]
                    pr = project(inst, p_m, state)
                    key = lex_key(metrics(inst, pr, sigma0), norm, cfg.gamma)
                    if best is None or key < best[0]:
                        best = (key, m, p_m, rinfo)
                _, method, plan, rinfo = best
            else:
                plan, rinfo = repair(method, inst, plan, state, cfg.gamma, norm, D,
                                     cfg.time_limit, cfg.workers)
                cpu += rinfo["rt"]
            n_int += 1
            entry.update(method=method, rt=rinfo["rt"], T_mu=rinfo.get("T_mu"),
                         S=minfo.get("S"))
            deferred, defer_ref, review_t = [], None, None
        elif action == "DEFER":
            if not deferred:
                defer_ref = (inst_ref, P_ref)
                review_t = t + cfg.tau
            deferred.append(ev)
        else:  # IGNORE
            deferred, defer_ref, review_t = [], None, None
        log.append(entry)

    realised = project(inst, plan, state)
    err = validate(inst, realised, state.downtimes)
    if err:
        raise AssertionError(f"{policy.name}: infeasible realised schedule: {err[:5]}")
    m = metrics(inst, realised, sigma0)
    m.update(n_interventions=n_int, cpu=cpu)
    return SimResult(policy.name, realised, m, objective(m, norm, cfg.gamma), log, n_int, cpu)
