"""Verification suite (register: M-verification gates).
Golden values for E1/S1 were derived by hand (see verification note)."""
import copy
import pytest

from resched_lab.instance import load_js5x10, Instance, Job, Op
from resched_lab.schedule import Slot, Norm, validate, metrics, objective
from resched_lab.optimize import solve
from resched_lab.execution import Plan, State, commit_until, project, apply_event, Breakdown
from resched_lab.features import compute_features
from resched_lab.fuzzy import FuzzyParams, fis1, fis2
from resched_lab.repair import repair
from resched_lab.cases import e1_scenarios


@pytest.fixture(scope="module")
def base():
    inst = load_js5x10()
    s0 = solve(inst, 0, {}, [], 0.0, Norm.from_instance(inst, inst.lower_bound_cmax()), time_limit=10).sched
    C0 = metrics(inst, s0)["cmax"]
    return inst, s0, Norm.from_instance(inst, C0)


# ---- gate 1: instance & validator --------------------------------------------
def test_instance_data():
    inst = load_js5x10()
    assert inst.n_ops() == 40 and inst.total_p() == 1440
    assert inst.jobs["J02"].weight == 3.0 and inst.jobs["J03"].weight == 1.0   # I5
    assert inst.lower_bound_cmax() == 350                                      # M3 load


def test_validator_detects_violations():
    inst = Instance("t", ["A", "B"])
    inst.jobs["J"] = Job("J", [Op("J", 0, ("A",), 10), Op("J", 1, ("B",), 5)])
    inst.jobs["K"] = Job("K", [Op("K", 0, ("A",), 10)])
    ok = {("J", 0): Slot("A", 0, 10), ("J", 1): Slot("B", 10, 15), ("K", 0): Slot("A", 10, 20)}
    assert validate(inst, ok) == []
    bad = dict(ok); bad[("K", 0)] = Slot("A", 5, 15)           # machine overlap
    assert any("overlaps" in e for e in validate(inst, bad))
    bad = dict(ok); bad[("J", 1)] = Slot("B", 8, 13)           # precedence
    assert any("before" in e for e in validate(inst, bad))
    bad = dict(ok); bad[("J", 1)] = Slot("A", 20, 25)          # eligibility
    assert any("ineligible" in e for e in validate(inst, bad))
    # resume across downtime: net time must equal p
    dt = [("A", 5, 8)]
    res = {("J", 0): Slot("A", 0, 13), ("J", 1): Slot("B", 13, 18), ("K", 0): Slot("A", 13, 23)}
    assert validate(inst, res, dt) == []


# ---- gate 2: baseline ---------------------------------------------------------
def test_sigma0(base):
    inst, s0, norm = base
    assert validate(inst, s0) == []
    m = metrics(inst, s0)
    assert m["cmax"] == 455 and m["wt_hard"] == 0 and m["wt_soft"] == 0


def test_cpsat_deterministic(base):
    inst, s0, _ = base
    s0b = solve(inst, 0, {}, [], 0.0, Norm.from_instance(inst, inst.lower_bound_cmax()), time_limit=10).sched
    assert s0b == s0


# ---- gate 3: execution / projection --------------------------------------------
def test_projection_without_events_reproduces_plan(base):
    inst, s0, _ = base
    assert project(inst, Plan.from_schedule(inst, s0), State()) == s0


def test_resume_interrupted_operation():
    inst = Instance("t", ["A"])
    inst.jobs["J"] = Job("J", [Op("J", 0, ("A",), 10)])
    inst.jobs["K"] = Job("K", [Op("K", 0, ("A",), 5)])
    plan = Plan.from_schedule(inst, {("J", 0): Slot("A", 0, 10), ("K", 0): Slot("A", 10, 15)})
    st, _ = commit_until(inst, plan, State(), 4)
    plan, st = apply_event(inst, plan, st, Breakdown(4, "A", 6))
    P = project(inst, plan, st)
    assert P[("J", 0)] == Slot("A", 0, 16) and P[("K", 0)] == Slot("A", 16, 21)
    assert validate(inst, P, st.downtimes) == []


# ---- gate 4: features – hand-derived golden values for E1/S1 -------------------
def s1_features(base):
    inst, s0, norm = base
    ev = e1_scenarios()["S1"][0]
    i = copy.deepcopy(inst); plan = Plan.from_schedule(i, s0)
    st, _ = commit_until(i, plan, State(), ev.t)
    ir, Pr = copy.deepcopy(i), project(i, plan, st)
    plan2, st2 = apply_event(i, plan, st, ev)
    Pd = project(i, plan2, st2)
    return compute_features(ir, Pr, i, Pd, ev.t, norm.cmax0, 20.0, inst.mean_weight()), Pd


def test_s1_golden(base):
    f, Pd = s1_features(base)
    # hand derivation: M4 down [160,180) → J06.2 180–215, J10.2 215–250, J06.3 250–270,
    # J08.2 270–305, J08.3 305–325, J10.3 325–345; M3: J08.4 325–355, J10.4 355–385,
    # J09.4 385–425, J07.4 425–465  ⇒ Cmax 465, no new tardiness
    assert Pd[("J07", 3)].end == 465 and Pd[("J08", 3)].start == 325
    assert f.d_cmax == 10 and f.d_wt == 0
    assert f.Im == pytest.approx(10 / 455)
    assert (f.n_affected_jobs, f.n_unfinished) == (4, 9)          # J07, J08, J09, J10 of 9
    assert f.W == 0                                               # J06.2 was to start at t
    o = fis1(f.Im, f.Cr, FuzzyParams())
    # exact: μLOW=(0.05−10/455)/0.03, μMED=(10/455−0.02)/0.04, Cr=4/9 → μLOW_CR=(0.5−4/9)/0.3,
    # μHIGH_CR=(4/9−0.3)/0.4; A = (0.5·R2 + 0.5·R3 + 1·R4)/(R1+R2+R3+R4)
    lo, me = (0.05 - 10 / 455) / 0.03, (10 / 455 - 0.02) / 0.04
    cl, ch = (0.5 - 4 / 9) / 0.3, (4 / 9 - 0.3) / 0.4
    R = [min(lo, cl), min(lo, ch), min(me, cl), min(me, ch)]
    A = (0.5 * R[1] + 0.5 * R[2] + R[3]) / sum(R)
    assert o.A == pytest.approx(A) and abs(A - 0.3948) < 1e-4 and o.action == "DEFER"


