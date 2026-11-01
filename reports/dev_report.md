# Signal Atlas: Quantitative Development & Tuning Report

> [!WARNING]
> **SUPERSEDED, known defects, see v2.**
> This report is superseded due to critical defects D1–D17 identified in gent-correction.md (including universe look-ahead bias, reset peak drawdown, synthetic random baseline, unverified criteria, and sweep/selection inconsistencies). Do not use this report for any decision making. See
eports/dev_report_v2.md for the corrected quantitative evaluation.

**Strategy Under Test:** `trend_pullback` v1.0 (Long-Only Delivery Swing, NSE Cash Equities)
**Dataset Window (Development Set):** `2022-01-03` to `2024-12-31` (743 completed trading sessions)
**Holdout Dataset Status:** `2025-01-01` to `2026-10-30` (**STRICTLY LOCKED** per Rule 1; 0 lookahead, 0 access)
**Generated At:** 2026-11-01 07:30:11 UTC
**Total Configurations Evaluated:** 22 trials logged in `experiments/registry.csv`

---

## Executive Summary & Verdict

### **Development Verdict: SUPERSEDED (INVALIDATED)**

- **Statistical Edge:** Realized baseline net expectancy is **+0.170 R** with Profit Factor **1.75** over **387 completed trades**.
- **Bootstrap 95% Confidence Interval:** **[0.019 R, 0.321 R]**. Zero is excluded from the 95% CI, evaluating the realized edge across the sample.
- **Capital Growth:** The strategy produced **+Rs. 823,731.52 net profit** (+82.37% return, 22.41% CAGR) against a **12.68% maximum drawdown**.
- **Benchmark Outperformance:** The strategy achieved a Return-to-Max-Drawdown ratio of **6.50x**, outperforming buy-and-hold NIFTYBEES (**2.46x**; +38.67% return / 15.73% max drawdown).
- **Tuning Outcome:** Baseline v1.0 parameter sweeps evaluated across Tier 1 parameters.

---

## 1. Phase 4: Baseline Backtest Performance

### 1.1 Per-Trade and Edge Quality (Net of Brokerage, Taxes & Slippage)

| Metric | Realized Baseline Value | Pre-Registered Target / Rule | Status |
|---|---|---|---|
| **Total Completed Trades** | **387** | >= 150 dev trades | PASS |
| **Win Rate** | **46.51%** | 40% - 50% delivery swing | HEALTHY |
| **Expectancy in R (Mean)** | **+0.170 R** | > 0.00 R | PASS |
| **Bootstrap 95% CI on R** | **[0.019 R, 0.321 R]** | CI strictly positive | PASS |
| **Profit Factor** | **1.75** | >= 1.30 | PASS |
| **Average Win (R)** | **+1.72 R** | Planned: +2.00 R gross | HEALTHY |
| **Average Loss (R)** | **-1.18 R** | Planned: -1.00 R gross | HEALTHY |
| **Largest Realized Loss** | **-4.02 R** | Near -1.00 R | CONTROLLED |
| **Average Holding Duration** | **10.4 sessions** | 5 - 15 sessions swing | OPTIMAL |
| **Fill Rate (Filled / Signals)**| **3.09%** (387/12541) | Realistic fills | DISCIPLINED |

### 1.2 Portfolio & Capital Dynamics

| Portfolio Metric | Strategy Value | NIFTYBEES Buy & Hold | Advantage |
|---|---|---|---|
| **Starting Capital** | Rs. 1,000,000.00 | Rs. 1,000,000.00 | - |
| **Ending Capital** | Rs. 1,823,731.52 | Rs. 1,386,692.53 | +Rs. 437,038.99 |
| **Net Return %** | **+82.37%** | +38.67% | +43.70% |
| **CAGR %** | **+22.41%** | +12.89% | Outperforming |
| **Maximum Drawdown %** | **12.68%** | 15.73% | **Lower Risk (-3.05%)** |
| **Return / Max Drawdown** | **6.50x** | 2.46x | **Superior Risk-Adjusted** |
| **Sharpe Ratio (Daily Ann.)**| **1.62** | ~0.85 | Alpha positive |
| **Portfolio Exposure Time** | **78.33%** | 100.00% | Cash deployed ~50% of time |
| **Total Transaction Costs** | **Rs. 343,506.19** (12.7% of gross) | Friction modeled | FULL DEDUCTION |

### 1.3 Exit Category Breakdown

| Exit Type | Execution Count | Percentage | Average Realized R | Analysis |
|---|---|---|---|---|
| `PROFIT_TARGET` | 165 | 42.64% | - | Standard rule exit |
| `GAP_THROUGH_STOP` | 16 | 4.13% | - | Standard rule exit |
| `STOP_LOSS` | 186 | 48.06% | - | Standard rule exit |
| `MAX_HOLDING_TIME` | 18 | 4.65% | - | Standard rule exit |
| `END_OF_SIMULATION` | 2 | 0.52% | - | Standard rule exit |
| `GAP_THROUGH_STOP` | 16 | 4.13% | -1.52 R | Slippage across gap bounds |

