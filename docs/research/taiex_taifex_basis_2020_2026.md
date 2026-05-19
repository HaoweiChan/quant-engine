# TAIEX vs TAIFEX TX front-month basis, 2020 → 2026‑05

**Question (from the user / the screenshot doing the rounds):** TAIEX spot ≈ 42 053, TX
futures ≈ 41 862 — a −191 pt 逆價差 (backwardation). Is the current spread *bearish
emotion / 法人避險賣壓*, or just *normal dividend‑season backwardation* ("除權息旺季的結構性逆價差")?

**Short answer:** **Neither, exactly.** The ≈ −200 pt print is (a) **not** a dividend‑season
effect — Taiwan's heavy ex‑dividend block is Jun–Aug, not early May, and May's seasonal
basis is only about −24 pts; (b) it **is** a genuinely extreme single‑day *price* basis —
near the worst May reading in six years — so the commentator's instinct that "this isn't
nothing" is right; but (c) on the evidence so far it is best described as a **violent
one‑day unwind of an over‑stretched bullish contango**, not (yet) a confirmed bearish
regime — through 2026 the TX front month has been the *most contango on record* (+110 pts
average YTD, futures running 300‑500 pts *above* spot for two months), and in this
2020‑2026 sample a deep ex‑dividend‑adjusted backwardation has *preceded higher* TAIEX
returns, not lower. Watch whether the basis *stays* negative for weeks (that is what a real
bear looks like — see Jun 2022); a single −200 day reverting toward zero is the more typical
outcome in this dataset.

On the "is it related to the move?" question (the plot in §6): the monthly mean basis % is a
**coincident** read on risk appetite, not a leading one — `corr` with the *same-month* TAIEX
return is **+0.32** (R² ≈ 0.10; positive but noisy — rallies → contango, sell-offs →
backwardation), while `corr` with the *next-month* return is **+0.03** (≈ none). So the −200 pt
print is the futures *reacting to* the pullback, not foreseeing one.

Everything below is reproducible from three scripts and the data they cache:

- `scripts/research/crawl_basis_data.py` → `data/research/taiex_tx_basis_daily.csv`
  (1 541 trading days, 2020‑01‑02 … 2026‑05‑12)
- `scripts/research/analyze_basis.py` → `data/research/basis_monthly_table.csv`,
  `data/research/basis_seasonal_baseline.csv`, and the printed verdict block.
- `scripts/research/plot_basis_vs_return.py` → `data/research/basis_vs_return.png`
  (monthly mean basis % vs monthly TAIEX return %; see §6).

---

## 1. Methodology

| Item | Choice | Notes |
|---|---|---|
| **Spot (TAIEX)** | TWSE FMTQIK daily 發行量加權股價指數 (close) | One request per month; official; ROC dates converted to ISO. |
| **Futures (TX)** | TAIFEX `futDataDown` daily file, **near‑month**, **一般 (day) session 收盤價** | One request per month (the endpoint caps the range at ~1 month). Near‑month = the smallest non‑weekly 到期月份 trading that day; the just‑expired month drops out of the file the next day, so it auto‑rolls. `結算價` is also captured. |
| **Basis** | `basis_pts = TX_close − TAIEX_close`; `basis_pct = basis_pts / TAIEX_close` | "Close‑to‑close." See caveats below. |
| **Carry adjustment** | `carry_pts ≈ TAIEX × r × days_to_settle / 365`, r = 1.5 % default | `days_to_settle` = calendar days to the 3rd‑Wednesday settlement of the near‑month. `residual_pts = basis_pts − carry_pts ≈ −(dividend points before settlement + sentiment premium)`. |
| **Seasonal baseline** | For each calendar month, the cross‑year mean ± std of that month's monthly‑mean basis over the **completed prior years 2020‑2025** (the whole in‑progress 2026 is excluded — not just May — so every calendar month is scored against the same prior‑year set; otherwise an extreme partial year would contaminate the Jan–Apr norms). | z‑score = (2026‑05 month‑to‑date mean − May baseline mean) / May baseline std. |
| **Ex‑dividend trough detection** | From the data, not hard‑coded: start at the calendar month with the lowest seasonal basis and grow a *contiguous* run while each neighbour is still at least half as negative as the trough. | Isolates the persistent ex‑dividend dip from one‑off crisis cells in otherwise‑shoulder months. |

