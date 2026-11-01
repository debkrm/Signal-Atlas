# Signal Atlas: Backtesting and Tuning Plan

**Audience:** the AI coding agent building and running the backtest, plus Deb (the human owner).
**Strategy under test:** `trend_pullback` v1.0 (long-only, delivery swing, NSE cash equities).
**Status of this document:** research plan, not investment advice. A backtest can show a strategy did not fail on past data. It cannot prove the strategy works.

---

## 0. Goal and ground rules

**Goal:** decide, with evidence, whether `trend_pullback` has a real, cost-adjusted edge, and find robust parameters if it does. The output of this plan is a **GO / NO-GO / INSUFFICIENT EVIDENCE** decision, not a "best" parameter set.

### Rules the agent must follow

1. **The holdout is locked.** Data from `2025-01-01` to the latest ingested session is the final holdout. Do not load, plot, or summarize it until the human creates a file named `HOLDOUT_UNLOCK` in the repo root. The agent must never create that file itself.
2. **Pre-register before running.** The go/no-go criteria (Section 8) are committed to git before any holdout run. Never edit them afterwards to make a result pass.
3. **Log every run.** Every backtest run, including failed and discarded ones, is stored in the `backtest_runs` and `backtest_trades` tables from the architecture, with strategy version, parameters, config hash, git commit, source-file or data snapshot hashes, cost-model version, execution assumptions, date range, trial number, and key metrics. A CSV export at `experiments/registry.csv` is fine as a convenience. The total number of configurations tried must be reported in the final report.
4. **Never change strategy logic mid-experiment.** Only change values in the config file. Logic changes (new indicators, new rules) are a new strategy version (`v1.1`) with its own plan.
5. **Report negative results plainly.** "No edge found" is a valid, useful result. Do not tune until something looks good.
6. **Determinism.** Fixed random seeds, pinned dependencies, and a hash of the input data stored with every run. Re-running a config must reproduce the same trades.
7. **Stop and ask the human** if any of these happen: a data validation check fails, fewer than 30 trades are produced in any dev fold, the backtest results contradict the live `get_setup` output for the same date, or the plan needs a decision that is not covered here.

### Reuse the live engine

The backtest must call the **same** signal, sizing, and risk-check code that `screen` and `get_setup` use (position sizing with `q_risk` / `q_capital` / `q_liquidity`, max 10 positions, max 6% total open risk, 10% drawdown kill-switch, surveillance and liquidity checks). A separate simplified backtest will drift from the live system and its results will not transfer.

**Precedence:** where this plan and the architecture plan or build instructions disagree on engine behavior, the architecture documents win. This plan adds stricter tests and decision rules on top of them.

> Module and file names below are suggestions. Adapt them to the actual repo layout.

```
backtest/
  data_checks.py       # Phase 1 validators
  engine.py            # event loop, fills, portfolio, costs
  costs.py             # brokerage/taxes/slippage model
  metrics.py           # R-multiples, PF, drawdown, bootstrap, Monte Carlo
  walkforward.py       # fold generation and tuning loop
  baselines.py         # random-entry, buy-and-hold benchmarks
  report.py            # generates the markdown report
configs/
  base.yaml            # frozen defaults (current live values)
  grids/*.yaml         # parameter grids per tuning stage
experiments/
  registry.csv         # every run ever made
reports/
  data_validation.md
  dev_report.md
  holdout_report.md    # created only after HOLDOUT_UNLOCK
```

---

## 1. Phase 1: Data validation (gate: must pass before any backtest)

The earlier `FRESH` flag reported 2024-12-31 data as fresh in November 2026, so do not trust data-status flags. Validate directly. This also contradicts the freshness rule in the architecture plan (freshness is measured against the last expected trading session, and stale prices block new BUY setups), so treat it as a bug to fix.