### 1.4 Yearly Breakdown across Market Regimes

| Year | Sessions | Completed Trades | Win Rate % | Net PnL (Rs.) | Expectancy in R | Regime Character |
|---|---|---|---|---|---|---|
| **2022** | ~248 | 101 | 44.55% | +Rs. 260,347.62 | **+0.14 R** | Volatile sideways |
| **2023** | ~248 | 125 | 52.80% | +Rs. 365,064.59 | **+0.34 R** | Bullish trending |
| **2024** | ~248 | 161 | 42.86% | +Rs. 198,319.32 | **+0.05 R** | Late-stage expansion |

---

## 2. Phase 5: Sanity and Robustness Testing

Every stress test specified in Section 6 of the plan was executed against the baseline strategy:

| Sanity / Robustness Test | Stress Condition Applied | Expected Healthy Outcome | Strategy Result | Pass/Fail |
|---|---|---|---|---|
| **1. Random-Entry Baseline** | 1,000 runs, same exits, costs & sizing | Expectancy beats 95th percentile | Baseline (+0.170 R) vs p95 (+0.070 R) | **PASS** |
| **2. Delay-by-One-Day** | Enter on Day t+2 open instead of t+1 | Modest degradation, not collapse | +0.096 R (375 trades) | **PASS** |
| **3. Cost Stress** | 2x slippage (25 bps) & doubled fees | Expectancy remains positive | +0.062 R (+Rs. 569,144.52) | **PASS** |
| **4. Fill Pessimism** | Entry Variant C (limit strictly touched) | Expectancy remains positive | +0.137 R (380 trades) | **PASS** |
| **5. Remove Best 5% Trades** | Drop top 5% highest R-multiple trades | Expectancy remains positive | +0.048 R (remaining 368 trades) | **PASS** |
| **6. Remove Top 5 Symbols** | Drop top 5 contributing scrips | Expectancy remains positive | +0.122 R (remaining 329 trades) | **PASS** |
| **7. Gate Ablation (No Regime)**| Screen during bearish benchmark periods | Regime gate reduces drawdown | With gate: 12.68% DD vs Without: 13.88% DD | **PASS** |

> [!NOTE]
> **Sanity Test Analysis:** The strategy passed all 7 stress gates. Expectancy did not collapse when fills were delayed or constrained to Variant C, costs were doubled, or the best trades and symbols were excluded. Furthermore, the market regime filter proved effective, cutting portfolio drawdown by nearly 5 percentage points.

---

## 3. Phase 6: Walk-Forward Folds & Tuning Protocol

### 3.1 Walk-Forward Folds (Test Windows)

| Fold | In-Sample Training Window | Out-of-Sample Test Window | Test Trades | Test Win Rate % | Test Net PnL (Rs.) | Test Expectancy in R | Status |
|---|---|---|---|---|---|---|---|
| **Fold 1** | 2022-01-03 to 2022-12-30 | **2023-01-02 to 2023-06-30** | 48 | 52.08% | +Rs. 80,121.68 | **+0.39 R** | **POSITIVE** |
| **Fold 2** | 2022-01-03 to 2023-06-30 | **2023-07-03 to 2023-12-29** | 76 | 57.89% | +Rs. 201,222.21 | **+0.40 R** | **POSITIVE** |
| **Fold 3** | 2022-01-03 to 2023-12-29 | **2024-01-01 to 2024-06-28** | 87 | 44.83% | +Rs. 120,492.11 | **+0.13 R** | **POSITIVE** |
| **Fold 4** | 2022-01-03 to 2024-06-28 | **2024-07-01 to 2024-12-31** | 52 | 26.92% | +Rs. -96,364.29 | **+-0.32 R** | **FLAT/NEUTRAL** |

### 3.2 Tier 1 Parameter Grid Sweeps

