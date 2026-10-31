# Signal Atlas
## Technical Architecture & Implementation Plan
**Version:** 1.0 — Draft for architecture review  
**Product type:** Personal stock research and swing-trading intelligence system  
**Market:** NSE cash equities  
**Trading style:** Delivery-only, end-of-day (EOD)  
**Primary interface:** MCP server and CLI  
**Deployment:** Local machine, PostgreSQL and Docker Compose

---

# 1. Product vision

Signal Atlas is a personal quantitative research system for discovering, evaluating, and monitoring potential NSE cash-equity swing trades.

It will combine exchange market data, corporate actions, historical prices, company disclosures, news, and portfolio information to produce explainable research outputs.

The system is intended to help answer:

- Which NSE-listed stocks currently satisfy my swing-trading strategy?
- What is the entry zone, invalidation level, target, and position size?
- What risks or corporate events could invalidate a setup?
- Is the broader market supportive of new long positions?
- How has this strategy performed historically after realistic transaction costs?
- Why did a particular signal pass or fail?
- How did my actual trades perform compared with the original setup?

Signal Atlas is a research and decision-support product. It will not place orders or independently manage investments.

## 1.1 Explicit trading constraints

| Area | Decision |
|---|---|
| Exchange | NSE initially |
| Segment | Cash equities |
| Data frequency | Daily EOD |
| Trading approach | Delivery-only swing trading |
| Intraday trading | Out of scope |
| Short selling | No executable short positions |
| Derivatives | Out of scope for initial release |
| Holding period | Configurable in trading sessions |
| Execution | Manual through broker |
| Initial deployment | Local |
| Primary broker integration | Zerodha Kite, optional/read-only |
| Primary market-data source | NSE reports and archives |

Possible signal states:

- `BUY`: New delivery purchase candidate.
- `HOLD`: Continue holding an existing position.
- `EXIT`: Consider exiting an existing holding.
- `AVOID`: No new position recommended by the system.
- `BEARISH_WATCH`: Negative outlook for research purposes only; never an executable cash short.

The system must never recommend an `EXIT` as though a position exists without checking the user's holdings or journal context.

---

# 2. Architectural principles

### 2.1 Deterministic core, LLM at the edges

All numerical operations must be performed by deterministic Python code.

Python is responsible for:

- Technical indicators and quantitative features.
- Liquidity calculations and universe selection.
- Strategy conditions and signal generation.
- Entry, stop, target, and risk/reward calculations.
- Position sizing.
- Brokerage, taxes, and slippage.
- Backtesting and performance statistics.
- Data validation and freshness checks.

The LLM is responsible for:

- Explaining quantitative results.
- Summarising company announcements and filings.
- Identifying relevant news and possible catalysts.
- Highlighting contradictions between sources.
- Producing research narratives and pre-trade checklists.

The LLM must not calculate or modify a trade plan, change risk limits, or override a failed validation.

### 2.2 Core library independent of MCP

The complete research engine must function without an MCP server.

The same business logic should be accessible through:

1. Python modules.
2. A command-line interface.
3. MCP tools.

MCP is an interface layer, not the application architecture itself.

### 2.3 Provenance and reproducibility

Every important dataset and research result must be traceable.

Persist:

- Source name and source URL/reference.
- Exchange trading date (`as_of`).
- Retrieval timestamp (`retrieved_at`).
- Original source-file hash.
- Parser and transformation version.
- Relevant warnings and validation results.
- Strategy identifier and version.
- Backtest parameters and transaction-cost model version.

Never silently replace original exchange data with corrected or adjusted values.

### 2.4 Risk controls are enforced in code

Risk rules belong in configuration and the risk engine.

MCP tools and LLM prompts cannot override them.

### 2.5 Fail safely, not indiscriminately

Data quality must be evaluated separately by domain.

Examples:

- Stale prices: block new setups.
- Incomplete corporate-action adjustments for a stock: block signals for that stock.
- Failed news ingestion: allow technical screening with a warning, unless the selected strategy depends on news.
- Missing pledge data: report `UNKNOWN`, never interpret it as no pledge risk.
- Missing historical fundamentals: show unavailable rather than inventing a value.

---

# 3. High-level architecture