| Check | Method | Pass condition |
|---|---|---|
| Date coverage | Compare ingested dates to the NSE trading calendar | No missing sessions per symbol, except documented suspensions or listing gaps |
| Latest session | `latest_ingested_date` vs last NSE session | Within 1 trading session of the most recent session |
| Price adjustment | Scan for single-day moves beyond ±20% and near plausible split/bonus fractions; cross-check with corporate-action records | Every large move is explained by a real move or is correctly adjusted. Unreconciled discontinuities **quarantine the instrument** for the affected period; never auto-apply an action inferred from a price pattern |
| Split accounting | Unit test: the same trade with and without an intervening split | Identical economic P&L and R; quantity, cost basis, stop, target, and cash flows all transform consistently |
| Newly listed securities | First traded date per symbol | No signals until the symbol has the universe's minimum history (this also keeps recent IPOs out until enough post-listing history exists) |
| OHLC sanity | `low <= open, close <= high`, no zero or negative prices, no zero-volume days on traded names | Zero violations, or each one logged and excluded |
| Benchmark | NIFTYBEES series continuous over the same range | No gaps |
| Duplicates and ordering | Duplicate (symbol, date) rows, out-of-order dates | None |
| Indicator warm-up | First valid EMA50 / weekly EMA / RSI date per symbol | Drop the warm-up period from results; document the first tradable date |
| Look-ahead audit | Unit test: indicators computed on data truncated at day `t` equal the indicators at `t` from the full dataset | Exact match for all symbols and 20 random dates each |

**Deliverable:** `reports/data_validation.md` with pass/fail per check, list of excluded symbols or dates, and the actual first and last dates available.

**Also in this phase, add a staleness guard to the live tools:** `screen` and `get_setup` should refuse to run (or return a loud `STALE` status) when `latest_ingested_date` is more than 1 to 2 sessions behind the last NSE session. This is separate from the backtest but should be fixed first.

---

## 2. Phase 2: Backtest engine specification

### 2.1 Timing conventions (prevents look-ahead bias)

- A signal for day `t` is computed using **only data up to the close of day `t`**.
- The order is placed for day `t+1`. Nothing from day `t+1` may influence whether the signal exists.
- Position sizing at entry uses the portfolio equity as of the close of day `t`.

### 2.2 Entry model

The live setup uses entry = signal-day close, with a zone of roughly ±0.5% around it. Model the way Deb would actually trade it (manual delivery orders via Zerodha or Groww):

- **Primary (A), matches the architecture spec:** the day `t+1` open is the fill reference, plus entry slippage.
  - Recalculate reward-to-risk using the actual open (keeping the planned stop and target).
  - If the open is above `entry_zone_high`, or the recalculated R:R falls below the minimum (1.5), or the open is at or below the stop: **skip the trade**. Never assume a fill at the planned entry.
  - Round fills to a valid tick size.
- **Variant (B), limit-order model:** buy-limit at `entry_price` for day `t+1` only. Fill at `open` if `open <= entry_price`; else at `entry_price` if `low <= entry_price`; else no fill. This is how a manual limit order would behave.
- **Variant (C), pessimistic limit:** same as B, but require `low < entry_price` by at least one tick to count as a fill.
- **Reference only, never for decisions:** fill at the `t+1` open and skip the R:R recheck.

Report the **fill rate** (filled signals / total signals) for each variant. A strategy that only works with unrealistic fills is not a strategy.

### 2.3 Exit model (evaluated each day after entry, in this order)

1. **Gap through stop:** if `open <= stop`, exit at `open` (worse than the stop).
2. **Stop hit intraday:** if `low <= stop`, exit at `stop`.
3. **Target hit:** if `high >= target`, exit at `target` (or at `open` if the open is already above the target).
4. **Same-bar conflict:** if both stop and target are touched in one bar, assume the **stop was hit first** (pessimistic).
5. **Time stop (if the live strategy has one, or as a tested option):** exit at the close of day `N`.
6. **Regime exit (test as an option, off by default):** exit if NIFTYBEES closes below its EMA50.

Track **gap-through-stop count and the average loss in R on those trades**. If many losers are worse than -1R, the planned risk is understated and position sizing is too aggressive.

### 2.4 Costs and slippage (parameterized)