**Caveat 1 — close‑to‑close timing.** TAIEX's official close is the 13:30 call auction;
the TX day session closes at 13:45. The basis here is therefore TX‑13:45 minus TAIEX‑13:30
— a consistent ~15‑minute offset. The screenshot's −191 was an *intraday simultaneous*
quote; our 2026‑05‑12 close‑to‑close basis is −203. Same ballpark, same conclusion.

**Caveat 2 — front‑month roll decay.** A front‑month future mechanically converges to spot
as settlement approaches, then "resets" to a wider value when the front rolls to the next
month. So a monthly *mean* of the front‑month basis blends "near‑expiry, small basis" days
with "far‑from‑expiry, larger basis" days. This is why we also report the carry‑adjusted
residual and use month‑level aggregates rather than reading single days in isolation.

**Caveat 3 — settlement‑day artefact.** On the 3rd Wednesday the expiring contract settles
in the morning (final settlement = special opening quote) and the daily file then freezes
its 收盤價 near that morning value, even though the cash index keeps moving. So settlement‑day
basis prints are stale by construction. This affects ~6 days/year (~3 % of the sample) and
is immaterial to the monthly aggregates.

**Cross‑validation (sanity check).** For the 1 494 overlapping days 2020‑03‑02 … 2026‑04‑23
the TAIFEX near‑month day close matches the **TX 1‑minute day‑session close already stored
in `data/market.db`** with correlation **0.999985**, mean absolute difference **4.5 pts**,
and **p95 difference = 0.0** (i.e. it is identical to the tick on ≥ 95 % of days). The 45
days with a > 50 pt difference are *exactly the 3rd‑Wednesday settlement days* (Caveat 3) —
on those, `market.db`'s continuous `TX` series has already rolled to the next month while
the daily file freezes the expiring one. So the pipeline is sound; the divergences are the
expected ones.

---

## 2. Month‑by‑month basis table

`mean` / `median` / `min` / `max` in index points; `mean%` = mean basis as % of spot;
`ret%` = the month's TAIEX close-to-close return (vs the prior month's last close);
`%bw` = share of trading days with basis < 0; `resid` = mean carry-adjusted residual
(≈ dividend drag + sentiment, with the interest carry removed). Full daily data:
`data/research/taiex_tx_basis_daily.csv`; full monthly table (incl. `taiex_ret_pct`,
`taiex_ret_next_pct`): `data/research/basis_monthly_table.csv`.

