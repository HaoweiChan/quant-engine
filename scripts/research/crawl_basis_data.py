#!/usr/bin/env python3
"""Crawl TAIEX (TWSE spot index) and TAIFEX TX front-month daily closes and
build a daily futures-spot basis CSV.

Sources (both official, free, daily granularity):
  * TWSE  FMTQIK   -- daily 發行量加權股價指數 (TAIEX close), one request / month.
  * TAIFEX futDataDown -- daily TX futures bars per contract month + session,
    one request / month (the endpoint caps the date range at ~1 month).

The TAIFEX near-month is the smallest non-weekly 到期月份 trading in the
'一般' (day) session on a given date; the just-expired month drops out of the
file on the next trading day, so this auto-rolls.

Output: data/research/taiex_tx_basis_daily.csv with columns
  date, taiex_close, tx_close, tx_settlement, near_month,
  basis_pts (= tx_close - taiex_close), basis_pct (= basis_pts / taiex_close * 100),
  days_to_settle (calendar days to the 3rd-Wednesday settlement of near_month).

Idempotent: raw monthly payloads are cached under data/research/_cache/.
Complete past months are reused; the current month is always re-fetched.

Usage:  uv run python scripts/research/crawl_basis_data.py [--start YYYY-MM]
"""
from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "data" / "research"
CACHE_DIR = OUT_DIR / "_cache"
OUT_CSV = OUT_DIR / "taiex_tx_basis_daily.csv"

TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
TAIFEX_URL = "https://www.taifex.com.tw/cht/3/futDataDown"
HEADERS = {"User-Agent": "Mozilla/5.0 (research; quant-engine basis study)"}
POLITE_DELAY_S = 0.7
DEFAULT_START = (2020, 1)


