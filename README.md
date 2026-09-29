# resched_lab

Closed-loop computational workbench, input data and raw results for the article

> K. Kalinowski, *A two-stage fuzzy decision layer for rescheduling in digital-twin-enabled production systems* (manuscript submitted to the *International Journal of Production Research*, 2026).

The workbench evaluates rescheduling policies in closed loop with a digital-twin emulator of the shop floor. At every disruption the emulator projects the current plan with and without the disruption, the decision layer decides whether to act (FIS-1: IGNORE / DEFER / RESCHEDULE) and how to reschedule (FIS-2 with priority rule R16: right shift RS / match-up MU / full rescheduling FR), and the repair is computed by a constraint-programming model (OR-Tools CP-SAT) in deterministic mode.

## Contents

| Path | Content |
|---|---|
| `resched_lab/` | Python package (see *Modules*) |
| `tests/test_core.py` | 14 verification tests (instance data, schedule validator, baseline, projection, hand-derived feature values of scenario S1, fuzzy systems, repair feasibility, match-up constraints, variants A and B) |
| `data/zautomatyzowany2.csv` | processing times of the automated gear-wheel line (Kampa et al. 2026) – see `data/README.md` |
| `cache/` | baseline schedules σ0 used in the study (JSON) – see *Reproducibility* |
| `results/` | raw results of the study: `e1_pc.csv` (illustrative example, E1), `e2_main.csv` and `e2_gamma.csv` (production case, E2), `environment.txt` (machine, Python and package versions of the computing machine) |
| `scripts/` | `run_all.sh` / `run_all.bat` – tests, E1, E2 and analysis in one run |

### Modules

| Module | Content |
|---|---|
| `instance.py` | instance model; illustrative 5 × 10 job shop; gear-line loader; generator of order attributes |
| `schedule.py` | schedule representation, feasibility validator, metrics, objective *f*, lexicographic key |
| `execution.py` | digital-twin emulator: published plan, shop state, projection, disruption events |
| `features.py` | decision features *I_m*, *C_r*, *D_r*, *H*, *W*, *W_rel* |
| `fuzzy.py` | FIS-1 (zero-order Sugeno), FIS-2 (Mamdani) and priority rule R16; membership functions |
| `optimize.py` | CP-SAT model (baseline, FR, MU), list decoder, serial schedule generation scheme |
| `repair.py` | repair methods RS, MU, FR (heuristic portfolio + CP-SAT) |
| `simulate.py` | policies STATIC, ALWAYS-RS/MU/FR, CRISP, FUZZY, FUZZY-A, FUZZY-B, FUZZY-AB, ORACLE; closed-loop simulation |
| `cases.py` | scenarios S1–S3 of E1; generator of disruption streams of E2 |
| `experiments.py` | experiment runner (E1, E2) writing CSV files |
| `analysis.py` | descriptive statistics, Friedman and Wilcoxon–Holm tests, rank-biserial *r*, lexicographic comparison, signed gap relative to ORACLE, decision profile |
| `figures.py` | Figures 2–4 of the article |

Identifiers such as M5, U4 or I13 in the docstrings refer to the design log of the study.

## Installation

Python 3.11 (the version used in the study) and the pinned packages of `requirements.txt`:

```
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q tests          # 14 tests must pass
```

## Reproducing the results

```
# E1 – illustrative example (a few minutes)
python -m resched_lab.experiments e1 --gammas 0.2,0.5,0.8 --out results_new/e1.csv

# E2 – production case: 3 levels x 40 replications x 10 policies, gamma = 0.5 (hours)
python -m resched_lab.experiments e2 --levels low,medium,high --gammas 0.5 --reps 201-240 \
       --policies all --procs 8 --workers 2 --out results_new/e2_main.csv
# E2 – stability weight gamma = 0.2 and 0.8 at the medium level
python -m resched_lab.experiments e2 --levels medium --gammas 0.2,0.8 --reps 201-240 \
       --policies all --procs 8 --workers 2 --out results_new/e2_gamma.csv

# statistics (Tables 6-8 of the article, Tables S3-S7 of the Supplementary material)
python -m resched_lab.analysis results/e2_main.csv results/e2_gamma.csv --out results/analysis
# Figures 2-4
python -m resched_lab.figures results/e2_main.csv results/e2_gamma.csv --out results/figures
```

