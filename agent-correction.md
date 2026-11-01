# Signal Atlas: Combined Correction Report for the Backtest Agent (v3)

**Supersedes:** `agent-correction-brief.md`.
**Reviewed:** `metrics.py`, `costs.py`, `engine.py`, backtest `pipeline.py`, `run_pipeline.py`, `walkforward.py`, `robustness.py`, `trend_pullback.py`, ingestion `pipeline.py`, `experiments/registry.csv`, `reports/dev_report.md`, and one live `signal-atlas screen` output (2026-08-14).
**Not reviewed:** `models.py` and `strategy/models.py` (parameter defaults), `frozen_v1.yaml`, the universe service, the feature engine, any trade log.

---

## 1. Verdict on the v1 development report

The "GO" verdict is invalid and the report must not be used for any decision. Five independent reasons:

1. The verdict code never checks three pre-registered criteria (expectancy at least +0.20R, drawdown limits, benchmark comparison), and the report prints a literal "PASS" for every row.
2. The universe is chosen with future data (top 100 by average traded value over the entire 2022 to 2024 period) and applied to every date.
3. The reported drawdown is measured from a peak that is reset after the kill-switch cooldown, so it understates true drawdown.
4. The "random-entry baseline" is not a random-entry test. It re-samples the strategy's own results.
5. The parameter sweeps are partly broken, and the code's own selection rule contradicts the report's "baseline preserved" claim.

Applying the committed thresholds honestly to the v1 numbers gives at least: expectancy 0.170R against 0.20R (not met), historical drawdown 12.68% against 10% (not met), Monte Carlo p95 drawdown 15.16% against 15% (not met), and those figures themselves are unreliable for the reasons above.

---

## 2. Standing rules (add to AGENTS.md)

1. **Verdicts are computed, never typed.** Every PASS, FAIL, GO, status label, and sentence in a report is generated from computed values. No hard-coded adjectives such as HEALTHY, OPTIMAL, DISCIPLINED, CONTROLLED, or "Robust Plateau".
2. **Criteria live in a committed file.** Create `configs/go_no_go_criteria.yaml` with the exact thresholds from Section 8 of `backtest-and-tuning-plan.md`, commit it, and load it in code. Never edit thresholds after a run.
3. **The registry is append-only.** Every run is logged, including exploratory runs, train-window runs, and sanity-test runs. Any rule added after seeing results is logged as a trial with its rationale.
4. **One engine.** No second implementation of strategy filters, fills, or sizing.
5. **Do not create `HOLDOUT_UNLOCK`.** Only the human does.
6. **A criterion is PASS only if a printed computation or unit test backs it.** If something was not run, the report says "NOT RUN".

---

## 3. Defect register

Severity: **C** = invalidates headline results, **H** = materially affects results or trust, **M** = limitation or smaller error.