def _months(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    while (y, m) <= end:
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def _is_complete_past_month(y: int, m: int, today: dt.date) -> bool:
    last_day = dt.date(y, m, calendar.monthrange(y, m)[1])
    return last_day < today


def _third_wednesday(y: int, m: int) -> dt.date:
    first = dt.date(y, m, 1)
    # weekday(): Mon=0 .. Wed=2
    offset = (2 - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 14)


def _http_post(url: str, payload: dict) -> bytes:
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as r:  # noqa: S310 (fixed hosts)
        return r.read()


def _http_get(url: str, params: dict) -> bytes:
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as r:  # noqa: S310 (fixed hosts)
        return r.read()


# ---------------------------------------------------------------------------
# TWSE: TAIEX daily close
# ---------------------------------------------------------------------------
def _parse_twse(raw: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in raw.get("data", []) or []:
        roc = str(row[0]).strip()  # e.g. "109/04/01"
        try:
            yy, mm, dd = roc.split("/")
            iso = f"{int(yy) + 1911:04d}-{int(mm):02d}-{int(dd):02d}"
            out[iso] = float(str(row[4]).replace(",", "").strip())
        except (ValueError, IndexError):
            continue
    return out


def _twse_payload_ok(raw: dict, y: int, m: int) -> bool:
    """A valid FMTQIK month payload: non-empty, and a majority of its rows fall
    in the requested year-month (TWSE occasionally serves a stale/wrong month)."""
    parsed = _parse_twse(raw)
    if not parsed:
        return False
    want = f"{y:04d}-{m:02d}"
    return sum(d.startswith(want) for d in parsed) >= max(1, len(parsed) // 2)


def fetch_twse_month(y: int, m: int, today: dt.date) -> dict[str, float]:
    """Return {YYYY-MM-DD: taiex_close} for the given month, with validated retry."""
    cache = CACHE_DIR / f"twse_{y}{m:02d}.json"
    if cache.exists() and _is_complete_past_month(y, m, today):
        try:
            raw = json.loads(cache.read_text())
            if _twse_payload_ok(raw, y, m):
                return _parse_twse(raw)
        except json.JSONDecodeError:
            pass
        # cached payload is stale/garbage -> drop it and re-fetch below
        cache.unlink(missing_ok=True)

    last_err: Exception | None = None
    for attempt in range(4):
        try:
            body = _http_get(TWSE_URL, {"date": f"{y}{m:02d}01", "response": "json"})
            raw = json.loads(body)
            if _twse_payload_ok(raw, y, m):
                cache.write_text(json.dumps(raw, ensure_ascii=False))
                time.sleep(POLITE_DELAY_S)
                return _parse_twse(raw)
            last_err = RuntimeError(f"empty/wrong-month payload (stat={raw.get('stat')})")
        except Exception as e:  # noqa: BLE001 - retry on transport / JSON errors
            last_err = e
        time.sleep(POLITE_DELAY_S + 1.5 * (attempt + 1) ** 2)  # 2.0, 6.5, 14.0s backoff
    raise RuntimeError(f"TWSE {y}-{m:02d} failed after retries: {last_err}")


# ---------------------------------------------------------------------------
# TAIFEX: TX front-month daily close + settlement
# ---------------------------------------------------------------------------
# CSV header (19 cols):
# 交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,
# 成交量,結算價,未沖銷契約數,最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,
# 是否因訊息面暫停交易,交易時段,價差對單式委託成交量
_C_DATE, _C_PROD, _C_MONTH, _C_CLOSE, _C_SETTLE, _C_SESSION = 0, 1, 2, 6, 10, 17


def _num(x: str) -> float | None:
    x = str(x).replace(",", "").strip()
    if x in ("", "-"):
        return None
    try:
        return float(x)
    except ValueError:
        return None


def fetch_taifex_month(y: int, m: int, today: dt.date) -> dict[str, dict]:
    """Return {YYYY-MM-DD: {tx_close, tx_settlement, near_month}} for the month."""
    cache = CACHE_DIR / f"taifex_tx_{y}{m:02d}.csv"
    if cache.exists() and _is_complete_past_month(y, m, today):
        text = cache.read_text(encoding="utf-8")
    else:
        last = calendar.monthrange(y, m)[1]
        body = _http_post(
            TAIFEX_URL,
            {
                "down_type": "1",
                "commodity_id": "TX",
                "queryStartDate": f"{y}/{m:02d}/01",
                "queryEndDate": f"{y}/{m:02d}/{last:02d}",
            },
        )
        text = body.decode("big5", errors="replace")
        if not text.lstrip().startswith("交易日期"):
            raise RuntimeError(f"TAIFEX returned non-CSV for {y}-{m:02d} (range cap / outage?)")
        cache.write_text(text, encoding="utf-8")
        time.sleep(POLITE_DELAY_S)

    # date -> list of (yyyymm_int, close, settle)
    candidates: dict[str, list[tuple[int, float, float | None]]] = {}
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or not header[0].startswith("交易日期"):
        return {}
    for row in reader:
        if len(row) <= _C_SESSION:
            continue
        if row[_C_PROD].strip() != "TX":
            continue
        if row[_C_SESSION].strip() != "一般":  # day session only
            continue
        mon = row[_C_MONTH].strip()
        if len(mon) != 6 or not mon.isdigit():
            continue  # skip weekly contracts (YYYYMMWn) and calendar spreads (YYYYMM/YYYYMM)
        close = _num(row[_C_CLOSE])
        if close is None:
            continue
        d = row[_C_DATE].strip().replace("/", "-")
        candidates.setdefault(d, []).append((int(mon), close, _num(row[_C_SETTLE])))

    out: dict[str, dict] = {}
    for d, lst in candidates.items():
        yyyymm, close, settle = min(lst, key=lambda t: t[0])  # near month
        out[d] = {"tx_close": close, "tx_settlement": settle, "near_month": yyyymm}
    return out


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=f"{DEFAULT_START[0]}-{DEFAULT_START[1]:02d}",
                    help="first month, YYYY-MM (default 2020-01)")
    args = ap.parse_args()
    sy, sm = (int(x) for x in args.start.split("-"))

    today = dt.date.today()
    end = (today.year, today.month)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"crawling {sy}-{sm:02d} .. {end[0]}-{end[1]:02d} (today={today})", flush=True)

    taiex: dict[str, float] = {}
    taifex: dict[str, dict] = {}
    for y, m in _months((sy, sm), end):
        n_tw = n_tf = 0
        try:
            tw = fetch_twse_month(y, m, today)
            taiex.update(tw)
            n_tw = len(tw)
        except Exception as e:  # noqa: BLE001 - log & continue, partial data still useful
            print(f"  WARN twse {y}-{m:02d}: {e}", flush=True)
        try:
            tf = fetch_taifex_month(y, m, today)
            taifex.update(tf)
            n_tf = len(tf)
        except Exception as e:  # noqa: BLE001
            print(f"  WARN taifex {y}-{m:02d}: {e}", flush=True)
        print(f"  {y}-{m:02d}: taiex+={n_tw} taifex+={n_tf} "
              f"(cum taiex={len(taiex)} taifex={len(taifex)})", flush=True)

    # join on dates present in BOTH series
    dates = sorted(set(taiex) & set(taifex))
    if not dates:
        print("ERROR: no overlapping dates", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "taiex_close", "tx_close", "tx_settlement", "near_month",
                    "basis_pts", "basis_pct", "days_to_settle"])
        for d in dates:
            s = taiex[d]
            f = taifex[d]
            fx = f["tx_close"]
            basis = fx - s
            nm = f["near_month"]
            ny, nmth = nm // 100, nm % 100
            tdate = dt.date.fromisoformat(d)
            dts = (_third_wednesday(ny, nmth) - tdate).days
            w.writerow([d, f"{s:.2f}", f"{fx:.2f}",
                        ("" if f["tx_settlement"] is None else f"{f['tx_settlement']:.2f}"),
                        nm, f"{basis:.2f}", f"{basis / s * 100:.4f}", dts])

    print(f"wrote {OUT_CSV} ({len(dates)} rows, {dates[0]} .. {dates[-1]})", flush=True)
    # quick spot-check echo
    last = dates[-1]
    print(f"latest: {last} TAIEX={taiex[last]:.2f} TX={taifex[last]['tx_close']:.2f} "
          f"basis={taifex[last]['tx_close'] - taiex[last]:+.1f} pts "
          f"near_month={taifex[last]['near_month']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