| Month | n | mean | median | mean% | ret%* | min | max | %bw | resid |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2020-01 | 15 | -15 | -11 | -0.12% | -5.0% | -52 | +4 | 80% | -21 |
| 2020-02 | 19 | -12 | -10 | -0.11% | -1.8% | -32 | +6 | 79% | -19 |
| 2020-03 | 22 | -80 | -58 | -0.84% | -14.0% | -328 | +44 | 91% | -85 |
| 2020-04 | 20 | -44 | -35 | -0.42% | +13.2% | -112 | +13 | 80% | -51 |
| 2020-05 | 20 | -28 | -24 | -0.26% | -0.5% | -106 | +22 | 85% | -34 |
| 2020-06 | 20 | -73 | -39 | -0.63% | +6.2% | -182 | +14 | 95% | -79 |
| 2020-07 | 23 | -92 | -109 | -0.75% | +9.0% | -157 | +17 | 96% | -101 |
| 2020-08 | 21 | -37 | -40 | -0.29% | -0.6% | -81 | +27 | 90% | -44 |
| 2020-09 | 22 | -37 | -29 | -0.30% | -0.6% | -138 | +7 | 91% | -46 |
| 2020-10 | 19 | -36 | -29 | -0.28% | +0.2% | -132 | +12 | 90% | -43 |
| 2020-11 | 21 | -7 | -3 | -0.06% | +9.4% | -76 | +32 | 62% | -14 |
| 2020-12 | 23 | -35 | -26 | -0.25% | +7.4% | -132 | +18 | 78% | -45 |
| 2021-01 | 20 | -21 | -24 | -0.13% | +2.8% | -72 | +22 | 80% | -29 |
| 2021-02 | 13 | -24 | -25 | -0.15% | +5.4% | -64 | +2 | 85% | -36 |
| 2021-03 | 22 | -30 | -32 | -0.19% | +3.0% | -65 | +19 | 96% | -42 |
| 2021-04 | 19 | -13 | -10 | -0.08% | +6.9% | -47 | +29 | 74% | -23 |
| 2021-05 | 21 | -43 | -44 | -0.27% | -2.8% | -210 | +31 | 81% | -52 |
| 2021-06 | 21 | -37 | -47 | -0.21% | +4.0% | -101 | +37 | 76% | -49 |
| 2021-07 | 22 | -50 | -32 | -0.29% | -2.9% | -202 | +30 | 73% | -60 |
| 2021-08 | 22 | -62 | -58 | -0.36% | +1.4% | -149 | -25 | 100% | -71 |
| 2021-09 | 20 | -8 | -7 | -0.05% | -3.2% | -69 | +28 | 65% | -19 |
| 2021-10 | 20 | -21 | -11 | -0.12% | +0.3% | -76 | +20 | 75% | -30 |
| 2021-11 | 22 | -1 | +8 | -0.01% | +2.6% | -101 | +36 | 46% | -11 |
| 2021-12 | 22 | -3 | +2 | -0.02% | +4.5% | -89 | +28 | 46% | -16 |
| 2022-01 | 18 | -16 | -14 | -0.09% | -3.0% | -49 | +19 | 83% | -26 |
| 2022-02 | 15 | -24 | -21 | -0.14% | -0.1% | -91 | +15 | 87% | -34 |
| 2022-03 | 23 | -41 | -40 | -0.24% | +0.2% | -123 | +13 | 87% | -53 |
| 2022-04 | 19 | -15 | -18 | -0.09% | -6.2% | -72 | +52 | 74% | -24 |
| 2022-05 | 21 | -26 | -22 | -0.16% | +1.3% | -126 | +20 | 71% | -35 |
| **2022-06** | 21 | **-167** | -204 | **-1.07%** | **-11.8%** | -441 | +63 | 86% | -178 |
| 2022-07 | 21 | -96 | -76 | -0.66% | +1.2% | -198 | -16 | 100% | -105 |
| 2022-08 | 23 | -51 | -44 | -0.34% | +0.6% | -112 | +1 | 96% | -61 |
| 2022-09 | 21 | -30 | -28 | -0.20% | -11.1% | -81 | +49 | 86% | -38 |
| 2022-10 | 20 | +4 | +7 | +0.03% | -3.5% | -46 | +58 | 45% | -3 |
| 2022-11 | 22 | -28 | -24 | -0.20% | **+14.9%** | -82 | +50 | 86% | -38 |
| 2022-12 | 22 | -38 | -34 | -0.26% | -5.0% | -85 | +2 | 96% | -46 |
| 2023-01 | 13 | +5 | +6 | +0.03% | +8.0% | -43 | +41 | 31% | -0 |
| 2023-02 | 18 | -15 | -15 | -0.10% | +1.6% | -47 | +38 | 78% | -23 |
| 2023-03 | 23 | -21 | -27 | -0.14% | +2.4% | -58 | +16 | 74% | -32 |
| 2023-04 | 17 | +1 | +6 | +0.01% | -1.8% | -51 | +24 | 35% | -7 |
| 2023-05 | 22 | -24 | -17 | -0.15% | +6.4% | -90 | +35 | 64% | -35 |
| 2023-06 | 20 | -49 | -20 | -0.29% | +2.0% | -186 | +27 | 70% | -58 |
| 2023-07 | 21 | -38 | -39 | -0.23% | +1.4% | -103 | +23 | 90% | -48 |
| 2023-08 | 22 | -24 | -20 | -0.14% | -3.0% | -83 | +25 | 77% | -35 |
| 2023-09 | 20 | -5 | -2 | -0.03% | -1.7% | -55 | +32 | 50% | -14 |
| 2023-10 | 20 | +0 | +1 | +0.00% | -2.2% | -42 | +45 | 50% | -9 |
| 2023-11 | 22 | +8 | +11 | +0.05% | +9.0% | -41 | +53 | 32% | -4 |
| 2023-12 | 21 | -10 | -7 | -0.06% | +2.9% | -63 | +20 | 67% | -20 |
| 2024-01 | 22 | +5 | +3 | +0.03% | -0.2% | -56 | +52 | 46% | -7 |
| 2024-02 | 13 | +15 | +18 | +0.08% | +6.0% | -10 | +36 | 31% | +4 |
| 2024-03 | 21 | +21 | +14 | +0.10% | +7.0% | -37 | +65 | 19% | +10 |
| 2024-04 | 20 | +47 | +54 | +0.23% | +0.5% | -0 | +113 | 5% | +36 |
| 2024-05 | 22 | +47 | +46 | +0.22% | +3.8% | -4 | +111 | 18% | +32 |
| 2024-06 | 19 | -23 | -22 | -0.10% | +8.8% | -133 | +117 | 63% | -35 |
| 2024-07 | 21 | +3 | -7 | +0.02% | -3.6% | -109 | +122 | 52% | -12 |
| **2024-08** | 22 | -61 | -38 | -0.29% | +0.3% | **-457** | +55 | 73% | -73 |
| 2024-09 | 20 | +3 | +13 | +0.01% | -0.2% | -146 | +102 | 50% | -10 |
| 2024-10 | 19 | +57 | +49 | +0.25% | +2.7% | -67 | +202 | 21% | +40 |
| 2024-11 | 21 | +34 | +28 | +0.15% | -2.4% | -113 | +227 | 29% | +22 |
| 2024-12 | 22 | +23 | +9 | +0.10% | +3.5% | -83 | +138 | 46% | +11 |
| 2025-01 | 15 | +48 | +43 | +0.20% | +2.1% | -48 | +173 | 7% | +34 |
| 2025-02 | 19 | +2 | -0 | +0.01% | -2.0% | -97 | +143 | 53% | -10 |
| 2025-03 | 21 | -1 | -7 | -0.00% | -10.2% | -56 | +73 | 52% | -13 |
| 2025-04 | 20 | -55 | -62 | -0.29% | -2.2% | -270 | +80 | 75% | -68 |
| 2025-05 | 20 | -70 | -65 | -0.33% | +5.5% | -186 | +45 | 75% | -82 |
| **2025-06** | 21 | **-173** | -133 | **-0.78%** | +4.3% | -459 | -18 | 100% | -185 |
| 2025-07 | 23 | -70 | -82 | -0.31% | +5.8% | -201 | +46 | 78% | -86 |
| 2025-08 | 21 | -34 | -23 | -0.14% | +2.9% | -119 | +34 | 81% | -48 |
| 2025-09 | 21 | -0 | -4 | -0.01% | +6.6% | -103 | +134 | 57% | -14 |
| 2025-10 | 20 | +61 | +54 | +0.22% | +9.3% | -120 | +231 | 20% | +41 |
| 2025-11 | 20 | +53 | +50 | +0.19% | -2.1% | -80 | +146 | 10% | +38 |
| 2025-12 | 22 | +70 | +73 | +0.25% | +4.8% | -42 | +198 | 23% | +51 |
| 2026-01 | 21 | +115 | +123 | +0.37% | +10.7% | -88 | +241 | 10% | +98 |
| 2026-02 | 12 | +112 | +96 | +0.34% | +10.4% | -14 | +246 | 8% | +94 |
| 2026-03 | 22 | -14 | -38 | -0.04% | **-10.4%** | -324 | +256 | 55% | -33 |
| **2026-04** | 20 | **+198** | +227 | **+0.53%** | **+22.7%** | -85 | **+513** | 20% | +171 |
| **2026-05*** | 7 | **+235** | +326 | **+0.57%** | +7.6% | -203 | +406 | 14% | +214 |

