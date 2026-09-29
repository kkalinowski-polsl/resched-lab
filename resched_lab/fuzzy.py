"""Two-stage fuzzy decision module (register: M5, U4, U5).

FIS-1  zero-order Sugeno  (Im, Cr)       -> action A ∈ [0,1] -> IGNORE / DEFER / RESCHEDULE
FIS-2  Mamdani + centroid (Im, W_rel, γ) -> score S ∈ [1,3]  -> RS / MU / FR

Rule bases are those of the conference version (Tables 1–2).
Membership-function parameters are fixed a priori on relative (dimensionless)
universes (U4, U5); justification is given next to each parameter set.
AND = min, aggregation = max, Sugeno defuzzification = weighted average,
Mamdani defuzzification = centroid on a 1001-point grid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np


def ramp_down(x, a, b):      # 1 for x<=a, linear to 0 at b
    if x <= a:
        return 1.0
    if x >= b:
        return 0.0
    return (b - x) / (b - a)


def ramp_up(x, a, b):        # 0 for x<=a, linear to 1 at b
    return 1.0 - ramp_down(x, a, b)


def tri(x, a, c, d):         # 0 at a, 1 at c, 0 at d
    if x <= a or x >= d:
        return 0.0
    return (x - a) / (c - a) if x <= c else (d - x) / (d - c)


@dataclass
class FuzzyParams:
    # Im (relative impact, share of Cmax(σ0)):
    #   LOW : 1 up to 2 %, 0 from 5 %   – within ordinary processing-time variability
    #   MED : triangle 2 % – 6 % – 12 %
    #   HIGH: 0 up to 6 %, 1 from 15 %  – ≥15 % ≈ more than an hour of an 8-h shift
    im_a: float = 0.02
    im_b: float = 0.05
    im_c: float = 0.06
    im_d: float = 0.12
    im_u: float = 0.15
    # Cr (share of unfinished jobs affected):
    #   LOW : 1 up to 0.2, 0 from 0.5 (local disturbance)
    #   HIGH: 0 up to 0.3, 1 from 0.7 (system-wide propagation)
    cr_low_a: float = 0.2
    cr_low_b: float = 0.5
    cr_high_a: float = 0.3
    cr_high_b: float = 0.7
    # W_rel = W / L_FR (U4b):
    #   SHORT: 1 while the window does not exceed the FR lead time, 0 from twice that
    #   LONG : complementary
    w_a: float = 1.0
    w_b: float = 2.0
    # γ (stability weight): complementary linear MFs on [0.2, 0.8] (γ = 0.5 → 0.5/0.5)
    g_a: float = 0.2
    g_b: float = 0.8
    # FIS-1 output
    out_ignore: float = 0.0
    out_defer: float = 0.5
    out_resched: float = 1.0
    thr_ignore: float = 0.25
    thr_resched: float = 0.75
    n_grid: int = 1001

    def check(self):
        assert 0 <= self.im_a < self.im_b and self.im_a < self.im_c < self.im_d and self.im_c < self.im_u
        assert self.cr_low_a < self.cr_low_b and self.cr_high_a < self.cr_high_b
        assert self.w_a < self.w_b and self.g_a < self.g_b
        return True


def mf_im(x, p):
    return dict(LOW=ramp_down(x, p.im_a, p.im_b), MED=tri(x, p.im_a, p.im_c, p.im_d),
                HIGH=ramp_up(x, p.im_c, p.im_u))


def mf_cr(x, p):
    return dict(LOW=ramp_down(x, p.cr_low_a, p.cr_low_b), HIGH=ramp_up(x, p.cr_high_a, p.cr_high_b))


def mf_w(x, p):
    return dict(SHORT=ramp_down(x, p.w_a, p.w_b), LONG=ramp_up(x, p.w_a, p.w_b))


def mf_g(x, p):
    return dict(LOW=ramp_down(x, p.g_a, p.g_b), HIGH=ramp_up(x, p.g_a, p.g_b))


FIS1_RULES = [  # (Im, Cr, action)
    ("R1", "LOW", "LOW", "IGNORE"), ("R2", "LOW", "HIGH", "DEFER"),
    ("R3", "MED", "LOW", "DEFER"), ("R4", "MED", "HIGH", "RESCHEDULE"),
    ("R5", "HIGH", "LOW", "RESCHEDULE"), ("R6", "HIGH", "HIGH", "RESCHEDULE"),
]
FIS2_RULES = [  # (Im, W, γ or None, method)
    ("R7", "LOW", "SHORT", None, "RS"), ("R8", "LOW", "LONG", None, "RS"),
    ("R9", "MED", "SHORT", None, "RS"), ("R10", "MED", "LONG", "LOW", "FR"),
    ("R11", "MED", "LONG", "HIGH", "MU"), ("R12", "HIGH", "SHORT", "LOW", "FR"),
    ("R13", "HIGH", "SHORT", "HIGH", "MU"), ("R14", "HIGH", "LONG", "LOW", "FR"),
    ("R15", "HIGH", "LONG", "HIGH", "FR"),
]
METHOD_CENTRE = {"RS": 1.0, "MU": 2.0, "FR": 3.0}


@dataclass
class FIS1Out:
    A: float
    action: str
    mu_im: dict
    mu_cr: dict
    rules: dict


@dataclass
class FIS2Out:
    S: float
    method: str
    mu_im: dict
    mu_w: dict
    mu_g: dict
    rules: dict


def fis1(Im, Cr, p: FuzzyParams) -> FIS1Out:
    mi, mc = mf_im(Im, p), mf_cr(Cr, p)
    out = dict(IGNORE=p.out_ignore, DEFER=p.out_defer, RESCHEDULE=p.out_resched)
    rules = {r: min(mi[a], mc[b]) for r, a, b, _ in FIS1_RULES}
    num = sum(rules[r] * out[act] for r, _, _, act in FIS1_RULES)
    den = sum(rules.values())
    A = num / den if den > 1e-12 else 0.0
    action = "IGNORE" if A < p.thr_ignore else ("DEFER" if A < p.thr_resched else "RESCHEDULE")
    return FIS1Out(A, action, mi, mc, rules)


def fis2(Im, W_rel, gamma, p: FuzzyParams, H: float | None = None) -> FIS2Out:
    """H (variant B, V-B1): hard due-date threat in [0,1]. Rule R16 'IF hard-due-date
    threat is HIGH THEN FR' is a PRIORITY rule: its firing strength H shifts the score of
    rules R7–R15 towards FR, S = (1 − H)·S0 + 3·H, so a fully threatened hard due date
    always yields FR. (Adding R16 as an ordinary Mamdani rule was ineffective: with max
    aggregation and centroid defuzzification it never changed the selected method.)"""
    mi, mw, mg = mf_im(Im, p), mf_w(W_rel, p), mf_g(gamma, p)
    rules = {}
    for r, a, b, c, _ in FIS2_RULES:
        rules[r] = min(mi[a], mw[b], mg[c] if c else 1.0)
    extra = []
    s = np.linspace(1.0, 3.0, p.n_grid)
    agg = np.zeros_like(s)
    for r, _, _, _, meth in FIS2_RULES + extra:
        c = METHOD_CENTRE[meth]
        agg = np.maximum(agg, np.minimum(rules[r], np.clip(1 - np.abs(s - c), 0, 1)))
    S = float((s * agg).sum() / agg.sum()) if agg.sum() > 1e-12 else 2.0
    if H is not None:
        rules["R16"] = float(H)
        S = (1.0 - H) * S + 3.0 * H
    method = "RS" if S < 1.5 else ("MU" if S < 2.5 else "FR")
    return FIS2Out(S, method, mi, mw, mg, rules)