Build `costs.py` as a config-driven model. Verify every number against the current broker charge sheet and exchange schedule before the final run, since these change.

| Component | Applies to | Notes |
|---|---|---|
| Brokerage | Per order | Depends on Zerodha vs Groww delivery plans |
| STT | Delivery buy and sell | Percentage of turnover |
| Exchange transaction charges | Both sides | Percentage of turnover |
| SEBI turnover fee | Both sides | Small |
| Stamp duty | Buy side | Percentage of turnover |
| DP charges | Per sell scrip per day | Flat amount |
| GST | On brokerage and certain fees | Percentage |
| Slippage | Both sides | Base case 5 to 10 bps, stress case 20 to 30 bps |
| Tax | Short-term capital gains on profits | Report results **pre-tax and post-tax**; verify the current rate |

Costs are charged on every trade, and the report must show **costs as a percentage of gross P&L**. On a 1R-risk, 2R-target swing system with a small stop distance, costs can consume a large share of the edge.

### 2.5 Portfolio and risk rules

Use the live values from `market_status`:

- Risk per trade: 1% of equity (from the fraction `0.01` returned by the tool)
- Max concurrent positions: 10
- Max total open risk: 6% (fraction `0.06`)
- Drawdown kill-switch: 10% (new entries halted; define the re-enable rule explicitly and test both "never re-enable" and "re-enable after N sessions")
- Starting equity: 1,000,000 (configurable; report results in **R and % of equity**, so capital size does not matter)
- Mark-to-market equity daily; compound position sizing off current equity
- When more signals qualify than free slots, rank by the live `screen` ranking. Run an ablation with a different tie-break (for example, lowest RSI distance from 50) to test sensitivity to the ranking.

### 2.6 Market regime gate

The live gate requires NIFTYBEES > EMA50. Backtest **with the gate** as the baseline. Also run **without the gate** as an ablation to measure what the gate adds, and report the percentage of sessions in which the gate blocked all new entries. Test the architecture plan's example gate (Nifty 50 versus its 200-day average) as an alternative variant, and choose between gates using the walk-forward folds, not the full-sample result.

### 2.7 Universe

- Use the **point-in-time liquidity universe** from the architecture (trailing 126-session traded value, series and eligibility filters, minimum history), built from historical listed-security data including subsequently delisted names where the source supports them. Do not use a fixed list.
- If the live system currently screens a fixed 100-stock list, treat it as a stand-in: run it only as a clearly labeled secondary comparison, and note that a list based on today's constituents carries survivorship bias.
- Exclude a security until it meets the universe's minimum history, which keeps recent IPOs out until enough post-listing history exists.
- **Survivorship bias:** a current-constituents list excludes stocks that were delisted, suspended, or removed. Document this limitation in the report. If historical index membership can be reconstructed, use point-in-time membership. If it cannot, apply a stated haircut and test stability on random sub-universes (Section 6).
- Apply the live surveillance (ASM/GSM/circuit) and liquidity filters where historical data exists. If historical surveillance status is not available, state that those filters were not applied in the backtest.

### 2.8 Known data gaps

The live tools warn that the earnings calendar, sector metadata, and promoter pledge data are unavailable. A backtest cannot model what is not in the data, so:

- Report the distribution of overnight gaps larger than 5% and how many trades were affected.
- If a results-date history can be sourced, tag each trade whose holding period spans an earnings date and report performance with and without those trades.
- Disclose that sector concentration was not evaluated.

### 2.9 Corporate actions in the simulation

Keep three things separate, as the architecture requires: raw exchange prices, adjusted analytical prices, and trade accounting.

- Compute indicators on split/bonus-adjusted prices. Do not dividend-adjust indicator inputs.
- Use **raw** prices for fills, tick-size rounding, and price-band checks.
- For a position open across a split or bonus, transform quantity, cost basis, stop, and target consistently. A mechanical price drop must not count as a trading loss.
- For dividends, credit the entitlement according to ex-date and payment-date rules and include it in total-return accounting.
- Mergers, demergers, rights issues, and fractional entitlements are not modeled yet. Exclude the affected instrument and period from the backtest and list the exclusions in the report.
- Never apply a corporate action twice or mix adjusted and raw coordinate systems within one position.