\* `ret%` for 2026-05 is the partial-month return through 2026-05-12 (vs the 2026-04 close);
2026-05's basis figures are likewise month-to-date (7 trading days), and the -203 is the latest
single day (2026-05-12), the *first* backwardation day of the month.

### Yearly summary

| Year | days | mean basis (pts) | mean basis (%) | days backwardated |
|---|--:|--:|--:|--:|
| 2020 | 245 | −42.7 | −0.37 % | 85 % |
| 2021 | 244 | −26.6 | −0.16 % | 74 % |
| 2022 | 246 | −45.2 | −0.29 % | 83 % |
| 2023 | 239 | −15.3 | −0.09 % | 61 % |
| 2024 | 242 | **+14.0** | **+0.06 %** | 38 % |
| 2025 | 243 | −16.1 | −0.09 % | 54 % |
| **2026 YTD** | 82 | **+110.5** | **+0.31 %** | **24 %** |

**Reading the table.** 2020‑2023 were "backwardation‑normal" — TX traded *below* spot
70‑90 % of days, average −15 to −45 pts, with predictable seasonal deepening in Jun‑Aug and
crisis spikes (COVID Mar‑2020: −328 single day; the 2022 bear: −167 monthly mean in
Jun‑2022, −441 single day). 2024 flipped to *contango* for the first time as the AI boom
took TAIEX from ~17 600 to ~23 000 (the Aug‑2024 yen‑carry crash punched a one‑day −457 hole
that snapped straight back). 2025 H1 was a deep‑backwardation scare (tariff turmoil: Apr −55,
May −70, **Jun −173**, Jul −70 monthly means) that resolved into a melt‑up in H2 (Oct +61,
Nov +53, Dec +70). 2026 YTD is the *most contango on record*: +110 pts average, only 24 % of
days below spot, **April +198 / May +235 monthly means, with a +513 pt single‑day peak on
2026‑04‑16** — futures running ~1 % *above* spot for weeks on retail euphoria. The −203 on
2026‑05‑12 is the first crack in that.

