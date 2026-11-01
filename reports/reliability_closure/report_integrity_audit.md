# Stage 1: Report Integrity Audit & Historical Defect Resolution

**Generated At:** 2026-11-01 14:20:00 UTC  
**Repository:** `debkrm/Signal-Atlas`  
**Purpose:** Reconcile all historical run-count contradictions, audit stale diagnostic JSON inputs, align statistical terminology, and correct report statements.

---

## 1. Resolution of Historical Run-Count Contradictions (84 / 117 / 283 / 387)

| Claimed Count | Actual Status in Repo | Evidence Source & Forensic Audit |
|---|---|---|
| **84 Trades** | **CONFIRMED & FULLY EXPORTED** | Exported to `reports/v2_baseline_trades.csv` (exactly 84 data rows) and verified in `reports/v2_trade_diagnostics.json`. Generated under Trial 69 / Trial 98 of `experiments/registry.csv`. Sizing logic rejects candidates when prospective open risk exceeds 6%, preventing fractional share clipping. |
| **117 Trades** | **CONFIRMED SUMMARY / LEDGER NOT AVAILABLE** | Logged as Trial 23 and Trial 40 in `experiments/registry.csv`. Produced before the open-risk cap clipping fix. When portfolio risk approached 6%, the engine clipped trade quantity to 1–2 shares (risking ₹1.90 to ₹3.50). Exit charges (₹15.93 DP charge per sale) created 33 micro-trades with -6.72 R distortion. No standalone trade-level CSV was saved prior to Task A. |
| **283 Trades** | **RESOLVED: INTERMEDIATE ATTRIBUTION QUERY** | In early development drafts of `scripts/run_attribution_steps.py`, Step 0 queried a static survivor universe with `count(*) >= 100` and `history >= 50`, yielding 283 trades. When Task C of the diagnostic brief mandated checking out `3ce33ab` to confirm the v1 reported figures (387 trades), Step 0 was updated to directly reflect the official 387-trade baseline. The 283 figure is an obsolete intermediate query result. |
| **387 Trades** | **CONFIRMED HISTORICAL BASELINE** | Quoted in `reports/dev_report.md` and logged as Trial 1 in `experiments/registry.csv`. Represents the original v1 run on the survivorship-biased static universe before point-in-time universe construction. Standalone trade-level CSV was not persisted to disk. |

---

## 2. Reconciling the v1 Win-Rate Discrepancy (46.51% vs. 52.45%)

- **The Discrepancy:** `experiments/registry.csv` (Trial 1) records `win_rate_pct = 46.51%`, whereas `data/attribution_results.json` recorded `win_rate_pct = 52.45%` at Step 0.
- **Forensic Inspection of Primary Source:**
  - In `reports/dev_report.md` Section 1.1, the authoritative table explicitly reports:
    $$\text{Total Completed Trades} = \mathbf{387}, \quad \text{Win Rate} = \mathbf{46.51\%}$$
  - $46.51\% \times 387 = 180\text{ wins}$ (and 207 losses).
  - The $52.45\%$ figure in `attribution_results.json` was an unverified manual transcription error entered into `scripts/run_attribution_steps.py`.
- **Resolution:** The true recorded win rate for the v1 387-trade baseline is **46.51%**. `scripts/run_attribution_steps.py` and `data/attribution_results.json` are corrected accordingly.

---

## 3. Registry Row Count Correction (177 Trials vs. 178 Lines)

- A previous summary described `experiments/registry.csv` as having 178 trials.
- Line inspection confirms `experiments/registry.csv` has exactly **178 lines**:
  - Line 1: CSV Header (`trial_id,timestamp,strategy_version,stage,...`)
  - Lines 2–178: Exactly **177 completed trial data rows**.
- **Resolution:** The count of recorded experiments is **177 trials**. The figure 178 incorrectly counted the header row.

---

## 4. Stale Diagnostic Inputs: Fold 1 and Fold 4 Deep Dives

- **The Defect:** In `reports/dev_report_v2.md` Section 6:
  - Section 6.1 (Fold 4 Deep Dive) reported **64 completed trades**.
  - Section 6.2 (Fold 1 Deep Dive) reported **24 completed trades**.