---

## 3. Phase 3: Data splits

Use the whole ingested history, not just two years. The data already ingested runs about 3 years to 2024-12-31 (743 sessions at that date). After catch-up it should span roughly 4.5 to 5 years, which covers more than one market regime.

| Segment | Dates | Use |
|---|---|---|
| Warm-up | First ~100 sessions | Indicators only; no trades |
| **Development set** | End of warm-up to `2024-12-31` | Exploration, tuning, walk-forward |
| **Final holdout** | `2025-01-01` to the latest session | **Locked. One look only.** |

### Walk-forward folds inside the development set

Use anchored (expanding) windows, with a 12-month minimum training window and 6-month test windows. Adjust the dates to the actual start of data:

| Fold | Train | Test |
|---|---|---|
| 1 | Start to 2022-12 | 2023-01 to 2023-06 |
| 2 | Start to 2023-06 | 2023-07 to 2023-12 |
| 3 | Start to 2023-12 | 2024-01 to 2024-06 |
| 4 | Start to 2024-06 | 2024-07 to 2024-12 |

In each fold, tune on the train window and **score only on the test window**. The tuning decision is based on test-window results across all folds, not on the train window.

**The holdout can only be used once.** If the strategy fails on the holdout, the holdout is burned. The next independent validation data is forward paper trading (Section 9).

---

## 4. Phase 4: Baseline run (no tuning)

Run the **current live parameters unchanged** on the development set. This is the reference everything else is compared to.

| Parameter | Current live value (from `get_setup`) |
|---|---|
| EMA fast / slow | 20 / 50 |
| Weekly trend | Close > 10-week EMA |
| Pullback proximity | Within 4% of EMA20 and at or above EMA50 |
| RSI(14) reset zone | 40 to 60 |
| Minimum reward-to-risk | 1.5 |
| Target | 2.0R |
| Stop | Per live rule (confirm whether ATR-based and its multiple) |
| Regime gate | NIFTYBEES > EMA50 |

**Deliverable:** `reports/dev_report.md` section "Baseline", with every metric in Section 5.

**Checkpoint:** compare 5 to 10 backtest signals against `get_setup` for the same dates. They must match exactly (entry, stop, target, pass/fail). If they do not, stop and fix the engine before continuing.

---

## 5. Metrics to report for every run

Report **net of costs and slippage** unless stated otherwise.

**Per-trade and edge quality**
- Number of trades, signals generated, fill rate
- **Expectancy in R** (average net R per trade). This is the primary metric.
- Win rate, average win (R), average loss (R), largest loss (R)
- Profit factor
- Exit breakdown: % target, % stop, % time-stop, % gap-through-stop
- Average holding period (sessions)
- MAE and MFE (maximum adverse and favorable excursion) distributions, which show whether stops and targets are placed sensibly

**Portfolio**
- CAGR, total return
- Max drawdown (%) and longest drawdown duration
- Calmar ratio (CAGR / max drawdown) and Sharpe or Sortino on daily equity returns
- Exposure (% of sessions with at least one open position) and average number of open positions
- Number of times the drawdown kill-switch would have triggered

**Uncertainty**
- **Bootstrap 95% confidence interval on expectancy:** resample trades with replacement, 10,000 times
- **Monte Carlo of trade order:** reshuffle the trade sequence 10,000 times and report the median and 95th percentile of max drawdown and the longest losing streak. Compare the 95th-percentile drawdown to the 10% kill-switch.

**Breakdowns**
- By year and by quarter
- By regime (gate on vs off periods)
- By symbol (top 10 contributors, and whether results depend on a few names)
- By entry month and weekday (look for data artifacts, not for trading rules)

**Benchmarks**
- Buy-and-hold NIFTYBEES over the same period
- Equal-weight buy-and-hold of the same universe

---