---

## 3. Seasonal baseline — where the dividend season actually is

Mean ± std of each calendar month's monthly‑mean basis over the completed prior years
2020‑2025 (`data/research/basis_seasonal_baseline.csv`). The whole partial 2026 is excluded
so every row uses the same six‑year window:

| Cal‑month | n yrs | seasonal mean basis | ± std | min | max | resid mean |
|---|--:|--:|--:|--:|--:|--:|
| Jan | 6 | +1 | 25 | −21 | +48 | −8 |
| Feb | 6 | −10 | 16 | −24 | +15 | −20 |
| Mar | 6 | −26 | 35 | −80 | +21 | −36 |
| Apr | 6 | −13 | 36 | −55 | +47 | −23 |
| May | 6 | **−24** | **39** | −70 | +47 | −34 |
| **Jun** | 6 | **−87** | 66 | **−173** | −23 | **−97** |
| **Jul** | 6 | **−58** | 37 | −96 | +3 | **−69** |
| **Aug** | 6 | **−45** | 16 | −62 | −24 | **−55** |
| Sep | 6 | −13 | 17 | −37 | +3 | −23 |
| Oct | 6 | +11 | 40 | −36 | +61 | −1 |
| Nov | 6 | +10 | 29 | −28 | +53 | −1 |
| Dec | 6 | +1 | 41 | −38 | +70 | −11 |

