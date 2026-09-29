# Baseline schedules σ0 (CC BY 4.0)

- `sigma0_js5x10.json` – illustrative job shop (E1), makespan 455 min (optimal).
- `sigma0_gear_2026.json` – gear-wheel line (E2), order-attribute seed 2026, makespan 78 333 s.

Each entry: `[job, operation index, machine, start, end]`. The files were produced by `resched_lab.experiments` on the computing machine of the study and are read instead of recomputing σ0. A σ0 rebuilt on another platform can differ (Linux: 77 610 s), which changes all E2 results. Exact reproduction of E2 also requires the platform of the study, because CP-SAT repairs within a deterministic time limit can differ between platforms (see the main README).
