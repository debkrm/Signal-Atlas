# Known Technical Gaps & Definitive NO-GO Decision

**Document Version:** 1.0.0  
**Status:** Canonical Decision & Closure Document  
**Current Strategic Decision:** **STRICT NO-GO FOR STRATEGY PAPER TRADING**

---

## 1. Executive Summary & Definitive Decision

Based on the quantitative evidence, rigorous mathematical reconciliation, and robustness audits completed across the Reliability Review Bundle and repository:

> ### **DEFINITIVE VERDICT: NO-GO FOR STRATEGY PAPER TRADING**
> **Under no circumstances should the Trend-Pullback Strategy be deployed for paper trading, capital allocation, broker execution, or interpreted as actionable buy/sell instructions.**
> 
> **The holdout dataset (`2025-01-01` to `2026-10-30`) remains strictly sealed and unaccessed. The file `HOLDOUT_UNLOCK` has NOT been created.**

---

## 2. Empirical Grounds for NO-GO Decision

The strategy fails all primary quantitative viability gates established in `configs/go_no_go_criteria.yaml` and `backtest_and_tuning_plan.md`:

| Acceptance Criterion | Pre-Declared Threshold | Observed Strategy Result (84-Trade Clean Baseline) | Verdict |
|---|---|---|---|
| **Trade Sample Size** | $\ge 200$ completed trades | **84 trades** across 3 years | **FAIL** |
| **Out-of-Fold Expectancy** | $\bar{R} \ge +0.20 \text{ R}$ | **-0.106 R** (Negative Expectancy) | **FAIL** |
| **Statistical Significance** | 95% Bootstrap CI strictly $> 0.00 \text{ R}$ | **[-0.312 R, +0.108 R]** (Includes zero) | **FAIL** |
| **Random-Entry Benchmark** | $\bar{R} > 95^{\text{th}}$ percentile of random entries | Strategy: **-0.106 R** vs Random p95: **+0.071 R** | **FAIL** |
| **Parameter Plateau Stability** | Candidate plateau metric $> 0$ with $\ge 4$ neighbours | All 6 tuning grid candidates rejected (Candidate 5: plateau fail, Candidate 3: consistency fail) | **FAIL** |
| **Max Portfolio Drawdown** | $\le 10.0\%$ peak-to-trough | **13.42% drawdown** in February 2023 | **FAIL** |
| **Killswitch Resilience** | Strategy recovers from drawdown | **Permanent lockout:** Portfolio remained in `COOLDOWN` for 22 months post-Feb 2023 | **FAIL** |

---

## 3. Known Technical Gaps & Limitations

While the quantitative backtest, test suite, and provenance tracking have been brought to an auditable and reproducible state, the following technical limitations remain open:

1. **Stale Historical Ledgers:**
   - The older 117-trade unclipped baseline has no surviving machine-readable ledger in the repository (`LEDGER_NOT_AVAILABLE`).
   - The original v1 387-trade run cannot be re-simulated identically without rolling back to Git commit `3ce33ab` on an unmigrated database schema.
2. **Postgres Full Table Hashing Latency:**
   - Streaming and hashing 1.85 million raw price rows during live integration tests on PostgreSQL requires ~90 seconds per test. While fast in CI on a fresh database (~6 seconds), local integration test execution against populated development databases requires patience or selective test running.
3. **NSE Top 100 Scope:**
   - Universe reconstruction is limited to the top 100 liquid equities by 20-day trailing ADTV. Extrapolation of edge to mid-cap or small-cap equities is not supported.
4. **Statutory Tax Modelling:**
   - The reported 20% Short Term Capital Gains (STCG) post-tax metric is illustrative and assumes immediate annual loss offset without modelling carry-forward business loss provisions, advance tax payment schedules, or corporate tax slabs.

---

## 4. Scoping of Potential Future System QA (Non-Trading)

If authorized separately by the system owner in a future phase:
- A narrowly scoped **Shadow-Mode System QA** exercise may be conducted strictly to test:
  1. Real-time EOD bhavcopy ingestion scheduling;
  2. Data pipeline latency and calendar holiday parsing;
  3. Signal generation timestamps and logging plumbing;
  4. Web dashboard rendering and trade journal database tables.
- **Strict Boundary:** This QA mode must be **read-only** with respect to broker APIs, must place **zero live or paper orders**, and must **never** be used to claim strategy profitability or bypass the NO-GO gate.

---

## 5. Verification Affirmation

- **Holdout Status:** UNTOUCHED & VIRGIN.
- **Production DB State:** UNTOUCHED (zero writes to `signal_atlas`).
- **Strategy Code:** UNALTERED (no curve-fitting, no indicators added, no parameter changes).
- **Final Decision:** **NO-GO FOR STRATEGY PAPER TRADING.**
