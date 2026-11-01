# Signal Atlas: Diagnostic Brief for the v2 Report (v4)

**Context:** the v2 verdict (NO-GO) is plausible and the process is much better (committed criteria, computed verdicts, NOT RUN labels, holdout kept locked). But several v2 numbers contradict each other. Do not rely on the v2 numbers, and do not start strategy rework, until Tasks A to G are done. `HOLDOUT_UNLOCK` stays uncreated.

## Findings

| ID | Finding | Evidence from the v2 report |
|---|---|---|
| F1 | **R-multiples and rupee P&L disagree by about 9x.** | Net return -3.18% on Rs 1,000,000 gives net P&L of about -Rs 31,800. Net PF 0.92 with 36 wins and 81 losses implies gross profit about Rs 365k and gross loss about Rs 397k: average win about Rs 10.2k, average loss about Rs 4.9k (payoff about 2.07, matching a 2:1 design). Expectancy in rupees is about -Rs 272 per trade, so about -0.06R if a loser is about -1R. The report says -0.487R. For -0.487R to be right, the average loser would have to be about -9R and the average winner about +18R. The implied rupee risk per R is about Rs 558, against an intended risk of about Rs 10,000 per trade. |
| F2 | **The random-entry baseline is impossible as reported.** | Random entries with symmetric ATR stops and targets should land around -0.1R to -0.3R after costs. The report shows a median of -2.05R (and -1.46R at p95). The strategy at -0.487R "beats" it. That says the simulation or the R-scale is broken, not that the strategy has an edge. |
| F3 | **Fold 1 looks implausible.** | 8.33% win rate (2 of 24 trades) in 2023-H1, a strong market, with a 2:1 payoff. v1 showed 48 trades and 52% on the same window. |
| F4 | **The attribution table is not a real attribution.** | Step 0 does not reproduce v1 (283 trades, +0.407R, DD 4.41%, +74.28% against v1's 387, +0.170R, DD 12.68%, +82.37%). Steps 1 to 6 are identical to the last digit, including max drawdown, although ranking, drawdown tracking, and sizing changes should alter some of them. Gross PF equals net PF (0.92), but gross must exceed net when costs are positive. |
| F5 | **Sweep point equal to baseline does not match baseline.** | Candidate 1 is 1.5 ATR stop with 2.0R target, which is the baseline configuration. It shows -0.737R. The baseline fold average is -0.884R. |
| F6 | **Selection accepts negative-edge configurations.** | All six candidates have negative mean expectancy. Two are "ACCEPTED" because they beat a worse baseline. The report uses a 90% CI where the plan says 95%. "Plateau retention" shows PASS with no number. |
| F7 | **An invented criterion and misapplied tests.** | The summary cites "Win Rate >= 40%" as pre-registered; it is not in the committed criteria. Robustness tests 2, 4, 5, and 6 are marked FAIL because the baseline expectancy is already negative. The delay result (-0.553R against -0.487R) is graceful degradation, not a failure. |
| F8 | **Claims without evidence.** | Section 5 explains H2 2024 with market narratives (October 2024 correction, regime lag) that nothing in the report tests. The tax line in Section 7 does not say whether tax was modeled. Task 1 evidence (universe print, count of later-delisted members) is missing. |
| F9 | **Next steps invite overfitting.** | Section 8 proposes adding RS, ADX, and trailing stops after seeing dev results. |

## Tasks

### A. Trade-level export (first)

Export all 117 v2 baseline trades to CSV: symbol, entry and exit dates, entry and exit price, quantity, stop, target, price, ATR as % of price, stop distance %, rupee risk (`risk_per_share × qty`), rupee risk as % of equity, gross P&L, costs in rupees and in R, net P&L, R-multiple, exit reason.

Then print and check:
- Sum of net P&L divided by sum of R, and the mean rupee risk per trade, against the intended 1% of equity.
- Average win, average loss, win rate, and payoff in both R and rupees. `win% × avg_win_R - loss% × avg_loss_R` must equal the reported expectancy.
- Distribution of stop distance %, position value, and rupee risk. Flag trades with tiny stop distance or tiny position size.
- The 10 trades with the largest absolute R.

**Acceptance:** R-based and rupee-based expectancy reconcile. If they do not, find and fix the R denominator or the sizing path, and rerun everything that used R.

### B. Random-entry sanity

- Add a unit test: a zero-drift random-walk price series, ATR stops at 1.5 and targets at 3.0, costs on. Expected R is about minus the cost in R (roughly -0.1R to -0.3R). The test must pass within a stated tolerance.
- Re-run the random-entry baseline. If it still shows around -2R, locate the cause (R denominator, stops, costs, sizing, or position handling).
- Re-evaluate "beats random" only after this passes.

### C. Reproduce v1, then a real attribution

- Check out the commit that produced v1 (3ce33ab) and confirm 387 trades, +0.170R, 82.37%.
- Run the one-fix-at-a-time attribution on one engine, with each fix controlled by a config flag. Every row is a separate logged run.
- Any step that shows no change must come with a diff of the trade lists and an explanation.

### D. Fold 1 investigation

Compare v1 and v2 for 2023-01-02 to 2023-06-30: universe size per month, signals per day, fills, the 24 trades, exit reasons, and the equal-weight universe return for the same window. Explain the 8.33% win rate.

### E. Sweep integrity and selection

- A grid point equal to baseline must reproduce baseline exactly (add this as a test).
- Log the full resolved configuration per run.
- A configuration is acceptable only if its own mean out-of-fold expectancy is above the committed threshold, not merely above baseline. If none qualifies, report "no acceptable configuration".
- Use the 95% CI of the improvement and print the plateau retention numbers.

### F. Report hygiene

- Remove the "Win Rate >= 40%" mention, or label it as an observation and not a criterion.
- For tests that depend on a passing baseline, report "NOT APPLICABLE: baseline fails" instead of FAIL.
- Remove or support with evidence every causal claim in Section 5 (compute market return, breadth, and volatility for the window).
- State plainly whether tax was modeled.

### G. Evidence for the point-in-time universe

Print the universe on 2022-03-01 and 2023-01-02: member count, ETFs excluded, and the number and names of members that later stopped trading. Confirm delisting tracking is used in the backtest path.

## Rules for any strategy rework (after A to G)

1. Any new rule or parameter is a new version (v1.1) with its own logged trials.
2. Declare the ideas to test before testing (no more than three), in a committed file.
3. Use the same walk-forward protocol and pre-registered criteria.
4. Consider extending the development history backward (if the Phase 0 archive coverage supports it) before adding rules. More trades and more market regimes help more than more filters.
5. The holdout stays locked and is used once, for the single final candidate. Do not spend it on v1.0.

## Definition of done

- R-based and rupee-based metrics reconcile, with a printed reconciliation.
- The random-entry baseline passes its sanity test.
- v1 is reproduced and the attribution is real.
- Every verdict follows from the committed criteria file.
- The holdout is still locked.