## 6. Phase 5: Sanity and robustness tests (run on the baseline, before tuning)

These tests look for results that are too good, or too fragile, to be real.

| Test | What it does | What a healthy result looks like |
|---|---|---|
| Random-entry baseline | Keep exits, sizing, and costs; replace signals with random entries on the same universe and regime, 1,000 runs | Strategy expectancy beats the 95th percentile of random runs |
| Delay-by-one-day | Enter one session later than the signal | Modest degradation, not a collapse and not an improvement |
| Cost stress | Double costs and slippage | Expectancy stays above zero |
| Fill pessimism | Use entry variant C | Expectancy still positive |
| Remove best trades | Drop the top 5% of trades by R | Expectancy stays above zero (not driven by a handful of outliers) |
| Remove best symbols | Drop the top 5 contributing symbols | Expectancy stays above zero |
| Random sub-universes | 20 random halves of the universe | Most halves positive; low dispersion |
| Gate ablation | Run without the regime gate | Shows what the gate contributes; the gate should reduce drawdown |
| Time-shift of benchmark | Check regime gate uses prior-day benchmark close, not same-day | No look-ahead in the gate |
| Look-ahead scan | Re-run the unit test from Phase 1 after any engine change | Still passes |

**If the strategy fails the random-entry baseline or the cost stress on the development set, stop.** Tuning will not rescue a strategy with no edge. Report NO-GO and recommend a strategy revision instead.

---

## 7. Phase 6: Tuning protocol

### 7.1 Which parameters may be tuned

| Tier | Parameters | Policy |
|---|---|---|
| **Tier 1: tune** | ATR stop multiple (e.g. 1.5, 2.0, 2.5, 3.0); target in R (1.5, 2.0, 2.5, 3.0); pullback proximity to EMA20 (2, 3, 4, 5 %); RSI band (low 35/40/45, high 55/60/65); time stop (none, 10, 15, 20 sessions) | Staged grid search with limits below |
| **Tier 2: robustness only** | EMA lengths (e.g. 20/50 vs 21/55 vs 15/45), weekly EMA length, regime EMA length | Do not optimize. Test neighbors only, to confirm the result is not a knife-edge at exactly 20/50 |
| **Tier 3: frozen risk policy** | Risk per trade, max positions, max open risk, kill-switch level | Not tuned for return. Evaluate them against Deb's drawdown tolerance only |

### 7.2 Procedure

1. **Stage 1, one-at-a-time sweeps:** vary each Tier 1 parameter alone while holding the rest at baseline. Identify which parameters actually move expectancy.
2. **Stage 2, small joint grid** over only the parameters that mattered, centered on the best region from Stage 1.
3. **Walk-forward scoring:** for each candidate configuration, record test-window expectancy, profit factor, and max drawdown in each of the 4 folds.
4. **Trial budget:** at most about **150 configurations** in total. The agent must report the exact number tried. More trials mean more chance that the winner is luck.

### 7.3 Selection rules

A configuration is a candidate only if it:

- Has **positive net expectancy in at least 3 of 4 test folds**
- Has **at least 30 trades per test fold** (or the fold is marked underpowered and excluded from the vote)
- Sits on a **plateau**: each neighboring grid value (one step in any tuned parameter) retains at least 70% of its expectancy
- Beats the baseline by more than the noise: the bootstrap 95% confidence interval of the improvement must not include zero, or the baseline is kept

**Prefer the simplest, most central configuration on the plateau**, not the single highest-scoring point. If no tuned configuration clearly beats the baseline, **keep the baseline**. That is a successful outcome.

### 7.4 What not to do

- Do not tune on the holdout, and do not "peek" at it to choose between finalists.
- Do not add parameters or rules because they improve a fold.
- Do not select parameters on the full-sample result; always use the walk-forward test windows.
- Do not tune EMA lengths to the best single value.
- Do not report only the best fold or best year.

**Deliverable:** `reports/dev_report.md` with the baseline, all sanity tests, the tuning tables, the trial count, and the chosen configuration, frozen as `configs/frozen_v1.yaml`.