The data‑driven ex‑dividend trough is the **contiguous block around the seasonal minimum
(June): Jun (−87) → Jul (−58) → Aug (−45)** — a clean three‑month dip, each month at least
half as negative as the June trough. (The literal "four lowest" months are Mar, Jun, Jul,
Aug, but March's −26 is not a dividend effect: that cell is dominated by the COVID March of
2020, −80, and the bear March of 2022, −41; its neighbours Feb −10 and Apr −13 are normal,
so March is an isolated crisis cell, not part of any seasonal block.) **May (−24) is the
*shoulder* of the ex‑dividend season, not its core** — its seasonal basis is no deeper than
March's and roughly a third of June's. Taiwan's ex‑dividend dates cluster Jun‑Sep; the cash
index shedding those points is overwhelmingly a *summer* phenomenon. So a deep May
backwardation is **not** the "structural 除權息逆價差" the commentary invokes — that argument
applies to Jun‑Aug (and to the deferred contracts; see §4).

---

## 4. Decomposing the current ≈ −200 pt basis (2026‑05‑12)

TAIEX close 41 898, TX (May contract, day session) close 41 695 → **basis −203 pts**;
8 calendar days to the May‑20 settlement.

| Component | Estimate | Basis |
|---|--:|---|
| Theoretical interest carry (r ≈ 1.5‑2.0 %, T = 8 d, S ≈ 41 900) | **≈ +14 to +18 pts** | `S·r·T/365`; would put F *above* S |
| Expected dividend points realised before 2026‑05‑20 | **≈ −10 to −30 pts** | May ex‑div is light; the bulk lands Jun‑Aug |
| ⇒ "Fair‑value" front‑month basis on 2026‑05‑12 | **≈ −6 to +5 pts (≈ flat)** | carry minus the small May dividend accrual |
| **Observed** | **−203 pts** | |
| ⇒ **Residual = positioning / hedging premium** | **≈ −190 to −210 pts** | the "real 逆價差" — almost the entire print |

So the screenshot is right that, *for this one day*, the "扣掉除息點數後的實質逆價差" is large
— roughly **−200 pts of pure positioning**. Where it overstates the case:

1. **It is one day.** The 20‑day‑smoothed basis is still **+269 pts** — the 99th percentile
   of all daily readings in six years. The prevailing 2026 regime is the *opposite* of fear.
2. **The move is a mean‑reversion of an over‑extended bull contango, not a fresh fear
   build‑up.** TX had been printing +300 to +513 pts (≈ +0.7 % to +1.4 %) above spot for two
   months — the textbook signature of the retail long‑futures crowd over‑paying. The basis
   collapsed **−358 pts in one day / −610 pts in three days** into May‑12 — the *fastest
   basis collapse in the entire 2020‑2026 sample* (0th percentile on the 1‑, 3‑, 5‑ and
   10‑day change). That is what an over‑levered long‑futures position getting de‑risked /
   squeezed looks like, and it routinely overshoots through zero in a single session.
3. **The forward curve is not screaming "dividend".** On 2026‑05‑12 the TX curve was
   *upward*‑sloping past the front: May 41 695 (−203 vs spot), Jun 41 818 (−80), Jul 41 850
   (−48), Sep 42 084 (+186), Dec 42 453 (+555). A pure near‑month‑dividend story would leave
   the deferred months below spot too; instead the discount is local to the front month — an
   idiosyncratic squeeze, not a systematic carry/dividend feature.
4. **Statistically, −203 in May is at the extreme, but it has happened.** Versus all 126
   prior May trading days (2020‑2025), the basis ranged [−210, +111] with median −17 and 5th
   percentile −128. A −203 print sits at the **~1st percentile** — the only comparable May
   day on record is the May‑2021 spike (−210). And on the *monthly* view, 2026‑05 month‑to‑
   date averages **+235 pts**, a **+6.7 σ** reading versus the May seasonal norm — but in the
   **contango** direction. So "May 2026 as a whole" is the *most bullish‑positioned May on
   record*; the −203 day is the snap‑back, not the trend.

**Bottom line on the user's binary:** the −191/−203 is **not normal dividend‑season
backwardation** (wrong month for that), and it **is** a real, extreme negative basis print —
but it currently reads as a **one‑day positioning flush off an euphoric high**, not a
confirmed regime shift to "法人 hedging has taken over." A real bear regime shows up as the
basis staying negative for *weeks to months* (Jun 2022 ran −167 *monthly mean*; 2025 H1 ran
negative Apr→Aug). One −200 day inside a +270‑smoothed‑basis melt‑up is not that — yet.

