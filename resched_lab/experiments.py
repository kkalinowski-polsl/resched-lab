"""Experiment runner (register: M8, U9, N4). Every result row is produced from
(instance, σ0, scenario seed, policy, configuration) only, and written to CSV.

Usage (command line):
    python -m resched_lab.experiments e1  --out results/e1.csv
    python -m resched_lab.experiments e2  --levels low --gammas 0.5 --reps 1-10 \
                                          --policies all --procs 12 --out results/e2.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from .instance import load_js5x10, load_gear_line, generate_order_attributes
from .schedule import Norm, Slot, metrics, validate
from .optimize import solve, list_schedule
from .simulate import SimConfig, Static, Always, Crisp, Fuzzy, Oracle, simulate
from .cases import e1_scenarios, e2_events

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(HERE, "cache")

# fixed experimental constants (documented in the register)
E1 = dict(L_FR=20.0, tau=30.0, time_limit=10.0)                    # minutes; I4, U6, U9
E2 = dict(L_FR=3600.0, tau=8 * 3600.0, time_limit=1.0,             # seconds; I4, U6, U9 (pilot)
          instance_seed=2026, release_span=8 * 3600, sigma0_limit=4.0)
CRISP_THETA_MIN = (15.0, 45.0)      # I6: thresholds of the conference version [min] on Cmax0 = 455
CRISP_REL = (CRISP_THETA_MIN[0] / 455.0, CRISP_THETA_MIN[1] / 455.0)


def policies(names="all"):
    allp = {"STATIC": Static(), "ALWAYS-RS": Always("RS"), "ALWAYS-MU": Always("MU"),
            "ALWAYS-FR": Always("FR"), "CRISP": Crisp(*CRISP_REL), "FUZZY": Fuzzy(), "ORACLE": Oracle(),
            "FUZZY-A": Fuzzy(variant="A"), "FUZZY-B": Fuzzy(variant="B"),
            "FUZZY-AB": Fuzzy(variant="AB")}
    if names == "all":
        return [allp[k] for k in ("STATIC", "ALWAYS-RS", "ALWAYS-MU", "ALWAYS-FR", "CRISP",
                                  "FUZZY", "FUZZY-A", "FUZZY-B", "FUZZY-AB", "ORACLE")]
    return [allp[n] for n in names.split(",")]


# ---------------------------------------------------------------------------
def _dump(sched, path):
    with open(path, "w") as f:
        json.dump([[o[0], o[1], s.machine, s.start, s.end] for o, s in sched.items()], f)


def _load(path):
    with open(path) as f:
        return {(a, b): Slot(m, s, e) for a, b, m, s, e in json.load(f)}


def e1_setup():
    inst = load_js5x10()
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "sigma0_js5x10.json")
    if os.path.exists(path):
        s0 = _load(path)
    else:
        s0 = solve(inst, 0, {}, [], 0.0, Norm.from_instance(inst, inst.lower_bound_cmax()),
                   time_limit=E1["time_limit"]).sched
        _dump(s0, path)
    assert validate(inst, s0) == []
    return inst, s0, Norm.from_instance(inst, metrics(inst, s0)["cmax"])


def e2_setup():
    """Production instance (automated gear line) and its baseline σ0 (U1, I14)."""
    inst = load_gear_line(os.path.join(DATA, "zautomatyzowany2.csv"))
    generate_order_attributes(inst, seed=E2["instance_seed"], release_span=E2["release_span"])
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"sigma0_gear_{E2['instance_seed']}.json")
    if os.path.exists(path):
        s0 = _load(path)
    else:
        lb_norm = Norm.from_instance(inst, inst.lower_bound_cmax())
        hints = [list_schedule(inst, sorted(inst.jobs, key=key)) for key in (
            lambda j: (inst.jobs[j].due, j), lambda j: (inst.jobs[j].release, j))]
        best = min(hints, key=lambda h: (metrics(inst, h)["wt_hard"], metrics(inst, h)["cmax"]))
        s0 = solve(inst, 0, {}, [], 0.0, lb_norm, time_limit=E2["sigma0_limit"], hint=best).sched
        _dump(s0, path)
    assert validate(inst, s0) == []
    return inst, s0, Norm.from_instance(inst, metrics(inst, s0)["cmax"])


# ---------------------------------------------------------------------------
def _row(case, scen, rep, gamma, res, wall, n_events):
    m = res.metrics
    return dict(case=case, scenario=scen, rep=rep, gamma=gamma, policy=res.policy,
                wt_hard=m["wt_hard"], n_tardy_hard=m["n_tardy_hard"], wt_soft=m["wt_soft"],
                cmax=m["cmax"], delta=m["delta"], n_machine_changes=m["n_machine_changes"],
                f=res.f, n_interventions=res.n_interventions, cpu=round(res.cpu, 3),
                wall=round(wall, 2), n_events=n_events,
                decisions=";".join(f"{e['t']}:{e['event'][:2]}:{e['action'][:3]}"
                                   f"{':' + e['method'] if e.get('method') else ''}" for e in res.log))


def run_e1(gammas=(0.2, 0.5, 0.8), pol="all"):
    inst, s0, norm = e1_setup()
    rows = []
    for g in gammas:
        cfg = SimConfig(gamma=g, L_FR=E1["L_FR"], tau=E1["tau"], time_limit=E1["time_limit"])
        for name, evs in e1_scenarios().items():
            for p in policies(pol):
                t0 = time.perf_counter()
                r = simulate(inst, s0, evs, p, cfg, norm)
                rows.append(_row("E1", name, 0, g, r, time.perf_counter() - t0, len(evs)))
    return rows


def _e2_task(args):
    level, gamma, rep, pol, workers = args
    inst, s0, norm = e2_setup()
    horizon = int(1.2 * norm.cmax0)
    evs = e2_events(inst, horizon, level, seed=rep)
    cfg = SimConfig(gamma=gamma, L_FR=E2["L_FR"], tau=E2["tau"], time_limit=E2["time_limit"],
                    workers=workers)
    p = policies(pol)[0]
    t0 = time.perf_counter()
    r = simulate(inst, s0, evs, p, cfg, norm)
    return _row("E2", level, rep, gamma, r, time.perf_counter() - t0, len(evs))


def _done_keys(out):
    """Tasks already present in an existing CSV (resume after interruption)."""
    if not out or not os.path.exists(out):
        return set()
    with open(out, newline="") as f:
        return {(r["scenario"], float(r["gamma"]), int(r["rep"]), r["policy"]) for r in csv.DictReader(f)}


def run_e2(levels, gammas, reps, pols, procs=1, workers=2, out=None):
    names = [p.name for p in policies(pols)]
    done = _done_keys(out)
    tasks = [(lv, g, rep, n, workers) for lv in levels for g in gammas for rep in reps for n in names
             if (lv, g, rep, n) not in done]
    print(f"E2: {len(tasks)} runs to do ({len(done)} already in {out})", flush=True)
    e2_setup()                              # build σ0 cache once before forking
    rows = []
    with ProcessPoolExecutor(max_workers=procs) as ex:
        futs = [ex.submit(_e2_task, t) for t in tasks]
        for fu in as_completed(futs):
            row = fu.result()
            rows.append(row)
            if out:
                write_rows([row], out, append=True)
            print(f"  done {len(rows)}/{len(tasks)}: {row['scenario']} rep {row['rep']} "
                  f"gamma {row['gamma']} {row['policy']}  ({row['wall']} s)", flush=True)
    return rows


def write_rows(rows, path, append=False):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    new = not (append and os.path.exists(path))
    with open(path, "a" if append else "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if new:
            w.writeheader()
        w.writerows(rows)


def _parse_reps(s):
    if "-" in s:
        a, b = s.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",")]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("exp", choices=["e1", "e2"])
    ap.add_argument("--levels", default="low")
    ap.add_argument("--gammas", default="0.5")
    ap.add_argument("--reps", default="1")
    ap.add_argument("--policies", default="all")
    ap.add_argument("--procs", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    gam = [float(x) for x in a.gammas.split(",")]
    if a.exp == "e1":
        write_rows(run_e1(gam, a.policies), a.out)
    else:
        # resumable: runs already present in --out are skipped (delete the file to start over)
        run_e2(a.levels.split(","), gam, _parse_reps(a.reps), a.policies, a.procs, a.workers, a.out)