```text
                 EXTERNAL DATA SOURCES
 ┌──────────────────────────────────────────────────────┐
 │                                                      │
 │  NSE EOD Bhavcopy       NSE Corporate Actions        │
 │  NSE Security Files     NSE Delivery Reports         │
 │  NSE/BSE Filings        RSS / News Sources            │
 │  Zerodha Kite           (Holdings - optional)         │
 │                                                      │
 └──────────────────────────┬───────────────────────────┘
                            │
                            ▼
 ┌──────────────────────────────────────────────────────┐
 │                 DATA INGESTION LAYER                  │
 │                                                      │
 │  Download → Archive → Parse → Normalize → Validate   │
 │                                                      │
 │  Source hashes, ingestion logs, quality checks       │
 └──────────────────────────┬───────────────────────────┘
                            │
                            ▼
 ┌──────────────────────────────────────────────────────┐
 │                  POSTGRESQL DATABASE                  │
 │                                                      │
 │  Instruments      Raw Prices       Corporate Actions │
 │  Calendar         Adjustment Data  Signals           │
 │  Backtests        Trade Journal    Filings / News    │
 │                                                      │
 └──────────────────────────┬───────────────────────────┘
                            │
                            ▼
 ┌──────────────────────────────────────────────────────┐
 │                  SIGNAL ATLAS CORE                    │
 │                                                      │
 │  Point-in-Time Universe                              │
 │          ↓                                           │
 │  Indicators and Features                             │
 │          ↓                                           │
 │  Strategy Engine                                     │
 │          ↓                                           │
 │  Risk Engine                                         │
 │          ↓                                           │
 │  Trade Setup                                         │
 │                                                      │
 │  Independent Backtesting and Portfolio Modules      │
 └──────────────────────────┬───────────────────────────┘
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
       ┌─────────────────┐     ┌─────────────────┐
       │   MCP SERVER    │     │      CLI        │
       │                 │     │                 │
       │ Read-only tools │     │ Ingest          │
       │ Journal writes  │     │ Validate        │
       │ Research access │     │ Screen          │
       └────────┬────────┘     │ Backtest        │
                │              └─────────────────┘
                ▼
       ┌─────────────────┐
       │   LLM CLIENT    │
       │                 │
       │ Research        │
       │ Explanation     │
       │ News synthesis  │
       └─────────────────┘
```

The initial deployment will be a **modular monolith**, not distributed microservices.

---

# 4. Technology stack

| Component | Technology | Purpose |
|---|---|---|
| Language | Python 3.12 | Main application |
| Data processing | Pandas | EOD data and indicators |
| Database | PostgreSQL | Persistent market and research data |
| ORM | SQLAlchemy 2.x | Database access |
| Migrations | Alembic | Schema versioning |
| Validation | Pydantic | Input and output validation |
| MCP | FastMCP | LLM-facing tools |
| CLI | Typer | Development and operational commands |
| HTTP | HTTPX | Source integrations |
| Scheduling | Cron in worker container | Nightly processing |
| Logging | Structured Python logging | Operational visibility |
| Testing | Pytest | Unit and integration tests |
| Deployment | Docker Compose | Local services |

Start with Pandas rather than maintaining both Pandas and Polars. Consider Polars only if actual profiling shows that processing speed or memory usage is a problem.

**FastAPI is not required in the first release.** It can be added later if Signal Atlas needs a separate REST API or dashboard.

## 4.1 Docker Compose services

Initial services:

- `db`: PostgreSQL.
- `worker`: Scheduled ingestion and research jobs.
- `mcp`: MCP server.

The worker and MCP server can use the same Python application image with different entry points.

A developer should also be able to run the CLI directly in the local Python environment.

---

# 5. Market-data strategy

## 5.1 Primary source: NSE EOD reports

NSE should be the source of truth for the initial price dataset.

Candidate sources:

1. CM-UDiFF Common Bhavcopy Final.
2. NSE Security-wise Delivery Positions.
3. NSE listed-security and security-master files.
4. NSE corporate-action records.
5. NSE trading-holiday information.

BSE corporate disclosures can supplement company research, but BSE market-price ingestion is not part of the first release.

### Important implementation requirement

Before writing the production parser, perform a source-feasibility investigation.

Verify:

- Exact current report names.
- Exact download URLs and URL-generation behaviour.
- Daily file publication timing.
- Date selection and historical archive access.
- Actual file format and encoding.
- UDiFF field names and data types.
- Security identifier availability.
- Historical coverage, including older and subsequently delisted securities.
- Whether source terms permit the intended local use.

Do not hardcode an assumed URL pattern before testing it.

Keep source-specific download and parsing logic behind a provider interface so that changes to NSE's report layout do not affect the research engine.

## 5.2 Full listed-security history, not today's index constituents

The intended historical universe should be constructed from the full daily records of eligible listed securities, including instruments that subsequently became delisted.

Do not use today's Nifty 500 constituent list as the historical backtest universe.

Instead, derive universe membership from information available on each historical date.

### Initial liquidity-universe proposal

For a given trading date \(t\):

1. Identify eligible cash-equity instruments that existed on date \(t\).
2. Calculate traded value over the previous 126 trading sessions.
3. Calculate average or median daily traded value.
4. Apply a configurable liquidity threshold or select the top \(N\).
5. Apply price, trading-status, and other eligibility filters.
6. Generate the eligible universe for date \(t\).

All rolling calculations must use only information available on or before the relevant date.

The choice between average and median traded value, minimum history, liquidity threshold, and top-\(N\) size must remain configurable.

### Important caveat

This approach reduces survivorship bias only if the historical source data really includes subsequently delisted securities and the instrument history can be mapped correctly.

The source investigation must demonstrate this with at least one real security that was subsequently delisted.

If historical coverage is incomplete, the system must document the affected period and must not describe that backtest as survivorship-bias-free.

## 5.3 Instrument identity

Do not use ticker symbols as permanent primary keys.

Use an internal `instrument_id` to represent a specific tradeable security.

Maintain effective-dated identifiers such as:

- ISIN.
- Exchange.
- Trading symbol.
- Series.
- Listing and delisting dates.
- Name changes.
- Source-specific identifiers.

A symbol or ISIN can change during a company's lifecycle. Mergers and demergers can also create successor securities.

Corporate-action records should be capable of linking predecessor and successor instruments.

---

# 6. Database design

Use PostgreSQL with SQLAlchemy and Alembic.

Keep the initial schema small enough to implement and test, while leaving room for additional modules.

## 6.1 Core tables

| Table | Important fields | Purpose |
|---|---|---|
| `instruments` | instrument_id, name, status, listing_date, delisting_date | Internal security identity |
| `instrument_symbol_history` | instrument_id, exchange, symbol, ISIN, series, valid_from, valid_to | Effective-dated identifiers |
| `trading_calendar` | trade_date, is_trading_day, holiday_name | Exchange calendar |
| `daily_prices_raw` | instrument_id, trade_date, OHLC, volume, traded_value, source | Original EOD prices |
| `corporate_actions` | instrument_id, type, announcement_date, ex_date, ratios, cash_amount | Corporate events |
| `adjustment_factors` | instrument_id, effective_date, split_factor, action_hash, version | Reproducible adjustments |
| `ingestion_runs` | run_id, source, trade_date, file_hash, status, counts, validation_issues | Ingestion audit |
| `signals` | date, instrument_id, strategy, entry, stop, target, RR, version | Historical signal records |
| `backtest_runs` | strategy, parameters, dates, costs_version, code_version, metrics | Reproducible tests |
| `backtest_trades` | run_id, instrument_id, entry, exit, quantity, costs, P&L | Individual simulated trades |
| `journal` | signal_id, decision, reason, fills, exit, notes | Actual trading decisions |

## 6.2 Derived price data

Create a derived adjusted-price dataset or materialized table.

It must be rebuildable from:

- Immutable raw price records.
- Corporate actions.
- Versioned adjustment factors.
- An explicitly versioned adjustment algorithm.

Never overwrite the raw records.

## 6.3 Deferred tables

These can be added when their respective modules are implemented:

- `daily_delivery_stats`
- `fundamentals`
- `filings`
- `news`
- `risk_flags`
- `portfolio_snapshots`
- `strategy_definitions`

`ingestion_runs.validation_issues` can initially hold structured JSON validation results. A separate `data_quality_issues` table is not required until the volume or query requirements justify it.

---

# 7. Corporate actions and price adjustment

This requires particular care because a mistake can create artificial profits or losses in a backtest.

## 7.1 Keep three concepts separate

**A. Raw exchange prices**

Actual historical OHLC values reported by the exchange.

**B. Split/bonus-adjusted analytical prices**

Derived historical prices used for continuous technical analysis across splits and bonus issues.

**C. Trade accounting and execution prices**

The actual market prices and quantities applicable to a simulated or real position, with corporate actions explicitly applied.

These datasets must never be confused.

## 7.2 Indicator calculations

Technical indicators should use consistently split/bonus-adjusted historical OHLC values.

For example, a 1:2 split should not appear as an artificial 50% fall in an EMA or RSI input series.

Dividend adjustment should not be mixed into technical indicator prices for the initial swing strategy.

## 7.3 Simulated positions across corporate actions

A backtest must explicitly transform open positions on corporate-action dates.

For a split:

- Adjust the quantity by the split ratio.
- Adjust the economic cost basis per share.
- Transform stop and target levels consistently.
- Preserve the position's economic value, subject to market movement and execution costs.

The engine must not treat the mechanical price reduction as an actual trading loss.

For a bonus issue, apply the corresponding share entitlement and quantity transformation.

For dividends:

- Determine whether the position qualified for the entitlement using the applicable entitlement rules.
- Record the dividend receivable on the relevant ex-date.
- Credit cash on the payment date.
- Include the economic benefit in total-return accounting.

Complex events such as mergers, demergers, rights issues, and fractional entitlements should be explicitly modelled or excluded from affected backtest cases until supported.

## 7.4 Execution and exchange constraints

Use actual raw prices for simulated fills and exchange-specific constraints such as:

- Tick-size rounding.
- Price bands and circuit limits.
- Execution prices.
- Transaction costs.

Do not assume that adjusted prices are executable market prices.

---

# 8. Data ingestion and validation

## 8.1 Daily processing pipeline

```text
Check trading calendar
        ↓
Check NSE source availability
        ↓
Download original reports
        ↓
Store files and compute hashes
        ↓
Parse and normalize
        ↓
Validate source records
        ↓
Upsert instruments and identifiers
        ↓
Insert raw EOD prices
        ↓
Process corporate actions
        ↓
Rebuild affected adjusted data
        ↓
Recompute market features
        ↓
Run strategy screen
        ↓
Store run status and results
```

The job should wait for source-file availability and retry within a bounded window. It should not assume that an exchange report appears at a fixed time every day.

## 8.2 Validation rules

At minimum:

- Correct file format and expected fields.
- Valid trading date.
- Duplicate instruments or duplicate daily records.
- Zero, negative, or otherwise invalid prices.
- OHLC consistency.
- Unexpected volume or traded-value values.
- Significant price movements.
- Corporate-action consistency.
- Unexpected missing or newly appearing instruments.
- Source-file completeness.

### Validation severity

Separate errors into:

- `FATAL`: The report or batch cannot be safely processed.
- `QUARANTINE`: One or more affected records or instruments cannot be trusted.
- `WARNING`: Suspicious but not necessarily invalid.
- `INFO`: Non-blocking operational information.

A large one-day price move must not automatically fail the whole market batch. It could be a real movement, a corporate action, or a special trading condition.

Likewise, a security missing from yesterday's file is not automatically an error. It may be suspended, untraded, newly listed, or otherwise legitimately absent.

Use exchange reference data and trading status to determine whether a record was actually expected.

## 8.3 Freshness policy

Freshness should be checked against the last expected trading session, not the previous calendar day.

Each tool response should expose:

```json
{
  "as_of": "2026-10-30",
  "retrieved_at": "2026-10-30T19:45:00+05:30",
  "source": ["NSE"],
  "data_status": "VALID",
  "warnings": []
}
```

For combined research responses, expose freshness independently for each required data domain.

A failed news job must not automatically prevent an otherwise valid technical screen.

A stale price dataset or incomplete adjustment state must prevent a new BUY setup.

---

# 9. Research and quantitative engine

## 9.1 Point-in-time universe

The universe module should provide a function conceptually equivalent to:

`get_universe(as_of_date, universe_config)`

It must be deterministic and use only information available on that date.

Universe configuration should control:

- Eligible exchange and security series.
- Excluded instruments.
- Minimum historical sessions.
- Minimum traded value.
- Maximum number of constituents.
- Minimum share price, where appropriate.
- Treatment of suspended or restricted securities.

Start with ordinary NSE cash-equity instruments. Decide explicitly whether ETFs, REITs, InvITs, SME listings, partly-paid securities, and special series should be excluded.

## 9.2 Technical features

Initial daily indicators:

| Feature | Proposed calculation |
|---|---|
| EMA | 20-day and 50-day |
| RSI | 14-period |
| MACD | Standard configurable parameters |
| ATR | 14-period |
| Volume | 20-day average volume |
| Liquidity | Rolling traded value |
| Relative strength | Stock versus Nifty 50 |
| Support/resistance | Deterministic price-based method |
| Weekly trend | Aggregated daily data |

Weekly candles should be derived consistently from daily records.

Delivery percentage is intentionally deferred until a strategy demonstrates that it needs this input.

## 9.3 Strategy interface

A strategy must be a pure calculation over prepared data.

It must not make API calls or perform database I/O.

Conceptual interface:

```python
generate_candidates(
    market_context,
    universe,
    strategy_parameters
) -> list[Candidate]
```

Each strategy must have:

- Stable strategy ID.
- Version.
- Explicit parameters.
- Entry conditions.
- Invalidation conditions.
- Stop methodology.
- Target methodology.
- Maximum holding period.
- Required data fields.

Keep strategy parameters few and understandable.

The first strategy should be selected only after the historical dataset and indicator calculations are validated. Candidate strategies can include trend-following pullbacks or breakouts, but neither should be assumed to have an edge without testing.

---

# 10. Risk engine and trade setups

The risk engine is a mandatory gate between strategy output and a published trade setup.

## 10.1 Configurable rules

- Capital available.
- Risk budget per trade.
- Maximum concurrent positions.
- Maximum total open risk.
- Sector concentration limit.
- Minimum reward-to-risk ratio.
- Maximum holding period.
- Liquidity threshold.
- Maximum entry deviation.
- Market-regime restrictions.
- Transaction-cost assumptions.

Avoid hardcoding personal risk limits into the strategy code.

## 10.2 Position sizing

Calculate quantity using both risk capacity and available capital.

Conceptually:

\[
Q_{\text{risk}} =
\left\lfloor
\frac{\text{Risk Budget}}
{\text{Entry Price}-\text{Stop Price}}
\right\rfloor
\]

\[
Q_{\text{capital}} =
\left\lfloor
\frac{\text{Available Capital}}
{\text{Entry Price}}
\right\rfloor
\]

\[
Q = \min(Q_{\text{risk}}, Q_{\text{capital}})
\]

The implementation must also account for applicable tick sizes, estimated transaction costs, and any relevant trading constraints.

## 10.3 Hard risk exclusions

Initial exclusions or veto conditions should cover:

- ASM/GSM or other configured surveillance restrictions.
- Insufficient liquidity.
- Upcoming results inside the intended holding window.
- Unacceptable pledge-related risk, where reliable data exists.
- Incomplete corporate-action adjustment.
- Stale price data.
- Poor reward-to-risk after the actual entry assumption.
- Market-regime conditions prohibiting new longs.

Unknown risk information must remain explicitly unknown.

Where a risk input is mandatory for a particular strategy, unknown data should block the setup rather than silently pass.

## 10.4 Market-regime gate

Begin with a simple benchmark condition, for example:

- Nifty 50 relative to its 200-day moving average.
- Optional trend confirmation.
- Configurable permission for new long positions.

