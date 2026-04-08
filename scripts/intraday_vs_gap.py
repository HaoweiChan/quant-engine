"""Decompose TX returns into within-session vs inter-session gap components.

Splits by night/day sessions to answer: are gains driven by intraday moves or gaps?
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.db import Database
from src.data.session_utils import session_id


def load_session_bars(db: Database, symbol: str) -> pd.DataFrame:
    """Load 1-min bars and aggregate to session-level OHLC."""
    bars = db.get_ohlcv(symbol, datetime(2020, 1, 1), datetime(2026, 12, 31))
    print(f"Loaded {len(bars):,} 1-min bars")

    # Group by session_id
    sessions: dict[str, list] = defaultdict(list)
    for b in bars:
        sid = session_id(b.timestamp)
        if sid == "CLOSED":
            continue
        sessions[sid].append(b)

    rows = []
    for sid, sbars in sorted(sessions.items()):
        if len(sbars) < 2:
            continue
        stype = "night" if sid.startswith("N") else "day"
        rows.append({
            "session_id": sid,
            "session_type": stype,
            "open": sbars[0].open,
            "close": sbars[-1].close,
            "high": max(b.high for b in sbars),
            "low": min(b.low for b in sbars),
            "first_ts": sbars[0].timestamp,
            "last_ts": sbars[-1].timestamp,
            "n_bars": len(sbars),
        })

    df = pd.DataFrame(rows).sort_values("first_ts").reset_index(drop=True)
    print(f"Found {len(df)} sessions ({(df.session_type == 'night').sum()} night, {(df.session_type == 'day').sum()} day)")
    return df


def decompose_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Compute within-session and gap returns."""
    df = df.copy()
    df["intraday_ret"] = (df["close"] - df["open"]) / df["open"]
    df["prev_close"] = df["close"].shift(1)
    df["gap_ret"] = (df["open"] - df["prev_close"]) / df["prev_close"]
    # Classify gap type
    prev_type = df["session_type"].shift(1)
    df["gap_type"] = np.where(
        prev_type == "night", "night→day", np.where(prev_type == "day", "day→night", "unknown")
    )
    df = df.iloc[1:].copy()  # drop first row (no prev_close)
    return df


def annualized_sharpe(returns: np.ndarray, periods_per_year: float) -> float:
    if len(returns) < 2 or np.std(returns) == 0:
        return 0.0
    return np.mean(returns) / np.std(returns) * np.sqrt(periods_per_year)


def print_summary(df: pd.DataFrame) -> None:
    """Print decomposition summary."""
    sessions_per_year = len(df) / ((df["first_ts"].iloc[-1] - df["first_ts"].iloc[0]).days / 365.25)

    print("\n" + "=" * 70)
    print("TX RETURN DECOMPOSITION: Within-Session vs Inter-Session Gaps")
    print("=" * 70)
    print(f"Period: {df['first_ts'].iloc[0].date()} to {df['first_ts'].iloc[-1].date()}")
    print(f"Sessions: {len(df)} (~{sessions_per_year:.0f}/year)")

    # Cumulative returns
    intra_cum = np.prod(1 + df["intraday_ret"].values) - 1
    gap_cum = np.prod(1 + df["gap_ret"].values) - 1
    total_cum = np.prod(1 + df["intraday_ret"].values + df["gap_ret"].values) - 1

    print(f"\n{'Component':<25} {'Cum Return':>12} {'Ann Sharpe':>12} {'Mean':>10} {'Std':>10}")
    print("-" * 70)

    for label, rets in [
        ("Within-session (all)", df["intraday_ret"].values),
        ("Gaps (all)", df["gap_ret"].values),
        ("Total", (df["intraday_ret"] + df["gap_ret"]).values),
    ]:
        cum = np.prod(1 + rets) - 1
        sharpe = annualized_sharpe(rets, sessions_per_year)
        print(f"{label:<25} {cum:>+11.1%} {sharpe:>12.2f} {np.mean(rets):>+10.4%} {np.std(rets):>10.4%}")

    # Split by session type
    print(f"\n{'--- By Session Type ---'}")
    for stype in ["night", "day"]:
        mask = df["session_type"] == stype
        rets = df.loc[mask, "intraday_ret"].values
        cum = np.prod(1 + rets) - 1
        n = mask.sum()
        sharpe = annualized_sharpe(rets, n / ((df["first_ts"].iloc[-1] - df["first_ts"].iloc[0]).days / 365.25))
        print(f"  {stype:<23} {cum:>+11.1%} {sharpe:>12.2f} {np.mean(rets):>+10.4%} {np.std(rets):>10.4%}  (n={n})")

    # Split by gap type
    print(f"\n{'--- By Gap Type ---'}")
    for gtype in ["night→day", "day→night"]:
        mask = df["gap_type"] == gtype
        rets = df.loc[mask, "gap_ret"].values
        cum = np.prod(1 + rets) - 1
        n = mask.sum()
        sharpe = annualized_sharpe(rets, n / ((df["first_ts"].iloc[-1] - df["first_ts"].iloc[0]).days / 365.25))
        print(f"  {gtype:<23} {cum:>+11.1%} {sharpe:>12.2f} {np.mean(rets):>+10.4%} {np.std(rets):>10.4%}  (n={n})")

    # Year-by-year breakdown
    df["year"] = df["first_ts"].dt.year
    print(f"\n{'--- Year-by-Year Cumulative Returns ---'}")
    print(f"{'Year':<8} {'Intraday':>12} {'Gap':>12} {'Total':>12}  {'Night Intra':>12} {'Day Intra':>12}")
    print("-" * 70)
    for year, grp in df.groupby("year"):
        intra = np.prod(1 + grp["intraday_ret"].values) - 1
        gap = np.prod(1 + grp["gap_ret"].values) - 1
        total = np.prod(1 + (grp["intraday_ret"] + grp["gap_ret"]).values) - 1
        night_intra = np.prod(1 + grp.loc[grp.session_type == "night", "intraday_ret"].values) - 1
        day_intra = np.prod(1 + grp.loc[grp.session_type == "day", "intraday_ret"].values) - 1
        print(f"{year:<8} {intra:>+11.1%} {gap:>+11.1%} {total:>+11.1%}  {night_intra:>+11.1%} {day_intra:>+11.1%}")