| ID | Sev | File | Defect | Evidence |
|---|---|---|---|---|
| D1 | C | backtest `pipeline.py` | Universe look-ahead and survivorship | `load_development_dataset` ranks symbols by `avg(traded_value)` over 2022-01-03 to the end date, requires 100+ sessions, applies one fixed list to all dates. `PointInTimeUniverseService` exists but is not used. |
| D2 | C | `run_pipeline.py` | Verdict ignores criteria; PASS typed | `overall_dev_verdict` combines only sample size, profit factor, random baseline, cost stress, variant C, drop-trades, drop-symbols. `gate_beats_bench` is computed but unused. Expectancy and drawdown are never gated. Every report row contains a literal `**PASS**`. |
| D3 | C | backtest `pipeline.py` | Peak reset hides drawdown; cooldown counter flawed | After the cooldown, `peak_equity = curr_equity`. The equity-curve `drawdown_pct` uses that peak. The counter only decrements on days when drawdown is at or above the threshold. |
| D4 | C | `robustness.py` | "Random-entry" test is a bootstrap of the strategy's own R-multiples | It subtracts the mean R, adds an arbitrary -0.05R, and re-samples. The resulting p95 (about +0.07R) is just `-0.05 + 1.645 × sd/√n`. No random entries are simulated. |
| D5 | C | `metrics.py` | Profit factor and cost share use the wrong basis | Wins and losses are split by `net_pnl`, but profit factor sums `gross_pnl` (pre-cost). `costs_as_pct_gross_profit` divides total costs by the gross profit of winners only. |
| D6 | C | `run_pipeline.py` | Sweeps broken; selection contradicts report | See Section 3.1. |
| D7 | H | backtest `pipeline.py`, `trend_pullback.py` | Ranking by tick-rounding noise | Stop and target are rounded to 0.05, then R:R to 0.01. R:R differs only by rounding, so candidates sort by it. Cheap stocks rank first (see the live screen). |
| D8 | H | backtest `pipeline.py` | Backtest is not the live system | Strategy filters, fills, and sizing re-implemented inline. Entry-gap limit hardcoded at 1.5% while the param is 2%. Live treats unknown weekly trend (`None`) as pass; the runner treats it as fail. Backtest universe is 100 names; the live `--all` screen covers 2,463. |
| D9 | H | `walkforward.py`, `run_pipeline.py` | Registry is incomplete and ambiguous | Trial IDs 6 to 8 are used twice (WF folds are IDs 5 to 8, sweeps start at 6). IDs 2 to 4 missing. Train-window and sanity-test runs are not logged. Sweep rows log only the override, not the full config. No code commit, data hash, or cost-model version. "Total configurations" prints the last trial ID. |
| D10 | H | backtest `pipeline.py` | Position handling gaps | Missing bar means marked at entry price. End-of-simulation exit is skipped if the bar is missing, so positions never close. Fill-day `traded_value` is used for the volume cap (future information). |
| D11 | H | `run_pipeline.py` | Hard-coded and wrong report text | Benchmark Sharpe "~0.85" typed. "Cutting drawdown by nearly 5 points" typed (actual 1.2). "Statistically significant" typed. "Cash deployed ~50%" typed (exposure was 78%). Benchmark CAGR = return/3. Negative folds print as `+-0.32 R` and are labeled "FLAT/NEUTRAL". |
| D12 | H | `metrics.py` | Uncertainty estimates assume independence | Bootstrap resamples trades i.i.d. Monte Carlo reshuffles trade order, adding rupee P&L over initial capital, which ignores compounding, overlap, and loss clustering. |
| D13 | H | plan vs code | Planned tests not implemented | Look-ahead scan, random sub-universes, parameter-neighbor plateau, Tier-2 EMA robustness, bootstrap CI of improvement, minimum 30 trades per fold, kill-switch variants, MAE/MFE, regime breakdown. The report says all 7 gates passed without noting these are missing. |
| D14 | M | `run_pipeline.py` | Variant C is mislabeled | It fills at the signal close or better, skips the gap rule and the R:R recheck, so it avoids chasing rather than being pessimistic. |
| D15 | M | costs | Cost assumptions | Brokerage is zero (valid for Zerodha delivery, not Groww). No tax. No dividends. Stress test only scales slippage and the DP charge. Cost total includes slippage. |
| D16 | M | report | Benchmark comparison inconsistent | Benchmark drawdown is true peak-to-trough; strategy drawdown uses the reset peak. |
| D17 | M | engine | Regime gate defaults to "bullish" when the benchmark EMA is missing; tick rounding applied to adjusted prices; `engine.py` and the fast runner differ. | |

### 3.1 Sweep and selection details (D6)

- `run_pipeline.py` applies overrides with `if hasattr(cfg_params, k): setattr(...)`. `TrendPullbackParameters` has no `target_r_multiple`, so that key is silently skipped. The "target_r 1.5" run is identical to the baseline. The registry confirms it (same results to every digit).
- With stop 1.5 ATR, a 4.0 ATR target is 2.67R and a 5.0 ATR target is 3.33R. The report's 2.0R and 2.5R labels are wrong, and a real 1.5R target was never tested.
- Reward-to-risk is `target_atr / stop_atr` for every candidate. Stop 2.5 ATR gives 1.2, below the 1.5 minimum, so every signal is rejected and the run has zero trades. Stop 2.0 ATR gives exactly 1.5.
- Selection rule in code: positive in at least 3 folds and average above baseline, with a margin of 0.05. Using the registry, baseline averages +0.150R across test folds; target 5.0 ATR averages +0.239R with 3 of 4 positive folds, a margin of 0.089. By its own rule the code should select it as `TUNED`, but the report text says "Baseline v1.0 was preserved". **Check `frozen_v1.yaml`; either it or the report is wrong.**
- That 5.0 ATR result is driven mostly by one fold (+0.994R in fold 2) and is -0.338R in fold 4.
- The plateau-retention figure is printed but never used to select. The minimum 30 trades per fold and the bootstrap CI of the improvement are not implemented.
- Fold 4 (2024-07 to 2024-12) is negative in every configuration that produced trades.

---

## 4. Corrective tasks (in order)

After each task, re-run the baseline and add a row to the attribution table (Task 14).