The regime module should be explainable and independently testable.

## 10.5 Trade setup output

A valid setup should return:

- Instrument and trading date.
- Signal state.
- Strategy and version.
- Entry zone.
- Stop-loss.
- Target.
- Reward-to-risk.
- Position quantity.
- Planned capital usage.
- Planned risk in rupees.
- Relevant portfolio exposure.
- Passed checks.
- Failed checks.
- Data provenance and warnings.

A setup should explain why it was rejected, not merely return `NO SIGNAL`.

---

# 11. Backtesting engine

Backtesting must be independent of the live signal interface.

## 11.1 Execution model

Initial execution assumptions:

1. Strategy features are computed using data available through the close of day \(t\).
2. A signal is generated after that close.
3. The simulated earliest entry is day \(t+1\).
4. The actual next-session opening price is used as the starting fill reference.
5. Entry slippage and transaction costs are applied.
6. Entry is rejected if a gap or price movement makes the setup invalid.

Example:

- Planned entry: ₹500.
- Planned stop: ₹480.
- Planned target: ₹540.
- Next-session open: ₹520.

The engine must recalculate reward-to-risk at ₹520.

If the entry no longer satisfies the configured risk rules, skip the trade rather than assuming it was filled at ₹500.

## 11.2 Daily OHLC ambiguity

If a daily candle touches both stop-loss and target, the order of execution is unknown.

Use the conservative assumption that the stop-loss was reached first.

If the market opens beyond the stop, do not assume an exit at the stop price. Use a realistic gap-through-stop execution assumption and apply slippage.

## 11.3 Transaction costs

Implement an effective-dated cost model.

Potential components:

- Brokerage.
- Securities Transaction Tax.
- Exchange transaction charges.
- GST.
- Stamp duty.
- SEBI charges.
- Depository participant charges on applicable sell transactions.
- Slippage.

Do not hardcode today's rates into historical backtests.

Maintain source and effective-date information for each cost assumption. Verify the rates before treating backtest performance as credible.

## 11.4 Backtest safeguards

- No look-ahead bias.
- Point-in-time universe selection.
- Delisted securities retained where source history permits.
- Corporate actions applied correctly.
- Historical transaction costs.
- Realistic liquidity and gap assumptions.
- Walk-forward validation.
- A separate held-out evaluation period.
- No tuning on the final test period.
- Reproducible code and parameter versions.

## 11.5 Performance metrics

Report:

- Trade count.
- Win rate.
- Average winning trade.
- Average losing trade.
- Average R-multiple.
- Expectancy.
- Profit factor.
- Maximum drawdown.
- Sharpe ratio, with assumptions documented.
- Exposure time.
- Turnover.
- Benchmark comparison.
- Results across market regimes.

A trade count of around 100 can be a useful preliminary diagnostic threshold, but it is not proof of statistical significance or a profitable edge. Report uncertainty and sample limitations.

Every run must record:

- Strategy version.
- Parameters.
- Dataset version or source hashes.
- Code version/commit.
- Cost-model version.
- Date range.
- Execution assumptions.
- Performance results.

---

# 12. Portfolio and trade journal

## 12.1 Portfolio

Portfolio integration should initially be read-only.

Zerodha Kite can optionally provide long-term equity holdings. Store a timestamped snapshot so research can distinguish the actual holdings observed at one point in time from today's holdings.

Do not use the broker's intraday positions as the source of truth for the delivery-only research engine.

If broker integration is not available, allow manually maintained holdings.

## 12.2 Journal

The journal should record both taken and skipped signals.

For each signal:

- Taken or skipped.
- Reason.
- Planned entry and stop.
- Actual entry fill.
- Quantity.
- Actual exit fill.
- Exit date.
- Realized transaction costs.
- Realized P&L.
- Notes and observations.

The journal should allow comparing planned versus actual execution and studying behavioural errors.

Journal writes must never place orders or change broker holdings.

---

# 13. News, filings, and fundamentals

These are important modules, but they should not delay the first quantitative release.

## 13.1 Source priority

1. NSE corporate announcements.
2. BSE announcements where relevant.
3. Company investor-relations pages and filings.
4. Official regulatory and government announcements.
5. RSS feeds and other news sources for discovery.

A third-party article should not be treated as a substitute for an original regulatory filing when the original is available.

## 13.2 Data model

Eventually store:

- Document ID.
- Source.
- Original URL.
- Published timestamp.
- Retrieved timestamp.
- Associated instrument IDs.
- Original text or document reference.
- File/document hash.
- Event category.
- LLM-generated summary.
- Verification status.

Deduplicate using hashes, while retaining source references.

## 13.3 LLM safety

News articles and filing text must be considered untrusted input.

The LLM may summarize and classify them, but text inside a retrieved document must never be treated as an instruction to call tools, modify risk settings, reveal secrets, or perform an external action.

Summaries must remain linked to their original source documents.

The pre-trade research checklist should identify:

- Results announcements.
- Fundraising and dilution.
- Promoter pledges and stake sales.
- Material litigation.
- Regulatory actions.
- Mergers and acquisitions.
- Major contracts.
- Other material corporate developments.