---

## 5. Does the basis predict anything? (light in‑sample check)

Using a **seasonally‑adjusted** basis (raw basis minus its calendar‑month mean, so the
dividend cycle is removed) and z‑scoring it against a trailing 1‑year window:

| Condition (seasonally‑adjusted basis) | n days | mean TAIEX return over next 20 trading days |
|---|--:|--:|
| ≥ 1 σ **LOW** (unusually backwardated for the season) | 150 | **+3.1 %** |
| within ±1 σ | 1 071 | +1.8 % |
| ≥ 1 σ **HIGH** (unusually rich for the season) | 241 | +1.9 % |

`corr(seasonally‑adjusted basis z, fwd‑20d return) = −0.025` — essentially zero, and the
*sign* is the opposite of "backwardation ⇒ weakness." In this 2020‑2026 sample every deep
ex‑dividend backwardation episode (COVID Mar‑2020, yen‑carry Aug‑2024, tariff Apr/Jun‑2025)
was a **local capitulation that got bought**, so a backwardated basis has, if anything, been a
*mildly contrarian‑bullish* tell, not a bearish one. The current seasonally‑adjusted basis
z‑score is **−1.86** (i.e. unusually low for May) — which on this relationship leans
contrarian‑long, not bearish. **Heavy caveat:** the sample contains no multi‑quarter bear
after 2022; in a sustained downtrend the front‑month basis stays negative for *months* (it
was negative ~9 months straight in 2022) and the contrarian read would fail. The signal is
regime‑conditioned.

---

## 6. Does the monthly basis % co-move with the monthly return %?  (the plot)

Plot: `data/research/basis_vs_return.png` (generated by `scripts/research/plot_basis_vs_return.py`):

![monthly mean basis % vs monthly TAIEX return %](../../data/research/basis_vs_return.png)

- **Left panel — same month.** `corr(monthly mean basis %, monthly TAIEX return %) = +0.32`,
  R² ≈ **0.10**, OLS slope ≈ **7** (each +1 pp of monthly mean basis % goes with ≈ +7 pp of
  that month's return). So there *is* a positive link — strong rallies push the futures into
  contango, sell-offs into backwardation — but it explains only ~10 % of the variance and is
  noisy: e.g. **2022-11 rallied +14.9 % yet the basis stayed at −0.20 %**, and **2020-04
  rallied +13.2 % with the basis still at −0.42 %** (during 2020-2022 the basis was
  *structurally* negative regardless of direction, which drags the fit down). The relationship
  only really "switches on" once the basis *level* sits in contango territory — i.e. from 2024
  onwards. 2026 is the cleanest case in the sample: +22.7 % April / +0.53 % basis, −10.4 %
  March / −0.04 % basis.
- **Middle panel — predictive.** `corr(this-month basis %, *next*-month return %) = +0.03`,
  R² ≈ 0.001 — i.e. **none**. The monthly mean basis carries essentially no standalone
  information about next month's direction (consistent with the daily-frequency finding in §5
  that, if anything, a *deep* ex-dividend-adjusted backwardation has been mildly
  contrarian-bullish, not bearish).
- **Right panel — time series.** Visually the two lines move together at the regime level
  (both step up in 2024 and again hard in late-2025/2026; both sag through the 2022 bear and
  the 2025-H1 scare) but disagree at the month-to-month level often enough that you would not
  use one to trade the other.

**Takeaway for the headline question:** the monthly basis % is a *coincident* read on
risk appetite — it co-moves with the realised move — not a *leading* indicator of it. So the
−200 pt 2026-05-12 print is best read as the futures *reacting to* the sharp two-day pullback
in the cash index (and to the unwind of the prior euphoric long-futures positioning), not as
the futures *foreseeing* a coming decline. The data does not support treating the basis flip as
a forward-looking bearish signal — see §5 and §8.