def test_fis_boundaries():
    p = FuzzyParams()
    assert fis1(0.0, 0.0, p).action == "IGNORE"
    assert fis1(0.5, 0.0, p).action == "RESCHEDULE"
    assert fis2(0.01, 5.0, 0.5, p).method == "RS"
    assert fis2(0.5, 5.0, 0.2, p).method == "FR"
    assert fis2(0.5, 0.0, 0.8, p).method == "MU"


# ---- gate 5: repair cross-checks ------------------------------------------------
def test_fr_without_disruption_not_worse(base):
    inst, s0, norm = base
    plan = Plan.from_schedule(inst, s0)
    st, _ = commit_until(inst, plan, State(), 100)
    new, _ = repair("FR", inst, plan, st, 0.5, norm, 10, 10)
    P = project(inst, new, st)
    assert validate(inst, P) == []
    assert objective(metrics(inst, P, s0), norm, 0.5) <= objective(metrics(inst, s0, s0), norm, 0.5) + 1e-9


def test_repairs_feasible_on_all_e1(base):
    inst, s0, norm = base
    for name, evs in e1_scenarios().items():
        ev = evs[0]
        i = copy.deepcopy(inst); plan = Plan.from_schedule(i, s0)
        st, _ = commit_until(i, plan, State(), ev.t)
        plan, st = apply_event(i, plan, st, ev)
        for m in ("RS", "MU", "FR"):
            new, _ = repair(m, i, plan, st, 0.5, norm, max(1, ev.D), 10)
            P = project(i, new, st)
            assert validate(i, P, st.downtimes) == [], (name, m)
            # committed operations untouched
            assert all(P[o] == sl for o, sl in st.committed.items() if sl.end <= ev.t)


def test_mu_tail_constraints(base):
    """N5a: after T_mu operations keep machine, machine order and start >= planned start."""
    from resched_lab.repair import plan_as_ref
    inst, s0, norm = base
    for name, evs in e1_scenarios().items():
        ev = evs[0]
        i = copy.deepcopy(inst); plan = Plan.from_schedule(i, s0)
        st, _ = commit_until(i, plan, State(), ev.t)
        plan, st = apply_event(i, plan, st, ev)
        ref = plan_as_ref(i, plan)
        new, info = repair("MU", i, plan, st, 0.5, norm, max(1, ev.D), 10)
        P = project(i, new, st)
        assert validate(i, P, st.downtimes) == []
        tail = [o for o, sl in ref.items() if sl.start >= info["T_mu"] and o not in st.committed
                and not i.jobs[o[0]].rush]
        for o in tail:
            assert P[o].machine == ref[o].machine and P[o].start >= ref[o].start, (name, o)
        by_m = {}
        for o in sorted(tail, key=lambda o: ref[o].start):
            by_m.setdefault(ref[o].machine, []).append(P[o].start)
        assert all(a <= b for lst in by_m.values() for a, b in zip(lst, lst[1:]))


def test_heuristics_feasible_with_downtime():
    from resched_lab.optimize import list_schedule, sgs_schedule
    inst = load_js5x10()
    dts = [("M3", 100, 160), ("M1", 20, 50)]
    ls = list_schedule(inst, sorted(inst.jobs), 0, {}, dts)
    assert validate(inst, ls, []) == [] and all(
        not (sl.start < d1 and sl.end > d0) for sl in ls.values() for (m, d0, d1) in dts if m == sl.machine)
    sg = sgs_schedule(inst, 0, {}, dts, lambda o: o)
    assert validate(inst, sg, []) == []


def test_variant_features_e1_s3a(base):
    """Variant A: the bottleneck failure of S3a delays all open jobs (Cr = 1) but
    threatens no due date (Dr < 1, H = 0) – FIS-1 with Dr defers."""
    inst, s0, norm = base
    ev = e1_scenarios()["S3"][0]
    i = copy.deepcopy(inst); plan = Plan.from_schedule(i, s0)
    st, _ = commit_until(i, plan, State(), ev.t)
    ir, Pr = copy.deepcopy(i), project(i, plan, st)
    plan2, st2 = apply_event(i, plan, st, ev)
    f = compute_features(ir, Pr, i, project(i, plan2, st2), ev.t, norm.cmax0, 20.0, inst.mean_weight())
    assert f.Cr == 1.0 and f.H == 0.0 and f.Dr < f.Cr
    assert fis1(f.Im, f.Cr, FuzzyParams()).action == "RESCHEDULE"
    assert fis1(f.Im, f.Dr, FuzzyParams()).action == "DEFER"


def test_variant_b_priority_rule():
    """V-B1: full hard-due-date threat always selects FR; no threat = base FIS-2."""
    p = FuzzyParams()
    for Im in (0.05, 0.1, 0.3, 1.0):
        for W in (0.3, 1.5, 3.0):
            for g in (0.2, 0.5, 0.8):
                assert fis2(Im, W, g, p, H=1.0).method == "FR"
                assert fis2(Im, W, g, p, H=0.0).S == pytest.approx(fis2(Im, W, g, p).S)