### Task 0: Freeze

- Banner on `reports/dev_report.md`: "SUPERSEDED, known defects, see v2."
- Remove "GO", "statistically significant", and "plateau verified" from it.
- Create and commit `configs/go_no_go_criteria.yaml` (Standing rule 2).

### Task 1: Point-in-time universe (D1)

- Replace `load_development_dataset`'s SQL with per-date membership using data up to date `t` only: trailing 126-session traded value, series EQ, minimum history, top N, recomputed on a fixed schedule (for example monthly from the prior month-end).
- Exclusions per the architecture: ETFs, REITs, InvITs, SME, partly-paid and special series.
- Do not filter on end-of-period validity. Include names that later stopped trading.
- The ingestion code never sets `valid_to`, never marks delistings, and sets `listing_date` to the first ingested date. Add delisting detection (last traded date, status) before relying on it.
- **Tests:** deleting all data after `t` leaves the universe for `t` unchanged; print the 2022-03-01 universe and the count of members that later stopped trading (explain if zero); report results on the old fixed list for comparison.

### Task 2: One engine, equal to live (D8, D17)

- Remove `BacktestEngine` or the inline fast runner. The remaining engine calls shared functions for filters, entry evaluation, and sizing.
- Read the entry-gap limit from `max_entry_gap_pct`.
- Make unknown weekly trend block the signal in both live and backtest paths.
- **Equivalence test:** signals, entries, stops, targets, and quantities match the live `evaluate_candidate`, `evaluate_next_session_entry`, and `RiskEngine` for at least 500 random (date, symbol) pairs and 10 dates checked against `get_setup`.

### Task 3: Kill-switch and drawdown (D3)

- Track a never-reset high-water mark; compute every reported drawdown from it.
- Make kill-switch state explicit (`ACTIVE`, `COOLDOWN(n)`); decrement every session.
- Run three variants and report each: never re-enable, re-enable after N sessions keeping the true peak, and the current rule.
- **Test:** synthetic equity with a known 15% drawdown and recovery reports 15% in every variant.

### Task 4: Ranking (D7)

- Replace R:R sorting. Use a deterministic rule based on data up to `t` (for example trailing traded value, or RSI closeness to 50) and document it.
- Do not round R:R before comparing. Do not rank on tick-rounding artifacts.
- Run an ablation with random tie-breaks over 20 seeds and report the spread of expectancy.

### Task 5: Metrics (D5, D12)

- Profit factor on **net** P&L, and also on R-multiples. Report both.
- Costs as a share of total gross P&L (about 29% in v1: 343,506 / 1,167,237), split into slippage and statutory charges.
- Month-block bootstrap for the expectancy CI.
- Replace the Monte Carlo with a re-simulation that keeps compounding and overlap, or a block bootstrap of monthly returns.
- **Test:** a 6-trade example with every output verified by hand.

### Task 6: Real baselines (D4)

Replace `run_random_entry_baseline` with full simulations (200 or more runs):

- **Random entry:** same days, same number of entries per day as the strategy, random eligible instruments, same stops, targets, exits, costs, sizing, and portfolio limits. Compare expectancy, net return, and drawdown distributions.
- **Trend-only baseline:** the strategy without the pullback and RSI conditions, to test whether the pullback adds value beyond trend.
- **Equal-weight universe buy-and-hold.**
- Under the committed criteria, the strategy must beat the p95 of the random-entry distribution. Note that a long-only strategy in a rising universe has positive expectancy under random entry, so the null is not zero.

### Task 7: Sweeps and selection (D6, D13)

- Define stop in ATR and target in R-multiples (`target = entry + R × risk`) so they are independent. Sweep a small 2D grid and the minimum R:R.
- Fail loudly if a parameter key is not recognized by the params model (no silent `hasattr` skip).
- Guard: a configuration whose trades equal baseline when its parameter differs must raise an error. A configuration with zero trades in any fold is flagged and excluded from plateau claims.
- Implement the plan's selection rules: positive in at least 3 of 4 folds, at least 30 trades per fold, neighbor plateau retention of at least 70%, and a bootstrap CI of the improvement that excludes zero. Otherwise keep baseline.
- Make `frozen_v1.yaml` and the report agree, both generated from the same selection result.

### Task 8: Registry (D9)

- Unique monotonic trial IDs. Log every run: train windows, sanity tests, sweeps, kill-switch variants, earlier exploratory runs (restore from git history).
- Log the full resolved config (params, costs, portfolio limits), config hash over all of it, code commit, data snapshot hash, and cost-model version.
- Report the number of distinct configurations, not the last ID.