---

## 7. Limitations / what this study does **not** include

- **No open‑interest / positioning data.** The screenshot's strongest argument is "外資期貨
  淨空單在數萬口高水位." This study uses *price* basis only. The natural next pull is the TAIFEX
  大額交易人未沖銷部位 / 三大法人期貨未平倉 series (the data daemon does not currently crawl it). A −200
  pt basis *plus* a record foreign net‑short OI is a stronger story than the basis alone; a
  −200 pt basis with *flat* net OI would point to a pure squeeze/unwind. Recommend pulling OI
  before drawing a firm "法人避險" conclusion.
- **Close‑to‑close, not synchronous.** ~15‑min offset (TX 13:45 vs TAIEX 13:30); immaterial
  to monthly aggregates, but a true intraday basis (which we *can* build from `market.db`'s
  1‑min TX bars + an intraday TAIEX feed) would be cleaner for a live filter.
- **Front‑month only.** No term‑structure / weighted‑basis series; the front month carries
  roll‑decay noise (mitigated here via the carry residual and monthly aggregation).
- **r is a flat assumption.** Carry uses a constant 1.5 % (override with `--rate`); the carry
  term is tiny (~+15 pts) so this does not move the conclusion.
- **No US/JP/KR comparison.** The screenshot's "納斯達克有逆價差過嗎" aside is not addressed here —
  it would need separate index‑future feeds (CME, OSE, KRX). Happy to add if useful; the
  qualitative point in the screenshot (US = structural contango because r ≫ q; backwardation
  only in 2008/2020‑type panics) is broadly correct.

---

## 8. Recommendation — would I use this spread as a regime filter?

**Not as a *bearish* filter, no** — on this dataset "near‑month basis went negative" fires at
every local bottom of the last six years; trading it short would have been a steady loser.
What *is* defensible:

1. **As a risk (not direction) filter:** a *persistently* negative **seasonally‑adjusted**
   basis — e.g. the 20‑day mean residual more than 1 σ below its trailing‑1‑year mean for
   ≥ 3 weeks — is a reasonable "this is a genuine de‑risking regime, widen stops / cut
   pyramid leverage / shorten holding periods" flag. It would have flagged 2022 H2 and 2025
   H1 (both choppy/down) and *not* flagged the 2024 and 2026 melt‑ups. Note: the project's
   pyramid sizing is already account‑`RiskLevel`‑driven (`pyramid_config_from_risk_level` in
   `src/core/types.py`), so the natural wiring is "basis‑residual regime → suggest lowering
   `EngineConfig.pyramid_risk_level`," not a per‑strategy parameter.
2. **As a volatility signal:** a sudden one‑day basis collapse like 2026‑05‑12 (−358 pts,
   0th percentile) is a clean "vol is about to expand" tell — useful for stop‑width / position
   sizing, not for picking a side.
3. **Don't** use the raw front‑month basis without de‑seasonalising — you would systematically
   "go risk‑off" every July for no reason.
4. **Re‑evaluate if the basis stays negative.** A single −200 day reverting toward zero is the
   modal outcome in this sample. If the 20‑day‑smoothed basis flips negative and *stays* there
   for a month, that is the historical fingerprint of a real downtrend (2022) — at that point
   the contrarian read in §5 stops applying and the "法人 hedging regime" interpretation becomes
   the right one.

---

### Reproduce

```bash
uv run python scripts/research/crawl_basis_data.py        # -> data/research/taiex_tx_basis_daily.csv
uv run python scripts/research/analyze_basis.py           # -> monthly + seasonal CSVs + verdict
uv run python scripts/research/plot_basis_vs_return.py    # -> data/research/basis_vs_return.png
uv run python scripts/research/analyze_basis.py --rate 0.02   # sensitivity on the carry rate
```

Raw monthly payloads are cached under `data/research/_cache/`; complete past months are
reused, the current month is always re‑fetched, so re‑running is idempotent. Network access is
limited to `twse.com.tw` and `taifex.com.tw` with ≥ 0.7 s between requests.
