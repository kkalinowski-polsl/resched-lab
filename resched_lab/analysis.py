"""Statistical analysis of experiment CSV files (register: M8, U9c, A1).

Primary outcome: weighted hard tardiness T^h (lexicographic objective D7);
secondary outcome: f. Reference policy in paired tests: FUZZY-AB (P-AB).

    python -m resched_lab.analysis results/e2_main.csv [results/e2_gamma.csv] --out results/analysis
"""
from __future__ import annotations

import argparse
import os
import re
import numpy as np
import pandas as pd
from scipy import stats

KEYS = ["case", "scenario", "gamma"]
REF = "FUZZY-AB"
ORDER = ["STATIC", "ALWAYS-RS", "ALWAYS-MU", "ALWAYS-FR", "CRISP",
         "FUZZY", "FUZZY-A", "FUZZY-B", "FUZZY-AB", "ORACLE"]


def _hours(df):
    df = df.copy()
    scale = 3600.0 if (df["case"] == "E2").any() else 60.0      # E2: seconds; E1: minutes
    df["Th_h"] = df["wt_hard"] / scale
    df["Ts_h"] = df["wt_soft"] / scale
    df["cmax_h"] = df["cmax"] / scale
    df["delta_h"] = df["delta"] / scale
    df["any_hard_late"] = (df["n_tardy_hard"] > 0).astype(float)
    return df


def summary(df):
    df = _hours(df)
    g = df.groupby(KEYS + ["policy"])
    out = g.agg(n=("f", "size"), Th_h=("Th_h", "mean"), Th_med=("Th_h", "median"),
                p_hard_late=("any_hard_late", "mean"), n_tardy_hard=("n_tardy_hard", "mean"),
                Ts_h=("Ts_h", "mean"), cmax_h=("cmax_h", "mean"), delta_h=("delta_h", "mean"),
                f=("f", "mean"), interventions=("n_interventions", "mean"),
                cpu_s=("cpu", "mean"), events=("n_events", "mean")).reset_index()
    out["policy"] = pd.Categorical(out["policy"], ORDER, ordered=True)
    return out.sort_values(KEYS + ["policy"])


def rank_biserial(x, y):
    """Matched-pairs rank-biserial correlation of x − y (positive: x larger)."""
    d = np.asarray(x) - np.asarray(y)
    d = d[d != 0]
    if len(d) == 0:
        return 0.0
    r = stats.rankdata(np.abs(d))
    return float((r[d > 0].sum() - r[d < 0].sum()) / r.sum())


def paired_tests(df, metric, ref=REF):
    """Friedman over all policies; Wilcoxon signed-rank ref vs each other policy,
    Holm-corrected; effect size rank-biserial; mean paired difference with 95 % CI."""
    rows = []
    for key, d in df.groupby(KEYS):
        wide = d.pivot_table(index="rep", columns="policy", values=metric).dropna()
        if ref not in wide or len(wide) < 5:
            continue
        cols = [c for c in ORDER if c in wide.columns]
        try:
            fr_p = stats.friedmanchisquare(*[wide[c] for c in cols]).pvalue
        except ValueError:
            fr_p = np.nan
        res = []
        for c in cols:
            if c == ref:
                continue
            diff = wide[ref] - wide[c]
            if (diff == 0).all():
                p = 1.0
            else:
                p = stats.wilcoxon(wide[ref], wide[c], zero_method="zsplit").pvalue
            n = len(diff)
            hw = stats.t.ppf(0.975, n - 1) * diff.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
            res.append(dict(other=c, mean_diff=diff.mean(), ci95_half=hw, median_diff=diff.median(),
                            rb=rank_biserial(wide[ref], wide[c]), wins=int((diff < 0).sum()),
                            ties=int((diff == 0).sum()), losses=int((diff > 0).sum()), p=p))
        res.sort(key=lambda r: r["p"])
        k, running = len(res), 0.0
        for i, r in enumerate(res):
            running = max(running, min(1.0, (k - i) * r["p"]))
            r["p_holm"] = running
        for r in res:
            rows.append(dict(zip(KEYS, key), metric=metric, ref=ref, friedman_p=fr_p, n=len(wide), **r))
    out = pd.DataFrame(rows)
    if len(out):
        out["other"] = pd.Categorical(out["other"], ORDER, ordered=True)
        out = out.sort_values(KEYS + ["other"])
    return out