Missing news should be labelled as unavailable, not as evidence that no negative news exists.

---

# 14. MCP interface

MCP is a thin adapter over the core Python package.

Tool outputs should use structured responses and consistently expose:

- `as_of`
- `retrieved_at`
- `source`
- `data_status`
- `warnings`
- `result`

## 14.1 Read-only tools

| Tool | Purpose |
|---|---|
| `market_status()` | Latest data status, market regime, and current risk summary |
| `screen(strategy, date)` | Stocks passing a selected strategy and its filters |
| `get_setup(symbol)` | Complete setup, sizing, risk checks, and rejection reasons |
| `get_risk_flags(symbol)` | Surveillance and corporate risk information |
| `get_fundamentals_snapshot(symbol)` | Latest available fundamental data with timestamps |
| `get_filings(symbol, days)` | Relevant company announcements and filing summaries |
| `get_news(symbol, days)` | News and associated source documents |
| `get_backtest(strategy)` | Previously stored backtest results |
| `portfolio_view()` | Holdings, open risk, and concentration |

Only registered strategies should be accepted by `screen`.

Backtests should be triggered through the CLI initially, not through conversational tool calls.

## 14.2 Restricted journal-write tools

Two narrowly scoped write tools:

- `journal_add(...)`
- `journal_close(...)`

These may modify the journal, but must not:

- Place an order.
- Modify a stop-loss at the broker.
- Change portfolio holdings.
- Modify risk configuration.
- Alter a historical backtest.
- Modify raw market data.

Journal events should be auditable and validated. An append-only event history is preferable to silently rewriting past trade decisions.

## 14.3 Explicit exclusions

Do not implement:

- Order placement.
- Automatic buying or selling.
- Intraday trading.
- Overnight naked cash short positions.
- Derivatives execution.
- LLM-controlled risk overrides.
- Autonomous portfolio rebalancing.

Initially expose MCP locally. Do not expose an unauthenticated server to the public internet.

---

# 15. Repository structure

Use a `src` layout and the package name `signal_atlas`.

```text
signal-atlas/
│
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── .env.example
├── .gitignore
├── README.md
│
├── alembic/
│   └── versions/
│
├── src/
│   └── signal_atlas/
│       │
│       ├── __init__.py
│       ├── config.py
│       ├── cli.py
│       │
│       ├── db/
│       │   ├── base.py
│       │   ├── session.py
│       │   ├── models/
│       │   └── repositories/
│       │
│       ├── providers/
│       │   └── nse/
│       │       ├── client.py
│       │       ├── bhavcopy.py
│       │       ├── security_master.py
│       │       └── corporate_actions.py
│       │
│       ├── ingestion/
│       │   ├── downloader.py
│       │   ├── parser.py
│       │   ├── normalizer.py
│       │   ├── pipeline.py
│       │   └── run_tracker.py
│       │
│       ├── quality/
│       │   ├── validation.py
│       │   ├── freshness.py
│       │   └── rules.py
│       │
│       ├── instruments/
│       │   └── identity.py
│       │
│       ├── calendar/
│       │   └── trading_calendar.py
│       │
│       ├── adjustments/
│       │   ├── factors.py
│       │   └── processor.py
│       │
│       ├── universe/
│       │   ├── liquidity.py
│       │   └── eligibility.py
│       │
│       ├── indicators/
│       │   ├── technical.py
│       │   ├── volume.py
│       │   └── relative_strength.py
│       │
│       ├── strategies/
│       │   ├── base.py
│       │   └── registry.py
│       │
│       ├── risk/
│       │   ├── engine.py
│       │   ├── position_sizing.py
│       │   ├── exclusions.py
│       │   └── costs.py
│       │
│       ├── backtesting/
│       │   ├── engine.py
│       │   ├── execution.py
│       │   ├── portfolio.py
│       │   └── metrics.py
│       │
│       ├── portfolio/
│       │   └── holdings.py
│       │
│       ├── journal/
│       │   └── service.py
│       │
│       ├── news/
│       ├── filings/
│       ├── fundamentals/
│       ├── ipo/
│       │
│       ├── mcp/
│       │   ├── server.py
│       │   └── tools/
│       │
│       └── jobs/
│           └── eod.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── backtesting/
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── reports/
│
└── docs/
    ├── architecture.md
    ├── data_dictionary.md
    ├── strategy_specifications/
    └── decisions/
```

Create modules as their corresponding milestones begin; do not create large numbers of empty modules in the initial commit.

The `data/` directory should be excluded from Git. Raw source files should be retained locally with their original filenames and hashes, subject to a documented retention policy.

---

# 16. Milestones and acceptance criteria

The project should progress through independently testable milestones.

## Milestone 0 — Data-source feasibility

**Goal:** Establish that the required historical NSE dataset is obtainable and usable.

Tasks:

- Identify current report names and download locations.
- Download sample current UDiFF files.
- Inspect field names and formats.
- Find historical archive coverage.
- Test access to several historical dates.
- Identify a security that later delisted.
- Confirm it exists in the relevant historical files.
- Inspect available corporate-action data.
- Record any licensing or usage restrictions.

