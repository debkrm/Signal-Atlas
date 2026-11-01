# Accounting & Risk Specification

**Document Version:** 1.0.0  
**Status:** Canonical Reference & Specification  
**Scope:** Signal Atlas Quantitative Backtest Engine, Risk Engine, and Trade Accounting

---

## 1. Executive Summary

This specification defines the exact mathematical formulas, denominators, portfolio reconciliation rules, and precision requirements for trade accounting and risk management in Signal Atlas.

It formally resolves historical ambiguities identified in the Reliability Review Bundle:
1. **Unweighted Trade Expectancy vs. Portfolio Payoff Ratio:** Distinguishes the arithmetic mean of individual trade R-multiples from total net P&L divided by total rupee risk.
2. **Trade Risk Denominators:** Disentangles trade risk as a percentage of *equity immediately before entry* ($RupeeRisk / Equity_{entry}$) from portfolio risk relative to *initial capital* ($RupeeRisk / InitialCapital$).
3. **Floating-Point & Rounding Precision:** Enforces full-precision internal representation of realized R, restricting rounding exclusively to user-facing display layers.
4. **Near-Zero Denominator Protection:** Specifies strict minimum planned rupee risk thresholds to prevent odd-lot or microscopic denominators from inflating R-multiples.

---

## 2. Mathematical Definitions & Formulas

### 2.1 Trade-Level Quantities

For any closed trade $i \in \{1, \dots, N\}$:

| Variable | Symbol | Definition / Formula | Precision |
|---|---|---|---|
| Entry Price | $P_{entry}$ | Executed purchase price per share (including entry slippage) | Decimal (2 places) |
| Exit Price | $P_{exit}$ | Executed liquidation price per share (including exit slippage) | Decimal (2 places) |
| Quantity | $Q$ | Executed integer number of shares ($Q \in \mathbb{Z}^+$) | Integer |
| Initial Stop Loss | $SL_{initial}$ | Initial planned protective stop price | Decimal (2 places) |
| Initial Risk Per Share | $RPS$ | $P_{entry} - SL_{initial}$ ($RPS > 0$) | Decimal (4 places) |
| Initial Planned Rupee Risk | $Risk_{rupees}$ | $RPS \times Q$ | Decimal (2 places) |
| Entry Gross Value | $V_{entry}$ | $P_{entry} \times Q$ | Decimal (2 places) |
| Exit Gross Value | $V_{exit}$ | $P_{exit} \times Q$ | Decimal (2 places) |
| Gross P&L | $PnL_{gross}$ | $V_{exit} - V_{entry} = (P_{exit} - P_{entry}) \times Q$ | Decimal (2 places) |
| Entry Transaction Costs | $C_{entry}$ | Statutory charges + broker fees on entry | Decimal (2 places) |
| Exit Transaction Costs | $C_{exit}$ | Statutory charges + broker fees + DP charges on exit | Decimal (2 places) |
| Total Costs | $C_{total}$ | $C_{entry} + C_{exit}$ | Decimal (2 places) |
| Net P&L | $PnL_{net}$ | $PnL_{gross} - C_{total}$ | Decimal (2 places) |
| Realized R-Multiple | $R_i$ | $\frac{PnL_{net}}{Risk_{rupees}} = \frac{PnL_{net}}{(P_{entry} - SL_{initial}) \times Q}$ | Decimal (unrounded full precision) |
| Net Return on Position | $Return_{pos}$ | $\frac{PnL_{net}}{V_{entry}}$ | Decimal (4 places) |

---

### 2.2 Unweighted Trade Expectancy vs. Portfolio Payoff Ratio

A critical distinction must be maintained between per-trade statistical expectancy and portfolio aggregate risk payoff:

#### 1. Unweighted Mean Per-Trade Expectancy ($\bar{R}$):
$$\bar{R} = \frac{1}{N} \sum_{i=1}^{N} R_i = \frac{1}{N} \sum_{i=1}^{N} \frac{PnL_{net, i}}{Risk_{rupees, i}}$$
- **Meaning:** The expected R-multiple of an arbitrary setup drawn from the strategy's signal distribution.
- **Properties:** Equal weight given to each trade regardless of portfolio equity at entry or rupee risk magnitude.
- **Reporting Rule:** Reported in strategy validation and confidence intervals. Does NOT equal $\sum PnL / \sum Risk$.

#### 2. Risk-Weighted Portfolio Payoff Ratio ($\Pi_{portfolio}$):
$$\Pi_{portfolio} = \frac{\sum_{i=1}^{N} PnL_{net, i}}{\sum_{i=1}^{N} Risk_{rupees, i}}$$
- **Meaning:** Aggregate net rupees generated per aggregate rupee of planned risk deployed over the backtest.
- **Properties:** Weights trades in proportion to their rupee risk. If larger accounts take larger positions and win, $\Pi_{portfolio}$ exceeds $\bar{R}$; if smaller positions win and larger positions lose, $\Pi_{portfolio}$ can be negative even when $\bar{R}$ is positive.

