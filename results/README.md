# Results of the study (CC BY 4.0)

| File | Experiment | Command |
|---|---|---|
| `e1_pc.csv` | E1 – illustrative example, scenarios S1–S3, 10 policies, γ = 0.2 / 0.5 / 0.8 | `experiments e1 --gammas 0.2,0.5,0.8` |
| `e2_main.csv` | E2 – production case, levels low / medium / high, γ = 0.5, seeds 201–240, 10 policies (1200 runs) | `experiments e2 --levels low,medium,high --gammas 0.5 --reps 201-240 --policies all --workers 2` |
| `e2_gamma.csv` | E2 – medium level, γ = 0.2 and 0.8, seeds 201–240, 10 policies (800 runs) | `experiments e2 --levels medium --gammas 0.2,0.8 --reps 201-240 --policies all --workers 2` |
| `environment.txt` | machine, Python and package versions of the computing machine | – |

Computed on one machine (Intel i9-12900K, Windows 11 build 26200, Python 3.11.9, OR-Tools 9.15.6755, `--workers 2`) with the baseline schedules in `../cache/`. Column definitions: `../README.md`.
