@echo off
rem Full run: tests, E1, E2 (main + gamma), statistics and figures.
rem Output: results_new\ (the published results in results\ are not overwritten).
rem Requires Python 3.11 ("py -3.11"). Re-running resumes interrupted E2 runs.
setlocal
cd /d "%~dp0\.."
set "PROCS=8"
if not exist ".venv\Scripts\python.exe" py -3.11 -m venv .venv || goto :err
set "VPY=.venv\Scripts\python.exe"
"%VPY%" -m pip install -r requirements.txt || goto :err
"%VPY%" -m pytest -q tests || goto :err
if not exist results_new mkdir results_new
"%VPY%" -m resched_lab.experiments e1 --gammas 0.2,0.5,0.8 --out results_new\e1.csv || goto :err
"%VPY%" -m resched_lab.experiments e2 --levels low,medium,high --gammas 0.5 --reps 201-240 --policies all --procs %PROCS% --workers 2 --out results_new\e2_main.csv || goto :err
"%VPY%" -m resched_lab.experiments e2 --levels medium --gammas 0.2,0.8 --reps 201-240 --policies all --procs %PROCS% --workers 2 --out results_new\e2_gamma.csv || goto :err
"%VPY%" -m resched_lab.analysis results_new\e2_main.csv results_new\e2_gamma.csv --out results_new\analysis > results_new\analysis.txt 2>&1
"%VPY%" -m resched_lab.figures results_new\e2_main.csv results_new\e2_gamma.csv --out results_new\figures
echo Done: results_new\
pause
exit /b 0
:err
echo A step failed. Re-running this script resumes the experiments.
pause
exit /b 1