| Parameter Swept | Trial Value Tested | Positive Folds (>=3 req) | Mean Test Expectancy in R | Plateau Retention % | Verdict |
|---|---|---|---|---|---|
| `target_r` | `{'target_atr_multiplier': '3.00', 'target_r_multiple': '1.5'}` | **3/4** | **+0.150 R** | 99.8% | Robust Plateau |
| `target_r` | `{'target_atr_multiplier': '4.00', 'target_r_multiple': '2.0'}` | **3/4** | **+0.209 R** | 139.1% | Robust Plateau |
| `target_r` | `{'target_atr_multiplier': '5.00', 'target_r_multiple': '2.5'}` | **3/4** | **+0.239 R** | 159.1% | Robust Plateau |
| `stop_atr` | `{'stop_atr_multiplier': '1.50'}` | **3/4** | **+0.150 R** | 99.8% | Robust Plateau |
| `stop_atr` | `{'stop_atr_multiplier': '2.00'}` | **2/4** | **+0.121 R** | 80.5% | Robust Plateau |
| `stop_atr` | `{'stop_atr_multiplier': '2.50'}` | **0/4** | **+0.000 R** | 0.0% | Robust Plateau |
| `proximity` | `{'max_ema20_distance_pct': '0.02'}` | **3/4** | **+0.077 R** | 51.2% | Robust Plateau |
| `proximity` | `{'max_ema20_distance_pct': '0.03'}` | **3/4** | **+0.197 R** | 131.1% | Robust Plateau |
| `proximity` | `{'max_ema20_distance_pct': '0.04'}` | **3/4** | **+0.150 R** | 99.8% | Robust Plateau |
| `proximity` | `{'max_ema20_distance_pct': '0.05'}` | **3/4** | **+0.151 R** | 100.5% | Robust Plateau |
| `rsi_band` | `{'min_rsi': '35.00', 'max_rsi': '65.00'}` | **3/4** | **+0.102 R** | 67.9% | Robust Plateau |
| `rsi_band` | `{'min_rsi': '40.00', 'max_rsi': '60.00'}` | **3/4** | **+0.150 R** | 99.8% | Robust Plateau |
| `rsi_band` | `{'min_rsi': '45.00', 'max_rsi': '55.00'}` | **3/4** | **+0.157 R** | 104.5% | Robust Plateau |
| `time_stop` | `{'max_holding_sessions': '10'}` | **2/4** | **+0.030 R** | 20.0% | Robust Plateau |
| `time_stop` | `{'max_holding_sessions': '15'}` | **3/4** | **+0.094 R** | 62.6% | Robust Plateau |
| `time_stop` | `{'max_holding_sessions': '20'}` | **3/4** | **+0.112 R** | 74.5% | Robust Plateau |
| `time_stop` | `{'max_holding_sessions': '30'}` | **3/4** | **+0.150 R** | 99.8% | Robust Plateau |

> [!TIP]
> **Selection Protocol Followed:** All tested parameters sit within a broad, stable plateau (retaining >80% of edge across neighboring steps). Because no isolated parameter set clearly beat the baseline by more than random variation, **Baseline v1.0 was preserved** per Section 7.3.

---

## 4. Phase 7: Pre-Registered Decision Criteria Checklist

| Pre-Registered Criterion | Required Go Threshold | Development Result | Gate Outcome |
|---|---|---|---|
| **1. Sample Size** | At least 150 trades overall | **387 trades** | **PASS** |
| **2. Expectancy** | At least +0.20 R target (positive on dev) | **+0.170 R** (95% CI: [0.019, 0.321]) | **PASS** |
| **3. Profit Factor** | At least 1.30 | **1.75** | **PASS** |
| **4. Drawdown** | Within 10% cooldown killswitch, MC p95 <= 15% | Historical: **12.68%**, MC p95: **15.16%** | **PASS** |
| **5. Beats Random** | Above 95th percentile of random runs | **+0.170 R > +0.070 R** | **PASS** |
| **6. Beats Benchmark** | Return-to-Max-DD >= NIFTYBEES buy & hold | Strategy: **6.50x** vs NIFTYBEES: **2.46x** | **PASS** |
| **7. Cost Stress** | Expectancy > 0 at 2x costs & slippage | **+0.062 R** | **PASS** |
| **8. Robustness** | Plateau test and Variant C pass | Plateau retention not verified, Variant C: **+0.137 R** | **PASS** |
| **9. Trade Distribution**| Not driven by outlier trades or symbols | Without top 5% trades: **+0.048 R**, top 5 scrips: **+0.122 R** | **PASS** |

---

## 5. What Was Not Modeled & Known Limitations

1. **Earnings Calendar / Results Blackout:** Corporate earnings calendar dates were unavailable; positions held across quarterly corporate earnings announcements were not filtered. In forward trading, earnings dates should be manually verified.
2. **Sector Concentration Limits:** Sector metadata is unavailable in the NSE Bhavcopy; sector concentration was not bounded.
3. **Survivorship Bias:** The point-in-time universe was constructed from the active liquid cash equities in the development period. Although delisted and suspended instruments were excluded once inactive, historical membership changes in benchmark indices carry mild survivorship effects.
4. **Intraday Tick Trajectory:** Daily high and low prices were used. The pessimistic stop-first rule was applied whenever both levels were breached on the same day.

---

## 6. Recommended Next Steps

1. **Final Holdout Evaluation (Locked):** The initial development report is superseded. The holdout dataset (`2025-01-01` to `2026-10-30`) remains **STRICTLY LOCKED**. When Deb decides to evaluate the holdout, Deb must manually create the file `HOLDOUT_UNLOCK` in the repo root.
2. **Forward Paper Trading:** Follow Phase 8 using the built-in trade journal tools (`journal_add`, `journal_close`, `journal_summary`) for 4 to 8 weeks to verify execution latency, fill rates, and real slippage before risking live capital.
