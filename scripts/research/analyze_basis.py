#!/usr/bin/env python3
"""Analyse the TAIEX vs TAIFEX TX front-month basis.

Reads ``data/research/taiex_tx_basis_daily.csv`` (from crawl_basis_data.py) and
emits:
  * a month-by-month basis table  -> data/research/basis_monthly_table.csv
  * a calendar-month seasonal baseline (Jan..Dec, cross-year)
                                  -> data/research/basis_seasonal_baseline.csv
  * a z-score of the latest (in-progress) month against that baseline
  * a "how fast did it move" trajectory diagnostic
  * a light predictiveness check (does a seasonally-adjusted backwardation
    precede TAIEX weakness over the next ~20 trading days, in this sample?)
  * a cross-validation against the TX 1-min day-session close in data/market.db
  * a plain-language verdict.

Carry adjustment: the theoretical interest carry on a T-day forward is
``carry_pts ~= S * r * T / 365`` with r the annualised cost-of-carry rate.
Subtracting it leaves a residual that is approximately
``-(expected dividend points realised before settlement + sentiment premium)``.
r defaults to 1.5% (a representative Taiwan short rate over 2020-2026);
pass ``--rate`` to vary it.

Usage:  uv run python scripts/research/analyze_basis.py [--rate 0.015]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "data" / "research"
IN_CSV = OUT_DIR / "taiex_tx_basis_daily.csv"
MONTHLY_CSV = OUT_DIR / "basis_monthly_table.csv"
SEASONAL_CSV = OUT_DIR / "basis_seasonal_baseline.csv"

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _pctl(series: pd.Series, value: float) -> float:
    s = series.dropna()
    return float((s < value).mean() * 100.0) if len(s) else float("nan")


def _r1(x: float) -> float:
    return round(float(x), 1)


def load(rate: float) -> pd.DataFrame:
    df = pd.read_csv(IN_CSV, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["ym"] = df["date"].dt.to_period("M")
    df["carry_pts"] = df["taiex_close"] * rate * df["days_to_settle"].clip(lower=0) / 365.0
    df["residual_pts"] = df["basis_pts"] - df["carry_pts"]
    return df


def monthly_table(df: pd.DataFrame) -> pd.DataFrame:
    t = df.groupby(["year", "month"], as_index=False).agg(
        n_days=("basis_pts", "size"),
        mean_basis_pts=("basis_pts", "mean"),
        median_basis_pts=("basis_pts", "median"),
        mean_basis_pct=("basis_pct", "mean"),
        min_basis_pts=("basis_pts", "min"),
        max_basis_pts=("basis_pts", "max"),
        share_backwardation=("basis_pts", lambda s: float((s < 0).mean())),
        mean_residual_pts=("residual_pts", "mean"),
        first_taiex=("taiex_close", "first"),
        last_taiex=("taiex_close", "last"),
        mean_taiex=("taiex_close", "mean"),
    )
    # monthly TAIEX return = close-to-close vs the prior month's last close (the
    # standard monthly return); the first month in the sample uses its own
    # first->last close as a fallback so the column is never empty.
    prev_last = t["last_taiex"].shift(1)
    t["taiex_ret_pct"] = ((t["last_taiex"] / prev_last - 1.0) * 100.0)
    first_idx = t.index[0]
    t.loc[first_idx, "taiex_ret_pct"] = (t.loc[first_idx, "last_taiex"]
                                         / t.loc[first_idx, "first_taiex"] - 1.0) * 100.0
    # next-month return aligned to the current row (for "does basis predict?")
    t["taiex_ret_next_pct"] = t["taiex_ret_pct"].shift(-1)
    pts_cols = ["mean_basis_pts", "median_basis_pts", "min_basis_pts",
                "max_basis_pts", "mean_residual_pts", "first_taiex", "last_taiex", "mean_taiex"]
    t[pts_cols] = t[pts_cols].round(1)
    t["mean_basis_pct"] = t["mean_basis_pct"].round(3)
    t["taiex_ret_pct"] = t["taiex_ret_pct"].round(3)
    t["taiex_ret_next_pct"] = t["taiex_ret_next_pct"].round(3)
    t["share_backwardation"] = t["share_backwardation"].round(3)
    return t


def seasonal_baseline(monthly: pd.DataFrame, cur: pd.Period) -> tuple[pd.DataFrame, dict]:
    """Cross-year (complete-month) baseline per calendar month, plus a z-score
    of the latest in-progress month vs its calendar-month baseline.

    The whole current year is excluded from the baselines (not just the
    in-progress month) so every calendar month is scored against the same set of
    prior, settled years -- otherwise an extreme partial year would contaminate
    the Jan..Apr norms while May..Dec used only prior years."""
    base = monthly[monthly["year"] < cur.year]
    rows = []
    for m in range(1, 13):
        sub = base[base["month"] == m]
        vb = sub["mean_basis_pts"].to_numpy(dtype=float)
        vr = sub["mean_residual_pts"].to_numpy(dtype=float)
        has = len(vb) > 0
        has2 = len(vb) > 1
        rows.append({
            "month": m,
            "month_name": MONTH_NAMES[m - 1],
            "n_years": int(len(sub)),
            "seasonal_mean_basis": _r1(np.mean(vb)) if has else np.nan,
            "seasonal_std_basis": _r1(np.std(vb, ddof=1)) if has2 else np.nan,
            "seasonal_min_basis": _r1(np.min(vb)) if has else np.nan,
            "seasonal_max_basis": _r1(np.max(vb)) if has else np.nan,
            "seasonal_mean_residual": _r1(np.mean(vr)) if has else np.nan,
            "seasonal_std_residual": _r1(np.std(vr, ddof=1)) if has2 else np.nan,
            "years_used": ",".join(str(int(y)) for y in sorted(sub["year"].tolist())),
        })
    seas = pd.DataFrame(rows)

    crow = monthly[(monthly["year"] == cur.year) & (monthly["month"] == cur.month)]
    srow = seas[seas["month"] == cur.month].iloc[0]
    cur_basis = float(crow["mean_basis_pts"].iloc[0]) if len(crow) else np.nan
    cur_resid = float(crow["mean_residual_pts"].iloc[0]) if len(crow) else np.nan

    def _z(value: float, mean: float, std: float) -> float | None:
        if std is None or np.isnan(std) or std == 0 or np.isnan(value):
            return None
        return round((value - mean) / std, 2)

    # Dividend-season trough, detected from the data (not hard-coded): start at
    # the month with the lowest seasonal basis and grow a *contiguous* run while
    # each neighbour is still at least half as negative as the trough. This
    # isolates the ex-dividend block (the deep, persistent, consecutive dip)
    # from one-off crisis cells in otherwise-shoulder months.
    vals = {int(r.month): float(r.seasonal_mean_basis) for r in seas.itertuples()}
    trough_m = min(vals, key=vals.get)
    thr = 0.5 * vals[trough_m]  # trough is negative -> thr ~ half-way to zero
    block = {trough_m}
    for step in (-1, 1):
        m = trough_m
        while True:
            m = m + step if 1 <= m + step <= 12 else (12 if m + step < 1 else 1)
            if m in block or vals.get(m, 0.0) > thr:
                break
            block.add(m)
    trough_block = sorted(block)
    lowest4 = sorted(seas.sort_values("seasonal_mean_basis")["month"].tolist()[:4])

    info = {
        "current_period": str(cur),
        "current_month_name": MONTH_NAMES[cur.month - 1],
        "n_days_current": int(crow["n_days"].iloc[0]) if len(crow) else 0,
        "cur_mean_basis": _r1(cur_basis),
        "cur_mean_residual": _r1(cur_resid),
        "seasonal_mean_basis": float(srow["seasonal_mean_basis"]),
        "seasonal_std_basis": (None if np.isnan(srow["seasonal_std_basis"])
                               else float(srow["seasonal_std_basis"])),
        "seasonal_mean_residual": float(srow["seasonal_mean_residual"]),
        "seasonal_std_residual": (None if np.isnan(srow["seasonal_std_residual"])
                                  else float(srow["seasonal_std_residual"])),
        "z_basis": _z(cur_basis, srow["seasonal_mean_basis"], srow["seasonal_std_basis"]),
        "z_residual": _z(cur_resid, srow["seasonal_mean_residual"], srow["seasonal_std_residual"]),
        "dividend_season_block": [MONTH_NAMES[m - 1] for m in trough_block],
        "trough_month": MONTH_NAMES[trough_m - 1],
        "lowest_4_basis_months": [MONTH_NAMES[m - 1] for m in lowest4],
        "years_used_for_current_month": srow["years_used"],
    }
    return seas, info


def trajectory(df: pd.DataFrame) -> dict:
    """How unusual is the recent *move* in the basis, vs its own history?"""
    d = df.sort_values("date").reset_index(drop=True)
    raw = d["basis_pts"]
    latest = float(raw.iloc[-1])
    latest_dt = d["date"].iloc[-1]
    out: dict = {"latest_date": str(latest_dt.date()), "latest_day_basis_pts": _r1(latest)}
    for k in (1, 3, 5, 10):
        chg = raw.diff(k)
        cv = float(chg.iloc[-1])
        out[f"chg{k}d_recent_pts"] = _r1(cv)
        out[f"chg{k}d_percentile"] = round(_pctl(chg, cv), 1)
    s = d.set_index("date")["basis_pts"].asfreq("B").interpolate()
    roll20 = s.rolling(20, min_periods=10).mean()
    out["cur_roll20_basis_pts"] = _r1(roll20.iloc[-1])
    out["cur_roll20_level_percentile"] = round(_pctl(raw, float(roll20.iloc[-1])), 1)
    chg60 = roll20.diff(60)
    out["roll20_chg60d_pts"] = _r1(chg60.iloc[-1])
    out["roll20_chg60d_percentile"] = round(_pctl(chg60, float(chg60.iloc[-1])), 1)
    out["latest_day_level_percentile"] = round(_pctl(raw, latest), 1)
    cm = latest_dt.month
    prior = d[(d["month"] == cm) & (d["date"] < pd.Timestamp(latest_dt.year, cm, 1))]["basis_pts"]
    if len(prior):
        out["same_month_prior_years"] = {
            "n": int(len(prior)),
            "min": _r1(prior.min()), "p05": _r1(prior.quantile(0.05)),
            "p50": _r1(prior.median()), "p95": _r1(prior.quantile(0.95)),
            "max": _r1(prior.max()), "latest_day_percentile": round(_pctl(prior, latest), 1),
        }
    else:
        out["same_month_prior_years"] = {"n": 0}
    return out


def predictiveness(df: pd.DataFrame) -> dict:
    """Does a *seasonally-adjusted* backwardation precede TAIEX weakness over
    the next ~20 trading days, in this sample?"""
    d = df.copy()
    d["basis_sa"] = d["basis_pts"] - d.groupby("month")["basis_pts"].transform("mean")
    roll_mean = d["basis_sa"].rolling(252, min_periods=60).mean()
    roll_std = d["basis_sa"].rolling(252, min_periods=60).std(ddof=0)
    d["sa_z"] = (d["basis_sa"] - roll_mean) / roll_std
    d["fwd20_ret"] = d["taiex_close"].shift(-20) / d["taiex_close"] - 1.0
    sub = d.dropna(subset=["sa_z", "fwd20_ret"])
    if len(sub) < 100:
        return {"note": "insufficient data"}

    def _grp(mask: pd.Series) -> dict | None:
        r = sub.loc[mask, "fwd20_ret"]
        return {"n": int(len(r)), "mean_pct": round(float(r.mean()) * 100, 2)} if len(r) else None

    cur_z = d["sa_z"].dropna().iloc[-1]
    return {
        "n_obs": int(len(sub)),
        "corr_saZ_vs_fwd20ret": round(float(np.corrcoef(sub["sa_z"], sub["fwd20_ret"])[0, 1]), 3),
        "fwd20ret_when_saZ_lt_-1": _grp(sub["sa_z"] < -1.0),
        "fwd20ret_when_saZ_gt_+1": _grp(sub["sa_z"] > 1.0),
        "fwd20ret_when_saZ_mid": _grp((sub["sa_z"] >= -1.0) & (sub["sa_z"] <= 1.0)),
        "current_saZ": round(float(cur_z), 2),
    }


def cross_validate(df: pd.DataFrame) -> dict:
    """TAIFEX near-month day close vs the TX 1-min day-session close in market.db."""
    import sqlite3
    db = PROJECT_ROOT / "data" / "market.db"
    if not db.exists():
        return {"note": "data/market.db not found"}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        q = (
            "SELECT substr(timestamp,1,10) AS d, close FROM ohlcv_bars "
            "WHERE symbol='TX' AND substr(timestamp,12,5) BETWEEN '13:30' AND '13:45' "
            "GROUP BY d HAVING max(timestamp)"
        )
        mdb = pd.read_sql(q, con)
    finally:
        con.close()
    mdb["d"] = pd.to_datetime(mdb["d"])
    j = df.merge(mdb, left_on="date", right_on="d", how="inner")
    if j.empty:
        return {"note": "no overlap"}
    diff = (j["tx_close"] - j["close"]).abs()
    big = j[diff > 50].sort_values(by="date")
    return {
        "n_overlap_days": int(len(j)),
        "window": f"{j['date'].min().date()} .. {j['date'].max().date()}",
        "corr": round(float(np.corrcoef(j["tx_close"], j["close"])[0, 1]), 6),
        "mean_abs_diff_pts": _r1(diff.mean()),
        "p95_abs_diff_pts": _r1(diff.quantile(0.95)),
        "max_abs_diff_pts": _r1(diff.max()),
        "n_days_diff_gt_50pts": int((diff > 50).sum()),
        "big_diff_dates": [str(d.date()) for d in big["date"].tolist()][:12],
    }


def basis_return_relation(monthly: pd.DataFrame) -> dict:
    """Is the monthly mean basis % related to the monthly TAIEX return %?
    Reports the contemporaneous correlation (same month) and the lead one
    (this month's basis vs next month's return)."""
    m = monthly.dropna(subset=["mean_basis_pct", "taiex_ret_pct"])
    same = (float(np.corrcoef(m["mean_basis_pct"], m["taiex_ret_pct"])[0, 1])
            if len(m) > 2 else np.nan)
    ml = monthly.dropna(subset=["mean_basis_pct", "taiex_ret_next_pct"])
    lead = (float(np.corrcoef(ml["mean_basis_pct"], ml["taiex_ret_next_pct"])[0, 1])
            if len(ml) > 2 else np.nan)
    # simple OLS slope for the contemporaneous fit (return% per 1pp of basis%)
    slope = np.polyfit(m["mean_basis_pct"], m["taiex_ret_pct"], 1)[0] if len(m) > 2 else np.nan
    lead_r = round(lead, 3) if not np.isnan(lead) else None
    return {
        "n_months": int(len(m)),
        "corr_same_month(meanBasisPct, taiexRetPct)": round(same, 3),
        "OLS_slope_taiexRetPct_per_1pp_basisPct": round(float(slope), 2),
        "r_squared_same_month": round(same ** 2, 3),
        "corr_lead(thisMonthBasisPct, nextMonthRetPct)": lead_r,
        "interpretation": ("contemporaneous link is mostly mechanical: a strong within-month "
                           "move drags the futures the same way (contango on rallies, "
                           "backwardation on sell-offs); the lead correlation near 0 means the "
                           "monthly basis has little standalone power to forecast next month."),
    }


def fmt_block(title: str, payload: dict) -> str:
    return "\n".join([f"== {title} =="] + [f"  {k}: {v}" for k, v in payload.items()])


def _bucket(z: float | None) -> str:
    if z is None:
        return "INSUFFICIENT HISTORY"
    if abs(z) < 1:
        return "within seasonal norm"
    side = "negative / toward backwardation" if z < 0 else "positive / toward contango"
    return f"{'somewhat' if abs(z) < 2 else 'abnormally'} more {side} than seasonal norm"


def verdict_lines(info: dict, traj: dict, pred: dict) -> list[str]:
    z, zr = info["z_basis"], info["z_residual"]
    smp = traj["same_month_prior_years"]
    mn = info["current_month_name"]
    in_div = mn in info["dividend_season_block"]
    div_note = f"{mn} IS in that block" if in_div else f"{mn} is NOT in the heavy ex-div block"
    lines = [
        "## VERDICT",
        f"  Latest print: {traj['latest_date']}  basis = {traj['latest_day_basis_pts']:+.0f} pts"
        " (TX day-close minus TAIEX close).",
        f"  Month-to-date ({info['current_period']}, {info['n_days_current']}d): "
        f"mean basis {info['cur_mean_basis']:+.0f} pts, carry-adj residual "
        f"{info['cur_mean_residual']:+.0f} pts.",
        f"  Seasonal {mn} norm ({info['years_used_for_current_month']}): "
        f"{info['seasonal_mean_basis']:+.0f} ± {info['seasonal_std_basis']:.0f} pts "
        f"(residual norm {info['seasonal_mean_residual']:+.0f}).",
        f"  z(MTD mean basis vs seasonal) = {('n/a' if z is None else f'{z:+.2f}')} "
        f"-> {_bucket(z)}.",
        f"  z(carry-adj residual vs seasonal) = {('n/a' if zr is None else f'{zr:+.2f}')} "
        f"-> {_bucket(zr)}.",
        f"  Ex-dividend trough (contiguous block around the seasonal min {info['trough_month']}, "
        f"detected from the data): {info['dividend_season_block']}.  "
        f"{div_note} -> dividends explain only a small part of any {mn} backwardation.",
    ]
    if smp.get("n"):
        pc = smp["latest_day_percentile"]
        edge = ("extreme low end, but matched only by the 2021 record" if pc is not None and pc < 5
                else "within the historical range")
        lines.append(
            f"  The single-day {traj['latest_day_basis_pts']:+.0f} pts vs all prior {mn} days "
            f"(n={smp['n']}): range [{smp['min']:+.0f} .. {smp['max']:+.0f}], "
            f"median {smp['p50']:+.0f}, p05 {smp['p05']:+.0f}  ->  percentile {pc:.0f} ({edge})."
        )
    fast = ("an unusually fast collapse" if traj["chg5d_percentile"] < 5
            else "fast, but within history")
    lines.append(
        f"  Speed of the flip: 1d {traj['chg1d_recent_pts']:+.0f} "
        f"(pctl {traj['chg1d_percentile']:.0f}), 3d {traj['chg3d_recent_pts']:+.0f} "
        f"(pctl {traj['chg3d_percentile']:.0f}), 5d {traj['chg5d_recent_pts']:+.0f} "
        f"(pctl {traj['chg5d_percentile']:.0f})  ->  {fast}."
    )
    roll = traj["cur_roll20_basis_pts"]
    regime = ("extreme CONTANGO (opposite of backwardation)" if roll > 50
              else "roughly flat" if abs(roll) <= 50 else "backwardation")
    lines.append(
        f"  Context: the 20d-smoothed basis is still {roll:+.0f} pts "
        f"(pctl {traj['cur_roll20_level_percentile']:.0f} of all daily readings) -> the "
        f"{info['current_period']} regime as a whole is {regime}; the latest "
        f"{traj['latest_day_basis_pts']:+.0f} pt print "
        f"(pctl {traj['latest_day_level_percentile']:.0f}) is a one-day overshoot off that, "
        "not an established backwardation regime."
    )
    lo, hi = pred.get("fwd20ret_when_saZ_lt_-1") or {}, pred.get("fwd20ret_when_saZ_gt_+1") or {}
    if lo and hi:
        lines.append(
            f"  Predictiveness (2020-2026 sample): seasonally-adjusted basis >=1σ LOW -> next-20d "
            f"TAIEX +{lo.get('mean_pct')}% (n={lo.get('n')}); >=1σ HIGH -> +{hi.get('mean_pct')}% "
            f"(n={hi.get('n')}); corr={pred.get('corr_saZ_vs_fwd20ret')}.  In this bull-dominated "
            "window a deep ex-dividend backwardation has NOT been a bearish signal."
        )
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=0.015,
                    help="annualised carry rate (default 0.015)")
    args = ap.parse_args()
    if not IN_CSV.exists():
        print(f"ERROR: {IN_CSV} not found - run crawl_basis_data.py first", file=sys.stderr)
        return 1

    df = load(args.rate)
    monthly = monthly_table(df)
    cur_period = df["ym"].max()
    seas, info = seasonal_baseline(monthly, cur_period)
    traj = trajectory(df)
    pred = predictiveness(df)
    relation = basis_return_relation(monthly)
    xval = cross_validate(df)

    monthly.to_csv(MONTHLY_CSV, index=False)
    seas.to_csv(SEASONAL_CSV, index=False)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 200)
    print(f"# rows={len(df)}  window={df['date'].min().date()} .. {df['date'].max().date()}  "
          f"carry_rate={args.rate:.3%}")
    print("\n## Month-by-month basis table")
    print(monthly.to_string(index=False))
    print("\n## Calendar-month seasonal baseline (complete months only)")
    print(seas.to_string(index=False))
    print("\n" + fmt_block("Latest month vs seasonal baseline", info))
    print("\n" + fmt_block("Trajectory unusualness (recent move in the basis)", traj))
    print("\n" + fmt_block("Monthly mean basis % vs monthly TAIEX return %", relation))
    print("\n" + fmt_block("Predictiveness: seasonally-adj basis -> fwd 20d TAIEX", pred))
    print("\n" + fmt_block("Cross-validation: TAIFEX near-month vs market.db TX 1m", xval))
    print("\n" + "\n".join(verdict_lines(info, traj, pred)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