def lex_compare(df, ref=REF):
    """Per replication lexicographic comparison (T^h, then f) of ref vs each policy."""
    rows = []
    for key, d in df.groupby(KEYS):
        th = d.pivot_table(index="rep", columns="policy", values="wt_hard")
        ff = d.pivot_table(index="rep", columns="policy", values="f")
        for c in [c for c in ORDER if c in th.columns and c != ref]:
            better = ((th[ref] < th[c] - 1e-9) | ((abs(th[ref] - th[c]) <= 1e-9) & (ff[ref] < ff[c] - 1e-12)))
            worse = ((th[ref] > th[c] + 1e-9) | ((abs(th[ref] - th[c]) <= 1e-9) & (ff[ref] > ff[c] + 1e-12)))
            rows.append(dict(zip(KEYS, key), ref=ref, other=c, better=int(better.sum()),
                             worse=int(worse.sum()), equal=int((~better & ~worse).sum())))
    return pd.DataFrame(rows)


def regret(df):
    """Lexicographic regret against ORACLE, per replication then averaged."""
    o = df[df.policy == "ORACLE"][KEYS + ["rep", "f", "wt_hard"]].rename(
        columns={"f": "f_or", "wt_hard": "wh_or"})
    m = df.merge(o, on=KEYS + ["rep"])
    scale = 3600.0 if (df["case"] == "E2").any() else 60.0
    m["regret_Th_h"] = (m["wt_hard"] - m["wh_or"]) / scale
    m["regret_f"] = m["f"] - m["f_or"]
    m["beats_oracle_lex"] = ((m["wt_hard"] < m["wh_or"] - 1e-9) |
                             ((abs(m["wt_hard"] - m["wh_or"]) <= 1e-9) & (m["f"] < m["f_or"] - 1e-12)))
    out = m.groupby(KEYS + ["policy"]).agg(regret_Th_h=("regret_Th_h", "mean"),
                                            regret_f=("regret_f", "mean"),
                                            share_beats_oracle=("beats_oracle_lex", "mean")).reset_index()
    out["policy"] = pd.Categorical(out["policy"], ORDER, ordered=True)
    return out.sort_values(KEYS + ["policy"])


_DEC = re.compile(r"[^:;]+:(\w\w):(IGN|DEF|RES)(?::(RS|MU|FR))?")


def decision_profile(df):
    """Share of actions / methods per policy (all decision epochs, incl. reviews)."""
    rows = []
    for key, d in df.groupby(KEYS + ["policy"]):
        cnt = dict(IGN=0, DEF=0, RES=0, RS=0, MU=0, FR=0, epochs=0, rush_FR=0, rush_RES=0)
        for s in d["decisions"].fillna(""):
            for ev, act, meth in _DEC.findall(s):
                cnt["epochs"] += 1
                cnt[act] += 1
                if meth:
                    cnt[meth] += 1
                if ev == "ru" and act == "RES":
                    cnt["rush_RES"] += 1
                    cnt["rush_FR"] += meth == "FR"
        n = len(d)
        rows.append(dict(zip(KEYS + ["policy"], key),
                         **{k: v / n for k, v in cnt.items()}))
    out = pd.DataFrame(rows)
    out["policy"] = pd.Categorical(out["policy"], ORDER, ordered=True)
    return out.sort_values(KEYS + ["policy"])


def run(paths, outdir):
    df = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    df = df.drop_duplicates(KEYS + ["rep", "policy"])
    os.makedirs(outdir, exist_ok=True)
    res = dict(summary=summary(df), tests_Th=paired_tests(df, "wt_hard"), tests_f=paired_tests(df, "f"),
               lex_vs_ref=lex_compare(df), regret=regret(df), decisions=decision_profile(df))
    for k, v in res.items():
        v.to_csv(os.path.join(outdir, f"{k}.csv"), index=False)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--out", default="results/analysis")
    a = ap.parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    for k, v in run(a.csv, a.out).items():
        print(f"\n=== {k} ===")
        print(v.round(4).to_string(index=False))
