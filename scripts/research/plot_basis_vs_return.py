#!/usr/bin/env python3
"""Plot the monthly mean basis % against the monthly TAIEX return %.

Reads ``data/research/basis_monthly_table.csv`` (from analyze_basis.py) and
writes ``data/research/basis_vs_return.png`` with three panels:

  A. scatter — this month's mean basis % (x) vs this month's TAIEX return % (y),
     with the OLS fit and the Pearson correlation / R^2 in the title
     (the *contemporaneous* relationship);
  B. scatter — this month's mean basis % (x) vs *next* month's TAIEX return % (y)
     (the *predictive* relationship);
  C. time series — mean basis % and TAIEX return % on twin axes, so the
     co-movement is visible month by month.

Also prints the two correlations to stdout.

Usage:  uv run python scripts/research/plot_basis_vs_return.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "data" / "research"
IN_CSV = OUT_DIR / "basis_monthly_table.csv"
OUT_PNG = OUT_DIR / "basis_vs_return.png"


def _scatter_with_fit(ax, x: pd.Series, y: pd.Series,
                      xlabel: str, ylabel: str, title: str) -> float:
    m = pd.concat([x, y], axis=1).dropna()
    xs, ys = m.iloc[:, 0].to_numpy(), m.iloc[:, 1].to_numpy()
    r = float(np.corrcoef(xs, ys)[0, 1]) if len(xs) > 2 else float("nan")
    ax.axhline(0, color="0.7", lw=0.8)
    ax.axvline(0, color="0.7", lw=0.8)
    ax.scatter(xs, ys, s=22, alpha=0.75, edgecolor="white", linewidth=0.4)
    if len(xs) > 2:
        b, a = np.polyfit(xs, ys, 1)
        xg = np.linspace(xs.min(), xs.max(), 50)
        ax.plot(xg, b * xg + a, color="crimson", lw=1.5, label=f"OLS slope {b:.1f}")
        ax.legend(loc="upper left", fontsize=8, frameon=False)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.set_title(f"{title}\nr = {r:+.3f}   R² = {r**2:.3f}   (n={len(xs)})", fontsize=10)
    ax.grid(alpha=0.25)
    return r


def main() -> int:
    if not IN_CSV.exists():
        print(f"ERROR: {IN_CSV} not found — run analyze_basis.py first", file=sys.stderr)
        return 1
    t = pd.read_csv(IN_CSV)
    needed = {"mean_basis_pct", "taiex_ret_pct", "taiex_ret_next_pct"}
    missing = needed - set(t.columns)
    if missing:
        print(f"ERROR: {IN_CSV} is missing columns {missing} — re-run analyze_basis.py",
              file=sys.stderr)
        return 1
    t["date"] = pd.to_datetime(dict(year=t["year"], month=t["month"], day=1))
    t = t.sort_values("date").reset_index(drop=True)

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.6))
    r_same = _scatter_with_fit(
        axes[0], t["mean_basis_pct"], t["taiex_ret_pct"],
        "monthly mean basis %  (TX − TAIEX, % of spot)", "TAIEX return % (same month)",
        "Contemporaneous — basis vs same-month return",
    )
    r_lead = _scatter_with_fit(
        axes[1], t["mean_basis_pct"], t["taiex_ret_next_pct"],
        "monthly mean basis %  (this month)", "TAIEX return % (next month)",
        "Predictive — this-month basis vs next-month return",
    )

    ax = axes[2]
    ax.axhline(0, color="0.7", lw=0.8)
    ax.bar(t["date"], t["mean_basis_pct"], width=20, color="steelblue", alpha=0.6,
           label="mean basis % (left)")
    ax.set_ylabel("monthly mean basis %", color="steelblue", fontsize=9)
    ax.tick_params(axis="y", labelcolor="steelblue")
    ax2 = ax.twinx()
    ax2.plot(t["date"], t["taiex_ret_pct"], color="darkorange", lw=1.4, marker="o", ms=2.5,
             label="TAIEX return % (right)")
    ax2.set_ylabel("monthly TAIEX return %", color="darkorange", fontsize=9)
    ax2.tick_params(axis="y", labelcolor="darkorange")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_title("Time series — basis % and return %, by month", fontsize=10)
    ax.grid(alpha=0.25)

    fig.suptitle(
        "TAIEX–TAIFEX TX: monthly mean basis % vs monthly TAIEX return %  "
        f"(2020-01 .. {t['date'].iloc[-1]:%Y-%m})",
        fontsize=12, y=1.02,
    )
    fig.tight_layout()
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PNG, dpi=130, bbox_inches="tight")
    plt.close(fig)

    print(f"wrote {OUT_PNG}")
    print(f"contemporaneous corr(mean_basis_pct, taiex_ret_pct)        = {r_same:+.3f}  "
          f"(R² {r_same**2:.3f})")
    print(f"predictive   corr(mean_basis_pct, next-month taiex_ret_pct) = {r_lead:+.3f}  "
          f"(R² {r_lead**2:.3f})")
    if abs(r_same) < 0.4:
        verdict = "weakly related — the within-month link is mostly mechanical, not informative"
    elif abs(r_same) < 0.7:
        verdict = "moderately related — clearly co-moves, but a lot of noise"
    else:
        verdict = "strongly related"
    lead_note = ("no usable predictive content" if abs(r_lead) < 0.2
                 else "some weak predictive content")
    print(f"=> same-month: {verdict}.  next-month: {lead_note}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