---

## 8. Phase 7: Pre-registered go/no-go criteria

These are **defaults**. Deb should review and edit them **before the first holdout run**, then commit them. After that commit they cannot change. All numbers are net of costs and base-case slippage, evaluated on the **holdout** unless stated.

| Criterion | GO threshold |
|---|---|
| Sample size | At least 60 holdout trades and 150 trades overall. Below this, the result is **INSUFFICIENT EVIDENCE**, not GO |
| Expectancy | At least **+0.20R** per trade |
| Profit factor | At least 1.3 |
| Consistency with development | Holdout expectancy at least 50% of the development walk-forward average (no collapse out-of-sample) |
| Drawdown | Historical max drawdown within the 10% kill-switch, and Monte Carlo 95th-percentile drawdown no worse than 15% |
| Beats random | Above the 95th percentile of random-entry runs |
| Beats benchmark | Return-to-max-drawdown ratio at least that of buy-and-hold NIFTYBEES over the same period |
| Cost stress | Expectancy still above zero at 2x costs and slippage |
| Robustness | Plateau test and entry-variant C both pass |

**Decision outcomes**
- **GO:** all criteria met. Proceed to forward paper trading (Section 9), not straight to real money.
- **INSUFFICIENT EVIDENCE:** too few trades to judge. Extend the data, widen the universe, or go straight to paper trading with no capital at risk.
- **NO-GO:** any key criterion fails. Do not adjust thresholds. The holdout is now used up; any revised strategy (`v1.1`) needs fresh data.

**Deliverable:** `reports/holdout_report.md`, generated only after `HOLDOUT_UNLOCK` exists, including the exact trial count and a plain-language verdict.

---

## 9. Phase 8: Forward paper trading

Backtests cannot catch live problems such as data timing, missed fills, and execution habits. Use the existing journal tools (`journal_add`, `journal_close`, `journal_list`, `journal_summary`).

- **Duration:** at least 4 to 8 weeks and at least 15 to 20 signals.
- **Log every signal**, including ones skipped or not filled, with the reason.
- **Compare against backtest expectations:** signal frequency, fill rate, actual vs modeled slippage, share of gap-through-stop events, and expectancy in R.
- **Operational checks:** did the nightly sync complete every day, did data arrive before the signals were needed, did any stale-data warning fire.
- **Pass condition:** results within the backtest's confidence range, no unexplained operational failures, and no systematic fill shortfall.
- **Optional next step:** a small-size live stage (for example 0.25% risk per trade) for another 4 to 8 weeks before moving to full size. This is Deb's decision.

---

## 10. Hand-off to deployment

Deployment is gated on a GO plus a clean paper-trading period. The architecture is local-first (Docker Compose, MCP over a local transport). Moving to a public cloud host is a scope change that the build instructions require the owner to approve, so make that decision explicitly. Before deploying:

- The staleness guard from Phase 1 is live and tested.
- The health endpoint is **shallow** (returns OK without querying the database, so it does not wake or keep the database busy) and exposes no market data.
- The remote MCP endpoint is authenticated and advisory-only, with no broker credentials and no order placement.
- Ingestion is scheduled and monitored. If cloud IPs are blocked by the data source, run ingestion from a scheduled job elsewhere and use the cloud database only as the store.
- Every nightly run records the latest ingested date, and a failure alert fires if it does not advance on a trading day.

---

## 11. Final report checklist

The final report must state, in plain language:

- [ ] Data range, universe, and known biases (survivorship, missing event data)
- [ ] Baseline and tuned results, side by side, development and holdout
- [ ] Number of configurations tried
- [ ] Every sanity-test result, including failures
- [ ] Expectancy in R with its confidence interval
- [ ] Costs as a share of gross P&L
- [ ] Drawdown (historical and Monte Carlo) vs the 10% kill-switch
- [ ] The GO / NO-GO / INSUFFICIENT EVIDENCE verdict against the pre-registered criteria
- [ ] What was **not** tested or not modeled