def save_chart(df: pd.DataFrame, path: Path) -> None:
    """Save cumulative equity curves."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 1]})

    # Top: cumulative equity curves
    ax = axes[0]
    intra_eq = np.cumprod(1 + df["intraday_ret"].values)
    gap_eq = np.cumprod(1 + df["gap_ret"].values)
    total_eq = np.cumprod(1 + (df["intraday_ret"] + df["gap_ret"]).values)

    night_rets = df["intraday_ret"].where(df["session_type"] == "night", 0).values
    day_rets = df["intraday_ret"].where(df["session_type"] == "day", 0).values
    night_eq = np.cumprod(1 + night_rets)
    day_eq = np.cumprod(1 + day_rets)

    dates = df["first_ts"].values
    ax.plot(dates, total_eq, label="Total", color="black", linewidth=2)
    ax.plot(dates, intra_eq, label="Within-session (all)", color="blue", linewidth=1.5)
    ax.plot(dates, gap_eq, label="Gaps (all)", color="red", linewidth=1.5)
    ax.plot(dates, night_eq, label="Night intraday", color="blue", linewidth=1, linestyle="--", alpha=0.7)
    ax.plot(dates, day_eq, label="Day intraday", color="cyan", linewidth=1, linestyle="--", alpha=0.7)
    ax.axhline(1, color="gray", linestyle=":", alpha=0.5)
    ax.set_ylabel("Cumulative Return (1 = start)")
    ax.set_title("TX Return Decomposition: Within-Session vs Gaps")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    # Bottom: annual bar chart
    ax2 = axes[1]
    df_copy = df.copy()
    df_copy["year"] = df_copy["first_ts"].dt.year
    yearly = []
    for year, grp in df_copy.groupby("year"):
        yearly.append({
            "year": year,
            "night_intra": np.prod(1 + grp.loc[grp.session_type == "night", "intraday_ret"].values) - 1,
            "day_intra": np.prod(1 + grp.loc[grp.session_type == "day", "intraday_ret"].values) - 1,
            "gap": np.prod(1 + grp["gap_ret"].values) - 1,
        })
    ydf = pd.DataFrame(yearly)
    x = np.arange(len(ydf))
    w = 0.25
    ax2.bar(x - w, ydf["night_intra"], w, label="Night intraday", color="blue", alpha=0.7)
    ax2.bar(x, ydf["day_intra"], w, label="Day intraday", color="cyan", alpha=0.7)
    ax2.bar(x + w, ydf["gap"], w, label="Gaps", color="red", alpha=0.7)
    ax2.set_xticks(x)
    ax2.set_xticklabels(ydf["year"].astype(int))
    ax2.set_ylabel("Annual Return")
    ax2.axhline(0, color="gray", linestyle=":", alpha=0.5)
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    print(f"\nChart saved to {path}")
    plt.close()


def main():
    db = Database("sqlite:///data/taifex_data.db")
    df = load_session_bars(db, "TX")
    df = decompose_returns(df)
    print_summary(df)
    save_chart(df, Path("output/intraday_vs_gap.png"))


if __name__ == "__main__":
    main()