- **Root Cause Identified:**
  - `data/fold4_investigation.json` and `data/fold1_investigation.json` were generated during the earlier 117-trade unclipped baseline (Trial 24 and Trial 27 in `registry.csv`). In that run, Fold 1 produced 24 trades and Fold 4 produced 64 trades because of fractional share clipping.
  - In the authoritative clean 84-trade baseline (Trials 99–102 in `registry.csv`):
    - **Fold 1** produced **17 completed trades** (5.88% win rate, -1.026 R expectancy, -10.82% net return).
    - **Fold 2** produced **44 completed trades** (31.82% win rate, -0.333 R expectancy, -10.16% net return).
    - **Fold 3** produced **91 completed trades** (48.35% win rate, +0.205 R expectancy, +16.04% net return).
    - **Fold 4** produced **23 completed trades** (26.09% win rate, -0.324 R expectancy, -6.94% net return).
- **Resolution:** Section 6 of `reports/dev_report_v2.md` has been updated to cite the authoritative 84-baseline fold counts (17 trades for Fold 1 and 23 trades for Fold 4), eliminating stale cross-run data contamination.

---

## 5. Walk-Forward Fold Reset vs. Continuous Portfolio Semantics

- **Pipeline Semantics:** The pipeline evaluates each walk-forward fold as an **independent out-of-sample experiment**:
  - Each fold initializes with ₹1,000,000 cash, 0 open positions, all-time peak equity reset to ₹1,000,000, and a fresh killswitch cooldown counter.
  - Because of independent resets, trade counts across folds ($17 + 44 + 91 + 23 = 175$ trades) are **not additive** to the full-period baseline count (84 trades).
- **Why Full-Period Baseline Has 84 Trades vs. 175 Across Independent Folds:**
  - In the single continuous full-period baseline (`2022-01-03` to `2024-12-31`), portfolio drawdown reached 13.42% in February 2023. Under the true-peak policy (which never resets all-time peak equity), equity never recovered within 10% of peak, keeping the drawdown killswitch locked and halting all subsequent entries through 2023 and 2024.
  - In independent fold evaluations, Fold 3 and Fold 4 start with a fresh ₹1,000,000 equity and active killswitch state, allowing them to trade during periods when the continuous full-period portfolio was locked out.
- **Resolution:** Documented explicitly in `walkforward_and_killswitch_spec.md` and `reports/dev_report_v2.md`. Independent folds must never be described as a single continuous deployable path.

---

## 6. Correcting Parameter Grid Sweep Candidate Claims

- **Previous Inaccurate Claim:** Line 102 of `dev_report_v2.md` stated: *"all candidates show non-positive out-of-fold expectancy."*
- **Empirical Facts from Grid Sweep (Trials 103–126):**
  - **Candidate 0** (1.5 ATR / 1.5 R): Mean OOF Exp: -0.025 R $\to$ Negative edge.
  - **Candidate 1** (1.5 ATR / 2.0 R): Mean OOF Exp: -0.369 R $\to$ Negative edge (matches baseline fold average).
  - **Candidate 2** (1.5 ATR / 2.5 R): Mean OOF Exp: -0.285 R $\to$ Negative edge.
  - **Candidate 3** (2.0 ATR / 1.5 R): Mean OOF Exp: **+0.056 R** $\to$ Positive edge, but below the pre-registered +0.20 R threshold and fails fold consistency (only 3/4 folds beat baseline).
  - **Candidate 4** (2.0 ATR / 2.0 R): Mean OOF Exp: -0.168 R $\to$ Negative edge.
  - **Candidate 5** (2.0 ATR / 2.5 R): Mean OOF Exp: **+0.201 R** $\to$ Positive edge, beats baseline across 4/4 folds, but **fails the pre-registered parameter plateau retention requirement** (neighboring parameter stability fails).
- **Resolution:** Report text is updated to state the exact factual failure mode for each candidate rather than making the inaccurate blanket statement that all candidates were non-positive.

---

## 7. Statistical & Cost Stress Wording Alignments

1. **Bootstrap Confidence Interval:** Code in `src/signal_atlas/backtest/walkforward.py` and `engine.py` evaluates percentiles 2.5 and 97.5 (a **95% Bootstrap Confidence Interval**). All docstrings and report text are aligned to state 95% CI.
2. **Cost Stress Specification:** In Section 4 and Section 7:
   - Slippage stress increases from 10 bps to 25 bps: this is a **2.5x increase** (not 2.0x).
   - Statutory fees (exchange turnover, SEBI turnover) are doubled (**2.0x**).
   - The report now accurately states: *"Cost Stress (2.5x slippage: 25 bps, 2.0x statutory exchange fees)."*