#### 3. Why Positive Rupee P&L with Negative $\bar{R}$ is Mathematically Legitimate:
Consider two trades:
- Trade 1: Rupee risk = ₹2,000, Net P&L = +₹6,000 $\implies R_1 = +3.00 R$
- Trade 2: Rupee risk = ₹10,000, Net P&L = -₹4,000 $\implies R_2 = -0.40 R$
- Trade 3: Rupee risk = ₹10,000, Net P&L = -₹5,000 $\implies R_3 = -0.50 R$
- Trade 4: Rupee risk = ₹10,000, Net P&L = -₹6,000 $\implies R_4 = -0.60 R$
- $\sum PnL_{net} = +6,000 - 4,000 - 5,000 - 6,000 = -₹9,000$.
Conversely, if Trade 1 had risk ₹10,000 and P&L +₹20,000 ($+2.0 R$), while 3 small trades each had risk ₹1,000 and P&L -₹1,200 ($-1.2 R$ each):
- Total Net P&L = $+20,000 - 3,600 = +₹16,400$ (Positive Rupee P&L!)
- Mean Expectancy $\bar{R} = \frac{+2.0 - 1.2 - 1.2 - 1.2}{4} = \frac{-1.6}{4} = -0.40 R$ (Negative Expectancy!)

**Conclusion:** Divided rupees cannot be multiplied back to recover per-trade R unless all trades had an identical rupee risk. Dividends of total P&L by total R are strictly prohibited.

---

### 2.3 Explicit Denominators for Risk Percentages

To prevent diagnostic confusion, the denominator of every risk percentage must be named explicitly:

| Metric Name | Formula | Denominator | Purpose |
|---|---|---|---|
| `risk_pct_current_equity` | $\frac{Risk_{rupees}}{Equity_{entry}} \times 100$ | $Equity_{entry}$ (Marked-to-market portfolio equity immediately prior to order generation) | Enforces the 1.0% per-trade risk budget at entry |
| `position_pct_current_equity` | $\frac{V_{entry}}{Equity_{entry}} \times 100$ | $Equity_{entry}$ | Enforces the 20.0% capital concentration limit |
| `risk_pct_initial_capital` | $\frac{Risk_{rupees}}{InitialCapital} \times 100$ | $InitialCapital$ (Fixed ₹1,000,000) | Historical portfolio-normalized diagnostic only |
| `open_risk_pct_current_equity` | $\frac{\sum_{j \in Open} Risk_{rupees, j}}{Equity_{t}} \times 100$ | $Equity_{t}$ (Daily marked-to-market equity) | Enforces the 6.0% maximum total open risk constraint |

---

## 3. Portfolio Reconciliation & Daily Equity Ledger

### 3.1 Daily State Reconciliation Formula

For every trading session $t \in \{1, \dots, T\}$:
$$Equity_t = Cash_t + \sum_{j \in Open_t} (P_{ref, j, t} \times Q_j)$$

Where:
- $Cash_t$: Liquid unencumbered cash balance at close of session $t$.
- $Open_t$: Set of open positions held overnight into session $t+1$.
- $P_{ref, j, t}$: Mark-to-market reference price (closing price of session $t$, or last observed traded price if suspended/missing).
- $Q_j$: Quantity of shares held in position $j$.

### 3.2 Cash Flow Equation

The daily cash transition from session $t-1$ to $t$ satisfies:
$$Cash_t = Cash_{t-1} - \sum_{k \in Entries_t} (V_{entry, k} + C_{entry, k}) + \sum_{m \in Exits_t} (V_{exit, m} - C_{exit, m})$$

### 3.3 True Peak Equity & Drawdown Accounting

- **True Peak Equity ($Peak_t$):**
  $$Peak_t = \max(\text{InitialCapital}, \max_{\tau \le t} Equity_\tau)$$
  *Standing Rule:* True peak equity NEVER resets across the lifecycle of a continuous portfolio simulation.
- **Drawdown Percentage ($DD_t$):**
  $$DD_t = \frac{Peak_t - Equity_t}{Peak_t} \times 100\%$$

---

## 4. Edge-Case Protection: Micro-Positions & Near-Zero Denominators

If a trade enters with an abnormally tight stop (e.g. $P_{entry} = 100.00$, $SL = 99.95 \implies RPS = 0.05$), an odd-lot position or small capital allocation could yield $Risk_{rupees} \to 0$. A subsequent minor price fluctuation could generate an artificial $+50 R$ or $-50 R$ outlier.

### Safeguards Implemented:
1. **Minimum Trade Risk Filter:**
   $$Risk_{rupees} \ge 0.002 \times Equity_{entry} \quad (\text{Minimum 0.20\% of equity risk})$$
   Any candidate whose sized quantity produces less than 0.20% equity risk is rejected.
2. **Strict Non-Zero Risk Assertion:**
   In engine trade finalization, if $Risk_{rupees} \le \text{₹}1.00$, the trade is quarantined and raises an accounting error rather than dividing by near-zero.
3. **Execution Rounding Tolerance:**
   Quantities are rounded down via `floor` (`ROUND_DOWN`) to ensure cash and risk budgets are never exceeded by fractional odd-lots.

---

## 5. Machine-Readable Export Schema

The canonical trade ledger export (`reports/v2_baseline_trades.csv`) must provide the following columns:

```csv
trade_id,instrument_id,symbol,entry_date,exit_date,entry_price,exit_price,quantity,initial_stop_loss,initial_target_price,initial_risk_per_share,rupee_risk,equity_at_entry,risk_pct_current_equity,position_pct_current_equity,entry_fees,exit_fees,total_costs,gross_pnl,net_pnl,net_return_pct,realized_r,realized_r_unrounded,exit_reason,holding_sessions_count
```

- `realized_r`: Quantized to 2 decimal places strictly for human readability.
- `realized_r_unrounded`: Full-precision Decimal string used for bootstrap resampling and statistical metric computation.