**Exit:** A source and archive feasibility report with actual sample files, field mappings, known limitations, and a tested historical delisted-security example.

Do not promise five years of complete data before this investigation.

## Milestone 1A — Minimal EOD ingestion

**Goal:** Get the first real exchange data into PostgreSQL.

Tasks:

- Bootstrap the `signal_atlas` package.
- Create the initial PostgreSQL schema.
- Create the first Alembic migration.
- Implement instrument identity and symbol history.
- Download and parse one real UDiFF file.
- Store raw file and hash.
- Store normalized raw price records.
- Implement basic validation.
- Implement ingestion-run tracking.
- Add CLI ingestion command.

Example:

```bash
python -m signal_atlas.cli ingest --date 2026-10-30
```

**Exit:**

- A real NSE trading day can be ingested.
- Running ingestion twice does not create duplicate records.
- The original file is retained and hashed.
- Validation failures are recorded.
- The database can be queried for the ingested records.

## Milestone 1B — Historical data and adjustments

**Goal:** Build a defensible historical dataset.

Tasks:

- Import the verified historical price archive.
- Map historical identifiers to internal instruments.
- Ingest and process stock splits and bonus issues.
- Derive adjusted analytical prices.
- Add historical liquidity-universe queries.
- Add corporate-action unit tests.
- Test a security that was subsequently delisted.

**Exit:**

- A known split produces the expected adjusted historical prices and quantities.
- Raw prices remain unchanged.
- A point-in-time liquidity universe query works for a historical date.
- At least one subsequently delisted security is represented when the source archive supports it.
- Missing historical coverage is explicitly documented.

## Milestone 2 — First strategy and backtester

**Goal:** Validate one simple strategy rather than implement several untested strategies.

Tasks:

- Build daily technical indicators.
- Implement point-in-time liquidity filtering.
- Implement one strategy.
- Define next-session entry and realistic execution logic.
- Implement effective-dated transaction costs.
- Handle splits and dividends in open simulated positions.
- Add gap and stop/target ambiguity rules.
- Run walk-forward and held-out evaluation.

**Exit:**

The strategy either demonstrates encouraging out-of-sample evidence after costs or is documented as rejected and revised. No profitability claim should be made solely on the training period.

## Milestone 3 — Risk engine and trade setups

**Goal:** Turn strategy candidates into fully evaluated delivery setups.

Tasks:

- Implement capital and risk configuration.
- Implement position sizing.
- Add liquidity and market-regime filters.
- Add corporate-event and surveillance exclusions where data is reliable.
- Implement entry-gap validation.
- Generate complete setup explanations.

**Exit:**

Ten hand-calculated sample trade plans match the engine's outputs, including rounding, position size, costs, and rejection cases.

## Milestone 4 — MCP integration

**Goal:** Make the core research capabilities available to an LLM.

Tasks:

- Build FastMCP server.
- Implement read-only research tools.
- Implement structured responses and provenance.
- Implement domain-specific freshness guards.
- Add restricted journal tools.
- Test the complete `screen → setup → risk flags` flow.

**Exit:**

A supported MCP client can invoke the full research flow and receive consistent, reproducible outputs.

## Milestone 5 — Journal and paper trading

**Goal:** Compare modelled decisions with actual manual decisions.

Tasks:

- Add signal journal.
- Record taken and skipped setups.
- Record actual fills and exit information.
- Display planned versus realized risk and returns.
- Produce recurring performance reports.

**Exit:**

A couple of months of logged signals and decisions are available for analysis. Paper-trading results are reported separately from backtests.

## Milestone 6 — News, filings, and fundamentals

**Goal:** Add company-specific research context.

Tasks:

- Ingest NSE/BSE corporate announcements.
- Add RSS discovery sources.
- Deduplicate documents.
- Link documents to instruments.
- Generate source-linked summaries.
- Add fundamentals snapshots and pre-trade event checks.

**Exit:**

A company research query can retrieve relevant original filings, their timestamps, and clearly attributed summaries.

## Milestone 7 — IPO research

**Goal:** Add a separate IPO analysis module.

Cover:

- Fresh issue versus offer for sale.
- Price band and issue size.
- Lot size.
- Subscription data by investor category.
- Revenue, EBITDA, PAT, and debt.
- Valuation and listed-peer comparisons.
- Promoter holdings and dilution.
- Litigation and business risks.
- RHP/DRHP source documents.

GMP may be displayed as unofficial, source-attributed information only. It must never be treated as an official valuation or guaranteed listing indicator.

IPO candidates should not receive ordinary technical swing-trading signals before sufficient post-listing history exists.

---

# 17. Initial implementation priorities

The first implementation should NOT begin with indicators, LLM integration, or a trading strategy.

Recommended order:

1. Data-source feasibility investigation.
2. Repository bootstrap.
3. PostgreSQL schema and initial migration.
4. One-day NSE EOD ingestion.
5. Validation and idempotency.
6. Historical import and instrument identity.
7. Corporate-action adjustments.
8. Point-in-time liquidity universe.
9. One strategy and backtester.

The first meaningful vertical slice should demonstrate:

```text
NSE source file
      ↓
Download and archive
      ↓
Parse and validate
      ↓
PostgreSQL
      ↓
CLI query
      ↓
Verified EOD records
```

This gives Signal Atlas a working foundation before adding more complex research capabilities.

---

# 18. Important risks and unresolved design decisions

The following require explicit review before or during implementation.

| Question | Current proposal | What needs validation |
|---|---|---|
| Historical NSE coverage | Use full daily listed-security records | Confirm archive depth and delisted-security coverage |
| Security identity | Internal ID + effective-dated identifiers | ISIN changes, mergers, successor instruments |
| Liquidity universe | Trailing 126-session traded value | Average versus median; minimum data history |
| Eligible securities | NSE cash-equity series | ETFs, REITs, InvITs, SME, special series |
| Corporate actions | Split/bonus adjustment first | Rights, mergers, demergers, cash-in-lieu |
| Price completeness | Exchange reports + reference files | Suspensions and valid no-trade days |
| Delivery statistics | Deferred | Whether the first chosen strategy needs delivery % |
| Fundamentals | Primary filings first | Reliable source and historical availability |
| News | Exchange announcements before RSS | Source quality, deduplication, coverage |
| Pledge and surveillance flags | Mandatory where available | Authoritative source and freshness |
| Broker integration | Optional read-only holdings | Authentication and data availability |
| LLM connectivity | MCP adapter | Compatibility with intended client and local deployment |

---

# 19. Non-functional requirements

### Reliability

- Ingestion must be idempotent.
- Reprocessing a date must be safe.
- Original data must remain recoverable.
- Failed jobs must have explicit statuses.
- A failed pipeline must not publish fresh signals.

### Security

- API credentials must be stored outside source control.
- `.env` must be ignored by Git.
- Broker integration must initially be read-only.
- No order-placement endpoints or tool definitions.
- MCP should be local and authenticated if exposed over a network.

### Resource use

The first version must run on a personal laptop with 16 GB RAM.

Avoid Kafka, Kubernetes, distributed databases, and unnecessary services.

Historical processing should be incremental and batch-oriented.

### Maintainability

- Type annotations for core functions.
- Unit tests for financial calculations.
- Integration tests for ingestion and persistence.
- Versioned database migrations.
- Documented strategy definitions.
- No hidden calculations inside LLM prompts.

---

# 20. Architecture-review request

Please critically review this Signal Atlas proposal before implementation.

I want the review to focus on technical correctness, practical feasibility, overlooked edge cases, and whether the initial scope is achievable by one developer.

Please address these questions explicitly:

1. **Historical data feasibility:** Is NSE's daily listed-security data sufficient to construct a defensible point-in-time liquidity universe, including subsequently delisted stocks? What other sources or identity records are needed?

2. **Instrument identity:** Is an internal `instrument_id` with effective-dated symbol/ISIN history sufficient for symbol changes, ISIN changes, mergers, and demergers? What schema would you recommend?

3. **Corporate actions:** Is the proposed separation between raw prices, split/bonus-adjusted analytical prices, and trade accounting correct? What additional events or accounting cases must be handled before trusting backtests?

4. **Backtesting realism:** Are next-session opening fills, gap handling, daily stop/target ambiguity, price bands, transaction costs, and liquidity assumptions sufficiently realistic for an initial NSE swing strategy?

5. **Data validation:** Are the validation rules appropriate? Which checks should block an entire ingestion run, quarantine individual securities, or merely produce warnings?

6. **Point-in-time universe:** Is a 126-session traded-value universe a reasonable starting point? What biases can remain even with full historical security data?

7. **Database design:** Are any core tables missing, unnecessary, or incorrectly modelled? Pay particular attention to instrument identity, corporate actions, adjustment factors, and ingestion reproducibility.

8. **Architecture and stack:** Is a Python modular monolith with PostgreSQL, Pandas, FastMCP, CLI, and Docker Compose the right level of complexity for this project?

9. **Risk engine:** What mandatory rules are missing for delivery-only trading? How should unknown surveillance, pledge, or corporate-event data affect a setup?

10. **MCP design:** Are the proposed tools appropriately scoped? Are there security, state-management, or prompt-injection risks?

11. **Milestone feasibility:** Is Milestone 1 too large? Should historical ingestion, split adjustment, and liquidity-universe construction be split further?

12. **First implementation task:** What exactly should be built first, and what are its measurable acceptance tests?

### Please return your review in this format

- **Critical flaws:** Issues that could make results wrong or unsafe.
- **Important improvements:** Changes strongly recommended before implementation.
- **Optional improvements:** Useful, but not necessary for the MVP.
- **Incorrect assumptions:** Anything in this plan that is factually or technically questionable.
- **Revised Milestone 1:** A practical, testable scope.
- **Recommended first coding task:** Exact files/modules, responsibilities, and acceptance criteria.

Please do not redesign the entire system merely to make it more sophisticated. Prioritise a reliable, testable first release that one developer can realistically complete.

**The objective is not to build the most elaborate trading platform. It is to build a small, trustworthy research system whose data, calculations, and historical results can be independently verified.**