"""Figures 2-4 of the article (Section 4.2), drawn from the result files of E2.

    python -m resched_lab.figures results/e2_main.csv results/e2_gamma.csv --out results/figures

Figure 2  T^h vs number of interventions, per intensity level (log y, 95 % CI)
Figure 3  signed gap in T^h relative to the myopic ORACLE (mean, 95 % CI), per level
Figure 4  T^h vs stability weight gamma (medium level)
"""
from __future__ import annotations

import argparse
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

INK, INK2, GRID, GREY = "#1f1f1e", "#5f5e5a", "#e4e3de", "#9a9993"
STYLE = {  # policy: (colour, marker)
    "FUZZY-AB": ("#2a78d6", "o"), "CRISP": ("#eb6834", "s"), "ALWAYS-FR": ("#1baf7a", "^"),
    "ORACLE": ("#eda100", "D"), "FUZZY-B": ("#e87ba4", "v"), "FUZZY": ("#008300", "P"),
    "FUZZY-A": (GREY, "X"), "ALWAYS-MU": (GREY, "<"), "STATIC": (GREY, "h"),
}
LAB5 = {"FUZZY-AB": (-7, -11, "right"), "FUZZY-B": (6, -9, "left"), "CRISP": (6, 4, "left"),
        "ORACLE": (-7, 5, "right"), "ALWAYS-FR": (-7, -11, "right"), "FUZZY": (6, 0, "left"),
        "FUZZY-A": (-7, 3, "right"), "ALWAYS-MU": (-7, 3, "right"), "STATIC": (6, 3, "left")}
LAB7 = {"FUZZY-B": 6, "FUZZY-AB": -6}
LEVELS = [("low", "low (A = 97 %)"), ("medium", "medium (A = 93 %)"), ("high", "high (A = 88 %)")]

plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.dpi": 150, "savefig.dpi": 300})


def ci(x):
    x = np.asarray(x, float)
    return stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))


def _save(fig, out, name):
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(out, f"{name}.{ext}"), bbox_inches="tight")
    plt.close(fig)


def fig2(df, out):
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.4), sharey=True)
    pols = ["STATIC", "ALWAYS-MU", "ALWAYS-FR", "ORACLE", "CRISP", "FUZZY", "FUZZY-A", "FUZZY-B", "FUZZY-AB"]
    for ax, (lv, title) in zip(axes, LEVELS):
        d = df[(df.scenario == lv) & (df.gamma == 0.5)]
        for p in pols:
            x = d[d.policy == p]
            th = x.wt_hard / 3600
            m, e = th.mean(), ci(th)
            c, mk = STYLE[p]
            ax.errorbar(x.n_interventions.mean(), m, yerr=[[min(e, m * 0.95)], [e]], fmt=mk, ms=6,
                        color=c, mec="white", mew=1, ecolor=c, elinewidth=1, capsize=0, zorder=3)
            dx, dy, ha = LAB5[p]
            ax.annotate(p, (x.n_interventions.mean(), m), xytext=(dx, dy), textcoords="offset points",
                        fontsize=7, color=INK2, ha=ha)
        ax.set_yscale("log")
        ax.set_title(title, fontsize=9, color=INK)
        ax.set_xlabel("interventions per run")
        ax.grid(True, color=GRID, lw=0.6, zorder=0)
    axes[0].set_ylabel("weighted hard tardiness $T^h$ [h] (log)")
    _save(fig, out, "fig2_Th_vs_interventions")


def fig3(df, out):
    pols = ["ALWAYS-FR", "CRISP", "FUZZY", "FUZZY-A", "FUZZY-B", "FUZZY-AB"]
    d = df[df.gamma == 0.5]
    o = d[d.policy == "ORACLE"][["scenario", "rep", "wt_hard"]].rename(columns={"wt_hard": "o"})
    m = d.merge(o, on=["scenario", "rep"])
    m["reg"] = (m.wt_hard - m.o) / 3600
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    w = 0.13
    xs = np.arange(len(LEVELS))
    for i, p in enumerate(pols):
        vals = [m[(m.scenario == lv) & (m.policy == p)].reg for lv, _ in LEVELS]
        c, _ = STYLE[p]
        ax.bar(xs + (i - 2.5) * w, [v.mean() for v in vals], w * 0.9, yerr=[ci(v) for v in vals],
               color=c, ecolor=INK2, error_kw=dict(lw=0.8), label=p, zorder=3)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xticks(xs, [t for _, t in LEVELS])
    ax.set_ylabel("gap in $T^h$ vs ORACLE [h]")
    ax.grid(True, axis="y", color=GRID, lw=0.6, zorder=0)
    ax.legend(ncol=3, fontsize=7, frameon=False, loc="upper left")
    _save(fig, out, "fig3_gap_vs_oracle")


def fig4(df, out):
    pols = ["ALWAYS-FR", "CRISP", "FUZZY", "FUZZY-A", "FUZZY-B", "FUZZY-AB"]
    d = df[df.scenario == "medium"]
    fig, ax = plt.subplots(figsize=(5, 3.2))
    for p in pols:
        g = d[d.policy == p].groupby("gamma").wt_hard.mean() / 3600
        c, mk = STYLE[p]
        ls = "--" if p == "ALWAYS-FR" else "-"
        ax.plot(g.index, g.values, ls, marker=mk, color=c, lw=2, ms=6, mec="white", mew=1, zorder=3)
        ax.annotate(p, (g.index[-1], g.values[-1]), xytext=(6, LAB7.get(p, 0)), textcoords="offset points",
                    fontsize=7, color=INK2, va="center")
    ax.set_xticks([0.2, 0.5, 0.8])
    ax.set_xlim(0.15, 0.98)
    ax.set_xlabel("stability weight $\\gamma$")
    ax.set_ylabel("$T^h$ [h] (medium level)")
    ax.grid(True, color=GRID, lw=0.6, zorder=0)
    _save(fig, out, "fig4_Th_vs_gamma")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--out", default="figures")
    a = ap.parse_args()
    df = pd.concat([pd.read_csv(p) for p in a.csv], ignore_index=True)
    os.makedirs(a.out, exist_ok=True)
    fig2(df, a.out)
    fig3(df, a.out)
    fig4(df, a.out)
    print("figures written to", a.out)
