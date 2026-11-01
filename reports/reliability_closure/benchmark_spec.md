# Benchmark Specification: Matched Random-Entry Control

**Document Version:** 1.0.0  
**Status:** Canonical Reference & Specification  
**Scope:** Signal Atlas Quantitative Validation & Hypothesis Testing

---

## 1. Objective & Hypothesis

The purpose of the benchmark comparison is to test the null hypothesis ($H_0$):
> **Null Hypothesis ($H_0$):** The strategy's technical entry criteria (trend-pullback, EMA alignments, RSI bounds, and ADTV ranking) provide no predictive edge over picking an arbitrary liquid stock on the same day, given identical exit geometry, position sizing, capital constraints, and transaction friction.

To reject $H_0$ and claim an **entry edge**, the strategy must achieve an expectancy in R ($\bar{R}_{strategy}$) exceeding the 95th percentile of the matched random-entry distribution ($\bar{R}_{p95}$):
$$\text{Entry Edge Gate:} \quad \bar{R}_{strategy} > \bar{R}_{p95, random}$$

---

## 2. Specification of Matched Controls

To guarantee an apples-to-apples comparison, the control simulation holds every operational, portfolio, and friction variable constant, isolating the symbol selection mechanism:

| Dimension | Strategy | Matched Random Control | Controlled Variable Justification |
|---|---|---|---|
| **Entry Timing** | Strategy signal trigger date $t$, filled at session $t+1$ Open | Identical session $t+1$ Open on dates where strategy entered | Controls for calendar timing, macro market regime, and market-wide beta trends |
| **Eligible Universe** | Point-in-Time Top 100 liquid equities on date $t$ | Identical Point-in-Time Top 100 liquid equities on date $t$ | Eliminates survivorship bias and uninvestable small-cap distortions |
| **Symbol Selection** | Top-ranked candidate by ADTV & RSI | Uniformly sampled random draw from eligible PIT universe | Isolates pure stock-picking skill |
| **Stop Geometry** | $1.5 \times ATR_{14}$ trailing from entry price | $1.5 \times ATR_{14}$ trailing from entry price of chosen stock | Eliminates asymmetric risk/reward artifacts |
| **Target Geometry** | $2.0 \times R$ ($2.0 \times 1.5 ATR_{14} = 3.0 ATR_{14}$) | $2.0 \times R$ ($2.0 \times 1.5 ATR_{14} = 3.0 ATR_{14}$) | Ensures identical payoff geometry (2:1 R:R) |
| **Max Holding Period**| 30 trading sessions | 30 trading sessions | Controls for market drift / equity risk premium over time |
| **Position Sizing** | 1% current equity risk, capped at 20% capital & 2% ADTV | 1% current equity risk, capped at 20% capital & 2% ADTV | Ensures identical portfolio risk weighting and liquidity sizing |
| **Open Risk Cap** | Max 6% total open risk | Max 6% total open risk | Enforces identical portfolio risk concentration limits |
| **Max Concurrency** | Max 10 simultaneous positions | Max 10 simultaneous positions | Enforces identical diversification constraints |
| **Transaction Costs**| STT (10 bps), Exchange (2.97 bps), SEBI, GST, Stamp (15 bps), DP (₹15.93) | Identical full Indian statutory & brokerage cost model | Prevents cost-underestimation bias |
| **Slippage** | 10 bps on Open price entry and exit | 10 bps on Open price entry and exit | Enforces realistic market execution friction |
| **Exit Precedence** | Gap-down open < Stop $\to$ Fill at Open. High $\ge$ Target & Low $\le$ Stop $\to$ Stop first | Identical conservative exit precedence | Eliminates optimistic intraday execution assumptions |

---

## 3. Legacy Benchmark vs. Matched Control Discrepancy

The historical random-entry benchmark contained the following critical methodological flaws:
1. **Fixed Percentage Stops vs. Volatility Stops:** The legacy implementation used a fixed 3.0% stop and 6.0% target instead of the strategy's volatility-based $1.5 \times ATR_{14}$ stop.
2. **Absence of Portfolio Risk Constraints:** The legacy generator simulated independent single-trade bets rather than a constrained portfolio with cash limits, 6% open risk caps, and 10-position concurrency ceilings.
3. **Synthetic Unit Test Invariant:** The existing unit test (`test_random_entry_zero_drift_sanity`) merely validated a zero-drift synthetic random-walk array, failing to test the actual backtest execution engine or market data feed.

**Remediation:**
- Historical results are preserved and explicitly labelled `LEGACY_NON_MATCHED`.
- A fully matched random generator (`generate_matched_random_baseline`) runs through the unified `BacktestEngine` with identical configurations.
- Deterministic random seeds (`seed=42`, `runs=200`) guarantee full reproducibility.

---

## 4. Statistical Resampling & Uncertainty Estimation

To evaluate distribution characteristics:
1. **Resampling Unit:** Calendar-month block bootstrap ($B = 1,000$ iterations) is employed to preserve temporal autocorrelation and cross-sectional volatility clustering.
2. **Confidence Intervals:** 95% bootstrap intervals are constructed via the empirical percentile method ($2.5^{\text{th}}$ and $97.5^{\text{th}}$ percentiles).
3. **Paired Difference Analysis:** For each bootstrap iteration $b$:
   $$\Delta \bar{R}_b = \bar{R}_{strategy, b} - \bar{R}_{control, b}$$
   If the lower bound of the 95% CI of $\Delta \bar{R}$ is $\le 0$, the entry edge is deemed statistically indistinguishable from noise.

---

## 5. Current Strategy Evaluation

Under the clean 84-trade v2 baseline:
- Strategy Mean Expectancy: **-0.106 R**
- Matched Random 95th Percentile: **+0.071 R**
- Verdict: **FAIL (Definitive NO-GO)**. Strategy does not demonstrate an entry edge over random selection.