### Task 9: Report generation (D2, D11)

- Generate the report from a template where every number, status, and sentence is computed. Remove hard-coded statuses and commentary.
- Format signs correctly (`-0.32R`, `-Rs. 96,364`). Fold status is POSITIVE or NEGATIVE.
- Benchmark CAGR computed with the same method as the strategy. Benchmark Sharpe computed, not typed.
- The dev report lists each committed criterion as "met" or "not met" with the number and threshold. No GO or NO-GO until the holdout.

### Task 10: Position handling and look-ahead (D10)

- Mark missing bars at the last known close. Force-exit after a defined number of missing sessions. Assert no positions remain open at the end of a run.
- Volume cap uses trailing average traded value through `t`, not the fill day's value.

### Task 11: Investigate H2 2024

- Fold 4 is negative in every configuration. Also, 2024 is +0.05R in the full run but about -0.04R when folds 3 and 4 are combined. Report win rate, signal count, average gap, exit mix, regime-gate state, and the random-entry result for 2024-07 to 2024-12, and explain the full-run versus fold difference.

### Task 12: Missing tests (D13, D14)

- Implement or mark NOT RUN: look-ahead scan, random sub-universes, parameter-neighbor plateau, Tier-2 EMA robustness (20/50 against 21/55 and 15/45), kill-switch variants, MAE/MFE, regime breakdown.
- Rename variant C "limit order, strict touch". Add a real pessimistic fill variant (limit with the gap rule and R:R recheck, plus adverse selection).
- Stress test: scale all non-statutory costs, not only slippage.

### Task 13: State what is not modeled (D15, D16)

List explicitly: dividends and corporate-action accounting (and what the adjusted series contains), brokerage assumption and which broker it represents, short-term capital gains tax (report pre-tax and post-tax), earnings-date gaps, sector concentration, price bands, benchmark dividends.

### Task 14: Attribution re-run

Apply fixes in this order and record the baseline after each: (1) point-in-time universe, (2) true drawdown and kill-switch, (3) ranking, (4) metrics, (5) single engine, (6) position handling. Produce `reports/dev_report_v2.md` with a table of expectancy, net return, true max drawdown, net profit factor, and trade count after each step, so the effect of each defect on the v1 result is visible.

### Task 15: Align the live screener with what was tested

See Section 5.

---

## 5. Live screener findings (`screen --date 2026-08-14 --all`)

The output shows 2,463 screened, 339 approved. Observations:

- **The ranking is noise.** The top of the list is ordered by R:R of 2.05, 2.04, 2.02, 2.01, and the leaders are the cheapest stocks (PCJEWELLER at Rs. 9.64, LOWVOLIETF at 22.59, SOUTHBANK at 45.74). The 0.05 tick is a much larger share of a Rs. 10 price, so rounding pushes R:R above 2.0. This is the same ranking the backtest used (D7).
- **No eligibility filter is visible.** The list includes ETFs (LOWVOLIETF, SBIMIDMOM, MON100) and sub-Rs. 100 mid and small caps. The architecture excludes ETFs and requires a liquidity universe. The backtest used a 100-name list, so the live screen is not the system that was tested. (I assume `--all` bypasses the universe; confirm.)
- **Capacity versus candidates.** With 1% risk per trade and a 6% open-risk cap, at most about 6 positions fit. The ranking therefore decides which 6 of 339 you would trade.
- **Missing information.** The output has no average traded value, price band, series, or universe membership, and the constraint column only shows `RISK_BUDGET` or `CAPITAL_CAP`.

**Do:**
- Apply the same point-in-time universe and eligibility rules in `screen` and the backtest (shared code).
- Add price, ADTV, series, and membership flags to the output, plus the number of positions the risk limits allow.
- Rank by the deterministic rule from Task 4.
- Label `--all` clearly as bypassing the liquidity universe.

**Holdout hygiene:** 2026-08-14 falls inside the locked holdout window (2025-01-01 to 2026-10-30). Viewing signals is not the same as evaluating performance, but looking at how those candidates later performed would be peeking. Do not do that before the holdout evaluation.

---

## 6. Definition of done

- Every task has a test or printed evidence.
- No verdict, status, or commentary string is hand-written.
- Criteria are loaded from the committed file.
- The registry contains every run with a unique ID.
- The report states "met" or "not met" per criterion with numbers.
- The attribution table shows the effect of each fix.
- `frozen_v1.yaml` and the report agree.
- The holdout is still locked.