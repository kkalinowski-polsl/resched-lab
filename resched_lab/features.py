"""Decision features computed by the digital twin (register: M4, D3, I2, I3, I4, U4).

All features compare two projections of the current plan made at time t:
  P_ref – the shop as planned before the (possibly aggregated) disruption,
  P_dis – the shop after the disruption, absorbed by execution (IGNORE semantics).

Im  (I2): relative impact  [max(0,ΔCmax) + Σ_j (w_j/w̄)·max(0,ΔT_j)] / Cmax(σ0), clipped to [0,1]
Cr  (D3): share of unfinished jobs whose completion time or tardiness increases
W   (I3, eq. 9 of the conference version): time until the earliest not-yet-started
          operation whose timing changes (an interrupted operation in progress does not
          count – it cannot be rescheduled any more), or –
          for jobs that become (more) tardy – the slack d_j − t − Σ remaining p_j (≥ 0)
W_rel (I4/U4b): W / L_FR, L_FR = lead time of implementing a full reschedule
Dr  (variant A, Q2): delivery risk – share of unfinished jobs that are delayed and whose
          slack d_j − C_j falls below slack_tol (2 % of Cmax(σ0)) or whose tardiness grows
H   (variant B, Q2): hard due-date threat – Σ_hard (w_j/w̄)·ΔT_j / (5 % of Cmax(σ0)), clipped to [0,1]
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Features:
    Im: float
    Cr: float
    W: float
    W_rel: float
    d_cmax: float
    d_wt: float
    n_affected_jobs: int
    n_unfinished: int
    Dr: float = 0.0          # variant A: delivery risk
    H: float = 0.0           # variant B: hard due-date threat


def job_tardiness(job, C):
    return max(0, C - job.due)


def compute_features(inst_ref, P_ref: dict, inst_dis, P_dis: dict, t: int,
                     cmax0: float, L_FR: float, w_bar: float, cr_tol: float = 0.0,
                     slack_tol_rel: float = 0.02, hard_scale_rel: float = 0.05) -> Features:
    """cr_tol: a job counts as affected only if its completion time grows by more
    than cr_tol (time units) or its tardiness grows (proposal D3a)."""
    C_ref = {j.id: P_ref[j.ops[-1].id].end for j in inst_ref.jobs.values()}
    C_dis = {j.id: P_dis[j.ops[-1].id].end for j in inst_dis.jobs.values()}
    cmax_ref, cmax_dis = max(C_ref.values()), max(C_dis.values())
    d_cmax = max(0, cmax_dis - cmax_ref)

    d_wt = 0.0
    d_hard = 0.0
    at_risk = 0
    slack_tol = slack_tol_rel * cmax0
    affected, unfinished = 0, 0
    w_candidates = []
    for j in inst_dis.jobs.values():
        T_dis = job_tardiness(j, C_dis[j.id])
        if j.id in inst_ref.jobs:
            T_ref = job_tardiness(inst_ref.jobs[j.id], C_ref[j.id])
            is_new = False
        else:
            T_ref, is_new = 0, True            # rush order
        dT = max(0, T_dis - T_ref)
        d_wt += (j.weight / w_bar) * dT
        if j.hard:
            d_hard += (j.weight / w_bar) * dT
        if dT > 0:
            rem = sum(o.p for o in j.ops if P_dis[o.id].start >= t)
            w_candidates.append(max(0, j.due - t - rem))
        if not is_new and C_ref[j.id] > t:      # unfinished existing job
            unfinished += 1
            if C_dis[j.id] - C_ref[j.id] > cr_tol or dT > 0:
                affected += 1
            # variant A: delayed job whose remaining slack to its due date falls below
            # slack_tol (or which becomes more tardy) – delivery is threatened
            if (C_dis[j.id] > C_ref[j.id] and j.due - C_dis[j.id] < slack_tol) or dT > 0:
                at_risk += 1
    # earliest changed operation (not started before t in the reference projection)
    for oid, sl in P_ref.items():
        if oid in P_dis and sl.start >= t and P_dis[oid] != sl:
            w_candidates.append(sl.start - t)
    W = min(w_candidates) if w_candidates else float(cmax_dis - t)
    Im = min(1.0, (d_cmax + d_wt) / cmax0)
    Cr = affected / unfinished if unfinished else 0.0
    Dr = at_risk / unfinished if unfinished else 0.0
    H = min(1.0, d_hard / (hard_scale_rel * cmax0))
    return Features(Im=Im, Cr=Cr, W=float(W), W_rel=float(W) / L_FR, d_cmax=d_cmax,
                    d_wt=d_wt, n_affected_jobs=affected, n_unfinished=unfinished, Dr=Dr, H=H)