`results/analysis/regret.csv` contains the signed gap relative to ORACLE (named *regret* in the code).

`scripts/run_all.sh` (Linux/macOS) and `scripts/run_all.bat` (Windows) run all steps. Runs are resumable: rows already present in the output CSV are skipped. `--procs × --workers` should not exceed the number of physical cores.

Seeds: `--reps` are replication numbers and disruption-stream seeds. Pilot study: 1–6; diagnostic run: 101–103; main experiment: 201–240. Order attributes of the production case use seed 2026.

### Reproducibility

- CP-SAT runs in deterministic mode (interleaved search, deterministic time limit, 2 workers, seed 0). On one platform (hardware, operating system, OR-Tools build) repeated runs are bit-identical.
- The published results were computed on one machine: Intel i9-12900K, Windows 11 (build 26200, reported by Python as `Windows-10-10.0.26200`), Python 3.11.9, OR-Tools 9.15.6755, `--workers 2` (`results/environment.txt`).
- Cross-platform check (Linux, Python 3.11, the same package versions): E1 (`results/e1_pc.csv`) was reproduced identically, apart from computation times. In E2, a baseline σ0 rebuilt on Linux differed (makespan 77 610 s instead of 78 333 s); with the archived σ0 the runs without repairs (STATIC) coincided, but CP-SAT repairs within the deterministic time limit returned different schedules, so E2 values differ between platforms. **E2 is reproduced exactly only with the archived σ0 in `cache/` on the platform of the study.** Do not delete `cache/`; delete it only after changing the data or the instance seed.
- Wall-clock and CPU times (`cpu`, `wall`) are machine dependent.

## Result files

One row per run (policy × scenario/level × replication × γ):

| Column | Meaning |
|---|---|
| `case`, `scenario`, `rep`, `gamma`, `policy` | experiment, scenario (E1: S1–S3) or intensity level (E2: low / medium / high), replication seed, stability weight, policy |
| `wt_hard`, `n_tardy_hard` | weighted tardiness of hard-due-date jobs *T^h*, number of tardy hard-due-date jobs |
| `wt_soft` | weighted tardiness of soft-due-date jobs *T^s* |
| `cmax`, `delta`, `n_machine_changes` | makespan, instability Δ with respect to σ0, number of machine reassignments |
| `f` | objective (1) of the article |
| `n_interventions`, `cpu`, `wall`, `n_events` | published revisions, total repair time [s], wall-clock time of the run [s], disruption events |
| `decisions` | decision trace `t:event:action[:method]` (event: br – breakdown, ru – rush order, du – due-date change, re – review of deferred events) |

Time unit: minutes in E1, seconds in E2 (`wt_hard` and `wt_soft` are weighted time units).

## Licences

- Code (`resched_lab/`, `tests/`, `scripts/`): MIT – see `LICENSE`.
- Data and results (`data/`, `cache/`, `results/`): Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/. The line data are taken from Kampa et al. (2026), published under CC BY 4.0.

## How to cite

Cite the archived version (DOI in `CITATION.cff` and on the Zenodo record) and the article. Source of the line data:

Kampa, A., K. Kalinowski, M. Stawowiak, M. Jarzyńska, M. Olender-Skóra, G. Gołda, W. Banaś, et al. 2026. “Digital Twin Methodology for Flexible Manufacturing System Design: Integration of VSM, Discrete-Event Simulation and Production Scheduling for Gear Wheel Production.” *Applied Sciences* 16 (15): 7521. https://doi.org/10.3390/app16157521.

## Author

Krzysztof Kalinowski (ORCID 0000-0001-7601-2575), Department of Engineering Processes Automation and Integrated Manufacturing Systems, Faculty of Mechanical Engineering, Silesian University of Technology, Gliwice, Poland – krzysztof.kalinowski@polsl.pl
