import datetime
from decimal import Decimal
import logging
import sys
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table

from signal_atlas.ingestion.pipeline import IngestionPipeline, PipelineError
from signal_atlas.research.service import ResearchService, SUPPORTED_STRATEGIES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)

app = typer.Typer(
    name="signal-atlas",
    help="Signal Atlas CLI - Personal Quantitative Research and Swing Trading System",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def callback() -> None:
    """Signal Atlas CLI - Personal Quantitative Research and Swing Trading System"""
    pass


@app.command("ingest")
def ingest(
    date_str: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help="Single trading date to ingest in YYYY-MM-DD format (e.g. 2024-10-25)",
    ),
    from_date_str: Optional[str] = typer.Option(
        None,
        "--from",
        help="Start date for range ingestion in YYYY-MM-DD format (e.g. 2022-01-01)",
    ),
    to_date_str: Optional[str] = typer.Option(
        None,
        "--to",
        help="End date for range ingestion in YYYY-MM-DD format (defaults to today if --from is given)",
    ),
    since_last: bool = typer.Option(
        False,
        "--since-last",
        help="Resume ingestion from the latest ingested trading date up to today (or --to)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force re-ingestion if date already exists in the database",
    ),
) -> None:
    """
    Ingest NSE historical Bhavcopy (Legacy and CM-UDiFF) into PostgreSQL.
    """
    # Validate arguments
    if not date_str and not from_date_str and not since_last:
        console.print("[red]Error:[/red] Specify --date YYYY-MM-DD, --from YYYY-MM-DD, or --since-last.", style="bold")
        raise typer.Exit(code=1)
    if date_str and (from_date_str or to_date_str or since_last):
        console.print("[red]Error:[/red] --date cannot be combined with --from, --to, or --since-last.", style="bold")
        raise typer.Exit(code=1)

    pipeline = IngestionPipeline()

    # 1. Single Date Mode
    if date_str:
        try:
            trade_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid date format '{date_str}'. Expected YYYY-MM-DD.", style="bold")
            raise typer.Exit(code=1)

        console.print(f"\n[cyan]Signal Atlas Ingestion[/cyan] -> Date: [bold]{trade_date}[/bold] (force={force})")
        try:
            result = pipeline.ingest_date(trade_date=trade_date, force=force)
        except PipelineError as e:
            console.print(f"\n[bold red]Ingestion Failed:[/bold red] {e}")
            raise typer.Exit(code=1)
        except Exception as e:
            console.print(f"\n[bold red]Unexpected Failure:[/bold red] {e}")
            raise typer.Exit(code=1)

        # Render summary table
        table = Table(title="Ingestion Run Summary", show_header=True, header_style="bold magenta")
        table.add_column("Property", style="dim", width=20)
        table.add_column("Value", style="bold")

        status_color = "green" if result["status"] in ("SUCCESS", "ALREADY_INGESTED") else "yellow"
        table.add_row("Status", f"[{status_color}]{result['status']}[/{status_color}]")
        table.add_row("Trade Date", str(result.get("trade_date")))
        table.add_row("Source", str(result.get("source", "N/A")))
        table.add_row("Run ID", str(result.get("run_id", "N/A")))
        table.add_row("File Name", str(result.get("file_name", "N/A")))
        table.add_row("SHA-256", str(result.get("file_hash", "N/A")))
        table.add_row("Records Persisted", str(result.get("row_count", 0)))
        table.add_row("Quarantined Records", str(result.get("quarantine_count", 0)))
        table.add_row("Warnings Count", str(result.get("warning_count", 0)))
        if "saved_archive" in result:
            table.add_row("Archive Path", str(result["saved_archive"]))
        if "message" in result:
            table.add_row("Notice", str(result["message"]))

        console.print(table)
        console.print("[bold green]Operation completed successfully.[/bold green]\n")
        return

    # 2. Since-Last Catch-Up Mode (with gap discovery)
    if since_last:
        start_date = None
        if from_date_str:
            try:
                start_date = datetime.datetime.strptime(from_date_str, "%Y-%m-%d").date()
            except ValueError:
                console.print(f"[red]Error:[/red] Invalid --from date format '{from_date_str}'. Expected YYYY-MM-DD.", style="bold")
                raise typer.Exit(code=1)

        target_date = None
        if to_date_str:
            try:
                target_date = datetime.datetime.strptime(to_date_str, "%Y-%m-%d").date()
            except ValueError:
                console.print(f"[red]Error:[/red] Invalid --to date format '{to_date_str}'. Expected YYYY-MM-DD.", style="bold")
                raise typer.Exit(code=1)

        console.print(
            f"\n[cyan]Signal Atlas Gap-Aware Catch-Up[/cyan] -> Scan: [bold]{start_date or 'Earliest Known'}[/bold] to [bold]{target_date or 'Today'}[/bold]"
        )
        try:
            results = pipeline.ingest_since_last(start_date=start_date, target_date=target_date, force=force)
        except PipelineError as e:
            console.print(f"\n[bold red]Catch-Up Failed:[/bold red] {e}")
            raise typer.Exit(code=1)

        _render_batch_summary(results)
        return

    # 3. Date Range Mode
    if from_date_str:
        try:
            start_date = datetime.datetime.strptime(from_date_str, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid --from date format '{from_date_str}'. Expected YYYY-MM-DD.", style="bold")
            raise typer.Exit(code=1)

        end_date = datetime.date.today()
        if to_date_str:
            try:
                end_date = datetime.datetime.strptime(to_date_str, "%Y-%m-%d").date()
            except ValueError:
                console.print(f"[red]Error:[/red] Invalid --to date format '{to_date_str}'. Expected YYYY-MM-DD.", style="bold")
                raise typer.Exit(code=1)

        console.print(
            f"\n[cyan]Signal Atlas Range Ingestion[/cyan] -> [bold]{start_date}[/bold] to [bold]{end_date}[/bold] (force={force})"
        )
        try:
            results = pipeline.ingest_range(start_date=start_date, end_date=end_date, force=force)
        except PipelineError as e:
            console.print(f"\n[bold red]Range Ingestion Failed:[/bold red] {e}")
            raise typer.Exit(code=1)

        _render_batch_summary(results)
        return


def _render_batch_summary(results: list[dict]) -> None:
    table = Table(title="Batch Ingestion Summary", show_header=True, header_style="bold magenta")
    table.add_column("Trade Date", style="bold", width=12)
    table.add_column("Status", width=16)
    table.add_column("Source", width=15)
    table.add_column("Rows", justify="right", width=8)
    table.add_column("Quarantined", justify="right", width=11)
    table.add_column("Notes", style="dim")

    total_rows = 0
    total_success = 0
    total_quarantined = 0
    total_skipped = 0
    total_missing = 0
    total_failed = 0

    for r in results:
        status = r.get("status", "UNKNOWN")
        rows = r.get("row_count", 0)
        total_rows += rows

        if status in ("SUCCESS", "ALREADY_INGESTED"):
            status_style = "green"
            total_success += 1
        elif status == "QUARANTINED":
            status_style = "yellow"
            total_quarantined += 1
        elif status in ("NON_TRADING_DAY", "EXCHANGE_HOLIDAY", "CONFIRMED_HOLIDAY", "UP_TO_DATE"):
            status_style = "yellow"
            total_skipped += 1
        elif status == "EXPECTED_DATA_MISSING":
            status_style = "magenta"
            total_missing += 1
        else:
            status_style = "red"
            total_failed += 1

        notes = r.get("message") or r.get("error") or r.get("file_name", "")
        table.add_row(
            str(r.get("trade_date")),
            f"[{status_style}]{status}[/{status_style}]",
            str(r.get("source", "-")),
            f"{rows:,}" if rows else "-",
            str(r.get("quarantine_count", 0)),
            notes[:40] if notes else "",
        )

    console.print(table)
    summary_parts = [
        f"[green]{total_success} successful[/green]",
    ]
    if total_quarantined:
        summary_parts.append(f"[yellow]{total_quarantined} quarantined[/yellow]")
    summary_parts.append(f"[yellow]{total_skipped} skipped/holidays[/yellow]")
    if total_missing:
        summary_parts.append(f"[magenta]{total_missing} data missing[/magenta]")
    if total_failed:
        summary_parts.append(f"[red]{total_failed} failed[/red]")

    console.print(
        f"[bold]Totals:[/bold] {', '.join(summary_parts)} | [cyan]{total_rows:,} total records[/cyan]\n"
    )


@app.command("market-status")
def market_status_command(
    date_str: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help="Market date to evaluate in YYYY-MM-DD format (defaults to latest available)",
    ),
) -> None:
    """
    Check data freshness, market regime (NIFTY 50 trend), and system risk parameters.
    """
    trade_date = None
    if date_str:
        try:
            trade_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid date format '{date_str}'. Expected YYYY-MM-DD.", style="bold")
            raise typer.Exit(code=1)

    svc = ResearchService()
    res = svc.get_market_status(as_of_date=trade_date)
    r = res["result"]

    table = Table(title=f"Market Status — As Of {res['as_of']}", show_header=True, header_style="bold magenta")
    table.add_column("Property", style="dim", width=24)
    table.add_column("Value", style="bold")

    regime_color = "green" if r["is_bullish"] else "yellow"
    status_color = "green" if res["data_status"] == "FRESH" else "yellow"

    table.add_row("Data Freshness", f"[{status_color}]{res['data_status']}[/{status_color}]")
    table.add_row("Market Regime", f"[{regime_color}]{r['market_regime']}[/{regime_color}]")
    table.add_row("Benchmark Symbol", str(r.get("benchmark_symbol", "N/A")))
    table.add_row("Benchmark Close", str(r.get("benchmark_close", "N/A")))
    table.add_row("Latest Ingested Date", str(r.get("latest_ingested_date", "N/A")))

    for k, v in r.get("risk_parameters", {}).items():
        table.add_row(f"Risk Param: {k}", str(v))

    console.print(table)
    if res["warnings"]:
        for w in res["warnings"]:
            console.print(f"[yellow]Notice:[/yellow] {w}")


GATE_DISPLAY_NAMES = {
    "STRATEGY_SIGNAL_VALID": "Strategy Technical Criteria (Trend, Alignment, RSI)",
    "VALID_STOP_LOSS": "Stop Loss Geometry (Below Entry & Positive)",
    "VALID_PROFIT_TARGET": "Profit Target Geometry (Above Entry)",
    "MARKET_REGIME_BULLISH": "Macro Market Regime Gate (Benchmark > EMA 50)",
    "MARKET_REGIME_BYPASSED": "Macro Market Regime Gate (Diagnostic Bypass)",
    "DRAWDOWN_KILLSWITCH_INACTIVE": "Portfolio Drawdown Kill-Switch (< 10%)",
    "NOT_ALREADY_HELD": "Position Duplication Filter (Not Already Held)",
    "CONCURRENT_POSITIONS_AVAILABLE": "Portfolio Capacity (< 10 Positions)",
    "OPEN_RISK_WITHIN_BUDGET": "Portfolio Open Risk Limit (<= 6.0% Total Equity)",
    "SECTOR_EXPOSURE_COMPLIANT": "Sector Exposure Limit (<= 30% Concentration)",
    "LIQUIDITY_SUFFICIENT": "Liquidity Threshold (20-day ADTV >= Rs. 5 Cr)",
    "SURVEILLANCE_CLEAR": "Surveillance Restrictions (No ASM/GSM/Circuit Penalties)",
    "SURVEILLANCE_ADVISORY": "Surveillance Check (Non-Restricted / Circular Advisory)",
    "EARNINGS_CLEAR": "Corporate Earnings Blackout (Outside Window)",
    "OPENING_GAP_WITHIN_TOLERANCE": "Opening Gap Boundary & Tolerance (<= 2%)",
    "REWARD_TO_RISK_SATISFIED": "Effective Reward-to-Risk Ratio (>= 1.50)",
}


@app.command("screen")
def screen_command(
    strategy: str = typer.Option("trend_pullback", "--strategy", "-s", help="Strategy identifier"),
    date_str: Optional[str] = typer.Option(None, "--date", "-d", help="Market date in YYYY-MM-DD format"),
    top_n: int = typer.Option(15, "--top", "-n", help="Maximum setups to display"),
    all_stocks: bool = typer.Option(False, "--all", "-a", help="Scan all active traded stocks (unbounded universe scan)"),
    ignore_regime: bool = typer.Option(False, "--ignore-regime", "-i", help="Bypass macro market regime gate for diagnostic screening"),
) -> None:
    """
    Screen securities for swing trade setups matching a strategy and passing all risk gates.
    """
    trade_date = None
    if date_str:
        try:
            trade_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid date format '{date_str}'. Expected YYYY-MM-DD.", style="bold")
            raise typer.Exit(code=1)

    svc = ResearchService()
    try:
        res = svc.screen(
            strategy_id=strategy,
            as_of_date=trade_date,
            top_n=top_n,
            scan_all=all_stocks,
            ignore_regime=ignore_regime,
        )
    except Exception as e:
        console.print(f"[bold red]Screen Failed:[/bold red] {e}")
        raise typer.Exit(code=1)

    r = res["result"]
    setups = r.get("setups", [])

    diag_notice = " [yellow](Diagnostic: Regime Ignored)[/yellow]" if ignore_regime else ""
    console.print(
        f"\n[cyan]Signal Atlas Screener[/cyan] — Strategy: [bold]{strategy}[/bold] | As Of: [bold]{res['as_of']}[/bold]{diag_notice}"
    )
    console.print(
        f"Screened Universe: {r.get('screened_universe_size', 0)} | Approved Candidates: [bold green]{r.get('approved_count', 0)}[/bold green]\n"
    )

    if not setups:
        console.print("[yellow]No approved trade setups found for the selected date and strategy.[/yellow]\n")
        return

    table = Table(title=f"Top Approved Setups (Ranked by Reward/Risk)", show_header=True, header_style="bold magenta")
    table.add_column("Symbol", style="bold cyan", width=12)
    table.add_column("State", width=8)
    table.add_column("Entry Ref", justify="right", width=11)
    table.add_column("Stop Loss", justify="right", width=11)
    table.add_column("Target", justify="right", width=11)
    table.add_column("R:R", justify="right", width=7)
    table.add_column("Quantity", justify="right", width=9)
    table.add_column("Capital (Rs.)", justify="right", width=14)
    table.add_column("Constraint", width=14)

    for s in setups:
        table.add_row(
            s["symbol"],
            "[green]BUY[/green]",
            f"Rs. {Decimal(str(s['entry_price'])):,.2f}",
            f"Rs. {Decimal(str(s['stop_loss'])):,.2f}",
            f"Rs. {Decimal(str(s['target_price'])):,.2f}",
            f"{Decimal(str(s['reward_to_risk'])):.2f}",
            f"{s['allocated_quantity']:,}",
            f"Rs. {Decimal(str(s['planned_capital_usage'])):,.2f}",
            s.get("limiting_factor", "-"),
        )

    console.print(table)
    console.print()


@app.command("setup")
def setup_command(
    symbol: str = typer.Argument(..., help="NSE stock symbol (e.g. RELIANCE)"),
    date_str: Optional[str] = typer.Option(None, "--date", "-d", help="Market date in YYYY-MM-DD format"),
    ignore_regime: bool = typer.Option(False, "--ignore-regime", "-i", help="Bypass macro market regime gate for diagnostic setup evaluation"),
    next_open: Optional[float] = typer.Option(None, "--next-open", help="Simulate next-session opening fill price for gap execution R:R test"),
) -> None:
    """
    Evaluate full trade setup, position sizing, and risk audit for a specific stock.
    """
    trade_date = None
    if date_str:
        try:
            trade_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid date format '{date_str}'. Expected YYYY-MM-DD.", style="bold")
            raise typer.Exit(code=1)

    svc = ResearchService()
    eff_open = Decimal(str(next_open)) if next_open is not None else None
    res = svc.get_setup(symbol=symbol, as_of_date=trade_date, next_open=eff_open, ignore_regime=ignore_regime)
    s = res["result"]

    diag_note = " [yellow](Diagnostic: Regime Ignored)[/yellow]" if ignore_regime else ""
    console.print(f"\n[cyan]Trade Setup Audit[/cyan] — Symbol: [bold]{symbol.upper()}[/bold] | As Of: [bold]{res['as_of']}[/bold]{diag_note}\n")

    # Render Strategy Technical Conditions Checklist Table if available
    conds = s.get("condition_evaluations") or []
    if conds:
        table_cond = Table(title="Strategy Technical Conditions Audit", show_header=True, header_style="bold magenta")
        table_cond.add_column("Condition", style="bold", width=32)
        table_cond.add_column("Criteria", style="dim", width=34)
        table_cond.add_column("Actual / Observation", width=38)
        table_cond.add_column("Status", justify="center", width=8)

        for c in conds:
            status_str = "[bold green]PASS[/bold green]" if c.get("passed") else "[bold red]FAIL[/bold red]"
            table_cond.add_row(c.get("name", ""), c.get("criteria", ""), c.get("actual", ""), status_str)
        console.print(table_cond)
        console.print()

    if not s.get("is_approved"):
        console.print(f"[bold red]Signal State: {s.get('signal_state', 'AVOID')} (BLOCKED)[/bold red]")
        console.print(f"Primary Reason: [yellow]{s.get('primary_rejection_reason', 'Did not qualify')}[/yellow]\n")

        if s.get("entry_price"):
            table = Table(title="Calculated Technical Geometry (Execution Blocked)", show_header=True, header_style="bold magenta")
            table.add_column("Parameter", style="dim", width=22)
            table.add_column("Value", style="bold")
            table.add_row("Reference Entry", f"Rs. {Decimal(str(s['entry_price'])):,.2f}")
            table.add_row("Calculated Stop Loss", f"Rs. {Decimal(str(s['stop_loss'])):,.2f}")
            table.add_row("Calculated Target", f"Rs. {Decimal(str(s['target_price'])):,.2f}")
            table.add_row("Reward-to-Risk", f"{Decimal(str(s.get('reward_to_risk', '0.00'))):.2f}")
            table.add_row("Allocated Quantity", "0 (Blocked by Risk Gates)")
            console.print(table)

        if s.get("failed_checks"):
            console.print("\n[bold]Failed Gates:[/bold]")
            for fc in s["failed_checks"]:
                name = fc.get('name') or fc.get('check_id', 'Gate')
                msg = fc.get('message') or fc.get('explanation', '')
                console.print(f"  * [red][X][/red] {name}: {msg}")
        if s.get("passed_checks"):
            console.print(f"\n[bold green]Passed Risk Checks ({len(s['passed_checks'])} verified):[/bold green]")
            for pc in s["passed_checks"]:
                name = GATE_DISPLAY_NAMES.get(pc, pc)
                console.print(f"  * [green][v][/green] {name}")
        if res.get("warnings"):
            for w in res["warnings"]:
                console.print(f"[yellow]Advisory Notice:[/yellow] {w}")
        console.print()
        return

    table = Table(title="Setup Geometry & Sizing", show_header=True, header_style="bold magenta")
    table.add_column("Parameter", style="dim", width=22)
    table.add_column("Value", style="bold")

    table.add_row("Signal State", "[bold green]BUY[/bold green]")
    table.add_row("Strategy", f"{s.get('strategy_id')} ({s.get('strategy_version')})")
    table.add_row("Reference Entry", f"Rs. {Decimal(str(s['entry_price'])):,.2f}")
    table.add_row("Entry Zone", f"Rs. {Decimal(str(s['entry_zone_low'])):,.2f} - Rs. {Decimal(str(s['entry_zone_high'])):,.2f}")
    table.add_row("Stop Loss", f"Rs. {Decimal(str(s['stop_loss'])):,.2f}")
    table.add_row("Target Price", f"Rs. {Decimal(str(s['target_price'])):,.2f}")
    table.add_row("Reward-to-Risk", f"{Decimal(str(s['reward_to_risk'])):.2f}")
    table.add_row("Allocated Quantity", f"{s['allocated_quantity']:,} shares")
    table.add_row("Capital Allocation", f"Rs. {Decimal(str(s['planned_capital_usage'])):,.2f}")
    table.add_row("Planned Risk", f"Rs. {Decimal(str(s['planned_risk_amount'])):,.2f} ({Decimal(str(s['planned_risk_pct'])):.2%})")
    table.add_row("Binding Constraint", str(s.get("limiting_factor")))

    console.print(table)

    if s.get("passed_checks"):
        console.print(f"\n[bold green]Passed Risk Checks ({len(s['passed_checks'])} verified):[/bold green]")
        for pc in s["passed_checks"]:
            name = GATE_DISPLAY_NAMES.get(pc, pc)
            console.print(f"  * [green][v][/green] {name}")
    if res.get("warnings"):
        for w in res["warnings"]:
            console.print(f"[yellow]Advisory Notice:[/yellow] {w}")
    console.print()


@app.command("risk-flags")
def risk_flags_command(
    symbol: str = typer.Argument(..., help="NSE stock symbol (e.g. INFY)"),
    date_str: Optional[str] = typer.Option(None, "--date", "-d", help="Market date in YYYY-MM-DD format"),
) -> None:
    """
    Audit surveillance flags, corporate events, and liquidity restrictions for a stock.
    """
    trade_date = None
    if date_str:
        try:
            trade_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid date format '{date_str}'. Expected YYYY-MM-DD.", style="bold")
            raise typer.Exit(code=1)

    svc = ResearchService()
    res = svc.get_risk_flags(symbol=symbol, as_of_date=trade_date)
    r = res["result"]

    table = Table(title=f"Risk & Surveillance Audit — {symbol.upper()} ({res['as_of']})", show_header=True, header_style="bold magenta")
    table.add_column("Category", width=18)
    table.add_column("Severity", width=10)
    table.add_column("Audit Description")

    status_color = "red" if r.get("blocking_veto_active") else "green"
    console.print(f"\nOverall Risk Status: [{status_color}]{r.get('overall_risk_status')}[/{status_color}]\n")

    for f in r.get("flags", []):
        sev = f["severity"]
        sev_color = "red" if sev == "BLOCKING" else ("yellow" if sev == "WARNING" else "green")
        table.add_row(f["category"], f"[{sev_color}]{sev}[/{sev_color}]", f["description"])

    console.print(table)
    if res.get("warnings"):
        for w in res["warnings"]:
            console.print(f"[yellow]Notice:[/yellow] {w}")
    console.print()


@app.command("mcp")
def mcp_command() -> None:
    """
    Launch the Model Context Protocol (FastMCP) server over stdio.
    """
    from signal_atlas.mcp.server import run_stdio
    console.print("[cyan]Starting Signal Atlas FastMCP server on stdio transport...[/cyan]")
    run_stdio()


# -------------------------------------------------------------------------
# Trade Journal & Paper Trading Sub-CLI
# -------------------------------------------------------------------------
journal_app = typer.Typer(help="Trade journal and paper-trading management commands")
app.add_typer(journal_app, name="journal")


@journal_app.command("add")
def journal_add_command(
    symbol: str = typer.Argument(..., help="NSE stock symbol (e.g. RELIANCE)"),
    date_str: str = typer.Option(..., "--date", "-d", help="Signal date (YYYY-MM-DD)"),
    decision: str = typer.Option("TAKEN", "--decision", help="Decision: TAKEN or SKIPPED"),
    price: float = typer.Option(..., "--price", "-p", help="Planned entry reference price"),
    stop: float = typer.Option(..., "--stop", "-s", help="Planned stop loss price"),
    target: float = typer.Option(..., "--target", "-t", help="Planned target price"),
    qty: int = typer.Option(..., "--qty", "-q", help="Planned share quantity"),
    fill_price: Optional[float] = typer.Option(None, "--fill-price", help="Actual manual entry fill price (defaults to planned entry)"),
    fill_date: Optional[str] = typer.Option(None, "--fill-date", help="Actual fill date (YYYY-MM-DD)"),
    fill_qty: Optional[int] = typer.Option(None, "--fill-qty", help="Actual fill quantity (defaults to planned qty)"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="Reason for taking or skipping setup"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Trade execution notes"),
) -> None:
    """
    Log a trade decision (TAKEN or SKIPPED) to the paper-trading journal.
    """
    try:
        sig_date = datetime.datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid signal date '{date_str}'. Expected YYYY-MM-DD.", style="bold")
        raise typer.Exit(code=1)

    act_entry_dt = None
    if fill_date:
        try:
            act_entry_dt = datetime.datetime.strptime(fill_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid fill date '{fill_date}'. Expected YYYY-MM-DD.", style="bold")
            raise typer.Exit(code=1)

    svc = ResearchService()
    try:
        res = svc.record_journal_decision(
            symbol=symbol,
            signal_date=sig_date,
            decision=decision,
            planned_entry_price=Decimal(str(price)),
            planned_stop_loss=Decimal(str(stop)),
            planned_target_price=Decimal(str(target)),
            planned_quantity=qty,
            decision_reason=reason,
            actual_entry_date=act_entry_dt,
            actual_entry_price=Decimal(str(fill_price)) if fill_price is not None else None,
            actual_quantity=fill_qty,
            notes=notes,
        )
    except Exception as e:
        console.print(f"[red]Failed to record journal entry:[/red] {e}", style="bold")
        raise typer.Exit(code=1)

    e = res["result"]
    console.print(f"\n[green]Journal entry logged successfully![/green] ID: [bold]{e['entry_id']}[/bold]")

    table = Table(title=f"Journal Entry Summary — {e['symbol']} ({e['decision']})", show_header=True, header_style="bold cyan")
    table.add_column("Property", width=24)
    table.add_column("Value", width=36)

    table.add_row("Entry ID", e["entry_id"])
    table.add_row("Symbol", e["symbol"])
    table.add_row("Signal Date", str(e["signal_date"]))
    table.add_row("Decision / Status", f"{e['decision']} ({e['status']})")
    table.add_row("Planned Entry", f"Rs. {Decimal(e['planned_entry_price']):,.2f}")
    table.add_row("Planned Stop Loss", f"Rs. {Decimal(e['planned_stop_loss']):,.2f}")
    table.add_row("Planned Target", f"Rs. {Decimal(e['planned_target_price']):,.2f}")
    table.add_row("Planned Quantity", f"{e['planned_quantity']:,}")
    table.add_row("Planned Risk", f"Rs. {Decimal(e['planned_risk_amount']):,.2f}")
    table.add_row("Planned R:R", f"{Decimal(e['planned_reward_to_risk']):.2f}")

    if e.get("actual_entry_price") is not None:
        table.add_row("Actual Entry Fill", f"Rs. {Decimal(e['actual_entry_price']):,.2f} ({e['actual_entry_date']})")
        table.add_row("Actual Fill Quantity", f"{e['actual_quantity']:,}")
        slip = Decimal(e['entry_slippage'])
        slip_style = "green" if slip <= Decimal("0") else "yellow"
        table.add_row("Entry Slippage", f"[{slip_style}]Rs. {slip:+,.2f}[/{slip_style}]")

    if e.get("decision_reason"):
        table.add_row("Decision Reason", e["decision_reason"])
    if e.get("notes"):
        table.add_row("Notes", e["notes"])

    console.print(table)
    console.print()


@journal_app.command("close")
def journal_close_command(
    entry_id: str = typer.Argument(..., help="Journal entry ID (e.g. JRN-20241024-RELIANCE-abcd1234)"),
    price: float = typer.Option(..., "--price", "-p", help="Actual manual exit fill price"),
    date_str: str = typer.Option(..., "--date", "-d", help="Actual exit date (YYYY-MM-DD)"),
    reason: str = typer.Option("MANUAL", "--reason", "-r", help="Exit reason (PROFIT_TARGET, STOP_LOSS, TIME_STOP, MANUAL)"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Post-trade review / exit notes"),
) -> None:
    """
    Close an active OPEN journal trade with manual exit fill and calculate P&L.
    """
    try:
        exit_dt = datetime.datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid exit date '{date_str}'. Expected YYYY-MM-DD.", style="bold")
        raise typer.Exit(code=1)

    svc = ResearchService()
    try:
        res = svc.close_journal_entry(
            entry_id=entry_id,
            exit_date=exit_dt,
            exit_price=Decimal(str(price)),
            exit_reason=reason,
            notes=notes,
        )
    except Exception as e:
        console.print(f"[red]Failed to close journal entry:[/red] {e}", style="bold")
        raise typer.Exit(code=1)

    e = res["result"]
    console.print(f"\n[green]Journal trade closed successfully![/green] ID: [bold]{e['entry_id']}[/bold]")

    table = Table(title=f"Trade Realization Summary — {e['symbol']} ({e['status']})", show_header=True, header_style="bold green")
    table.add_column("Financial Metric", width=24)
    table.add_column("Realized Value", width=36)

    table.add_row("Symbol", e["symbol"])
    table.add_row("Holding Duration", f"{e['actual_entry_date']} -> {e['actual_exit_date']}")
    table.add_row("Entry Fill", f"Rs. {Decimal(e['actual_entry_price']):,.2f} x {e['actual_quantity']:,} shares")
    table.add_row("Exit Fill", f"Rs. {Decimal(e['actual_exit_price']):,.2f} ({e['exit_reason']})")

    gross_pnl = Decimal(e["realized_gross_pnl"])
    gross_style = "green" if gross_pnl >= Decimal("0") else "red"
    table.add_row("Gross P&L", f"[{gross_style}]Rs. {gross_pnl:+,.2f}[/{gross_style}]")

    table.add_row("Transaction Costs", f"Rs. {Decimal(e['realized_costs']):,.2f} (STT, Stamp, Exch, SEBI, GST)")

    net_pnl = Decimal(e["realized_net_pnl"])
    net_style = "bold green" if net_pnl >= Decimal("0") else "bold red"
    table.add_row("Net Realized P&L", f"[{net_style}]Rs. {net_pnl:+,.2f}[/{net_style}]")

    pnl_pct = Decimal(e["realized_pnl_pct"]) * Decimal("100.00")
    table.add_row("Return on Outlay", f"[{net_style}]{pnl_pct:+.2f}%[/{net_style}]")

    r_mult = Decimal(e["realized_r_multiple"])
    r_style = "bold green" if r_mult >= Decimal("0") else "bold red"
    table.add_row("Realized R-Multiple", f"[{r_style}]{r_mult:+.2f}R[/{r_style}] (vs planned risk Rs. {Decimal(e['planned_risk_amount']):,.2f})")

    if e.get("notes"):
        table.add_row("Review Notes", e["notes"])

    console.print(table)
    console.print()


@journal_app.command("list")
def journal_list_command(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (OPEN, CLOSED, SKIPPED, CANCELLED)"),
    symbol: Optional[str] = typer.Option(None, "--symbol", help="Filter by stock symbol"),
    start_date: Optional[str] = typer.Option(None, "--start", help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, "--end", help="End date (YYYY-MM-DD)"),
) -> None:
    """
    List logged trade decisions and active paper-trading positions.
    """
    start_dt = None
    if start_date:
        try:
            start_dt = datetime.datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid start date '{start_date}'.", style="bold")
            raise typer.Exit(code=1)

    end_dt = None
    if end_date:
        try:
            end_dt = datetime.datetime.strptime(end_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid end date '{end_date}'.", style="bold")
            raise typer.Exit(code=1)

    svc = ResearchService()
    res = svc.list_journal_entries(
        status=status,
        symbol=symbol,
        start_date=start_dt,
        end_date=end_dt,
    )
    entries = res["result"]["entries"]

    table = Table(title=f"Trade Journal Records ({len(entries)} entries)", show_header=True, header_style="bold magenta")
    table.add_column("Entry ID", width=22)
    table.add_column("Date", width=11)
    table.add_column("Symbol", width=10)
    table.add_column("Status", width=9)
    table.add_column("Planned Setup", justify="right")
    table.add_column("Fill / Exit", justify="right")
    table.add_column("Net P&L", justify="right")
    table.add_column("R-Mult", justify="right")

    for e in entries:
        stat = e["status"]
        stat_color = "yellow" if stat == "OPEN" else ("green" if stat == "CLOSED" else ("blue" if stat == "SKIPPED" else "dim"))

        plan_desc = f"{Decimal(e['planned_entry_price']):,.2f} | S:{Decimal(e['planned_stop_loss']):,.2f} | T:{Decimal(e['planned_target_price']):,.2f} ({e['planned_quantity']})"

        if stat == "CLOSED":
            fill_desc = f"{Decimal(e['actual_entry_price']):,.2f} -> {Decimal(e['actual_exit_price']):,.2f}"
            net = Decimal(e["realized_net_pnl"])
            net_style = "green" if net >= Decimal("0") else "red"
            net_str = f"[{net_style}]Rs. {net:+,.2f}[/{net_style}]"
            r = Decimal(e["realized_r_multiple"])
            r_str = f"[{net_style}]{r:+.2f}R[/{net_style}]"
        elif stat == "OPEN":
            fill_desc = f"Fill: {Decimal(e['actual_entry_price']):,.2f}"
            net_str = "[yellow]ACTIVE[/yellow]"
            r_str = "-"
        elif stat == "SKIPPED":
            fill_desc = "[blue]SKIPPED[/blue]"
            net_str = "-"
            r_str = "-"
        else:
            fill_desc = "[dim]CANCELLED[/dim]"
            net_str = "-"
            r_str = "-"

        table.add_row(
            e["entry_id"],
            str(e["signal_date"]),
            e["symbol"],
            f"[{stat_color}]{stat}[/{stat_color}]",
            plan_desc,
            fill_desc,
            net_str,
            r_str,
        )

    console.print()
    console.print(table)
    console.print()


@journal_app.command("summary")
def journal_summary_command(
    start_date: Optional[str] = typer.Option(None, "--start", help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, "--end", help="End date (YYYY-MM-DD)"),
) -> None:
    """
    Display comprehensive paper-trading performance scorecard and operational evidence.
    """
    start_dt = None
    if start_date:
        try:
            start_dt = datetime.datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid start date '{start_date}'.", style="bold")
            raise typer.Exit(code=1)

    end_dt = None
    if end_date:
        try:
            end_dt = datetime.datetime.strptime(end_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid end date '{end_date}'.", style="bold")
            raise typer.Exit(code=1)

    svc = ResearchService()
    res = svc.get_journal_summary(start_date=start_dt, end_date=end_dt)
    s = res["result"]

    table = Table(title="Paper-Trading Performance Scorecard (Architecture Section 12)", show_header=True, header_style="bold cyan")
    table.add_column("Category", width=24)
    table.add_column("Metric", width=24)
    table.add_column("Value", width=20, justify="right")

    # Signals & Activity
    table.add_row("Signals & Activity", "Total Logged Signals", str(s["total_signals_logged"]))
    table.add_row("Signals & Activity", "Taken Setups", str(s["taken_count"]))
    table.add_row("Signals & Activity", "Skipped Setups", str(s["skipped_count"]))
    table.add_row("Signals & Activity", "Active Open Trades", str(s["open_count"]))
    table.add_row("Signals & Activity", "Closed Trades", str(s["closed_count"]))
    table.add_row("Signals & Activity", "Cancelled Trades", str(s["cancelled_count"]))

    # Win / Loss Distribution
    table.add_row("Win/Loss Stats", "Winning Trades", str(s["win_count"]))
    table.add_row("Win/Loss Stats", "Losing Trades", str(s["loss_count"]))
    table.add_row("Win/Loss Stats", "Breakeven Trades", str(s["breakeven_count"]))
    table.add_row("Win/Loss Stats", "Win Rate", f"[bold]{Decimal(s['win_rate_pct']):.2f}%[/bold]")

    # Financial Performance
    table.add_row("Financial Realization", "Gross P&L", f"Rs. {Decimal(s['total_gross_pnl']):+,.2f}")
    table.add_row("Financial Realization", "Total Transaction Costs", f"Rs. {Decimal(s['total_realized_costs']):,.2f}")

    net_pnl = Decimal(s["total_net_pnl"])
    net_style = "bold green" if net_pnl >= Decimal("0") else "bold red"
    table.add_row("Financial Realization", "Net Realized P&L", f"[{net_style}]Rs. {net_pnl:+,.2f}[/{net_style}]")

    pf = f"{Decimal(s['profit_factor']):.2f}" if s.get("profit_factor") is not None else "N/A"
    table.add_row("Financial Realization", "Profit Factor", pf)

    # Multiples & Behavioral Metrics
    table.add_row("Trade Metrics", "Average Trade P&L", f"Rs. {Decimal(s['avg_trade_pnl']):+,.2f}")
    table.add_row("Trade Metrics", "Average Win", f"Rs. {Decimal(s['avg_win']):,.2f}")
    table.add_row("Trade Metrics", "Average Loss", f"Rs. {Decimal(s['avg_loss']):,.2f}")

    avg_r = f"{Decimal(s['avg_r_multiple']):+.2f}R" if s.get("avg_r_multiple") is not None else "N/A"
    table.add_row("Trade Metrics", "Average Realized R", avg_r)
    table.add_row("Operational Quality", "Average Holding Duration", f"{Decimal(s['avg_holding_days']):.1f} days")
    table.add_row("Operational Quality", "Average Entry Slippage", f"Rs. {Decimal(s['avg_entry_slippage']):+,.2f}")

    console.print()
    console.print(table)
    console.print()


@app.command("filings")
def filings_command(
    symbol: str = typer.Argument(..., help="Stock ticker symbol (e.g. RELIANCE)"),
    days: int = typer.Option(30, "--days", "-d", help="Trailing calendar days to query (default: 30)"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category (e.g. RESULTS, FUNDRAISING)"),
    date: Optional[str] = typer.Option(None, "--date", help="As-of reference date (YYYY-MM-DD)"),
) -> None:
    """
    Query official corporate announcements and regulatory filings for a company.
    """
    target_date = None
    if date:
        try:
            target_date = datetime.datetime.strptime(date.strip(), "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid date format '{date}'. Expected YYYY-MM-DD.", style="bold")
            raise typer.Exit(code=1)

    svc = ResearchService()
    res = svc.get_filings(symbol=symbol, days=days, category=category, as_of_date=target_date)

    if res["data_status"] in ("DATA_NOT_AVAILABLE", "DATA_UNAVAILABLE") or not res["result"]["filings"]:
        console.print(f"\n[yellow]No corporate filings found for {symbol.upper()} over trailing {days} days.[/yellow]")
        console.print("[dim]Negative evidence rule: Absence of disclosures does not prove absence of risk.[/dim]\n")
        return

    filings = res["result"]["filings"]
    table = Table(
        title=f"Corporate Filings & Disclosures -- {symbol.upper()} (Trailing {days} Days)",
        show_header=True,
        header_style="bold blue",
    )
    table.add_column("Published Date", width=14)
    table.add_column("Category", width=22)
    table.add_column("Title / Announcement", width=42)
    table.add_column("Source", width=8)
    table.add_column("Risk Flag", width=14, justify="center")

    for f in filings:
        risk_str = "[bold red]MATERIAL RISK[/bold red]" if f.get("is_material_risk") else "[green]NORMAL[/green]"
        pub_dt = str(f["published_at"])[:10]
        table.add_row(
            pub_dt,
            f.get("category", "GENERAL"),
            f.get("title", "")[:42],
            f.get("source", "NSE"),
            risk_str,
        )

    console.print()
    console.print(table)
    console.print()


@app.command("news")
def news_command(
    symbol: str = typer.Argument(..., help="Stock ticker symbol (e.g. RELIANCE)"),
    days: int = typer.Option(30, "--days", "-d", help="Trailing calendar days to query (default: 30)"),
    date: Optional[str] = typer.Option(None, "--date", help="As-of reference date (YYYY-MM-DD)"),
) -> None:
    """
    Query company news articles and discovery feed for a company.
    """
    target_date = None
    if date:
        try:
            target_date = datetime.datetime.strptime(date.strip(), "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid date format '{date}'. Expected YYYY-MM-DD.", style="bold")
            raise typer.Exit(code=1)

    svc = ResearchService()
    res = svc.get_news(symbol=symbol, days=days, as_of_date=target_date)

    if res["data_status"] in ("DATA_NOT_AVAILABLE", "DATA_UNAVAILABLE") or not res["result"]["news_items"]:
        console.print(f"\n[yellow]No news articles found for {symbol.upper()} over trailing {days} days.[/yellow]")
        console.print("[dim]Negative evidence rule: Absence of news does not prove absence of risk.[/dim]\n")
        return

    items = res["result"]["news_items"]
    console.print("\n[dim italic]Untrusted Data Notice: News articles are third-party strings and are not verified trade instructions.[/dim italic]")

    table = Table(
        title=f"Company News & Discovery Feed -- {symbol.upper()} (Trailing {days} Days)",
        show_header=True,
        header_style="bold green",
    )
    table.add_column("Published Date", width=14)
    table.add_column("Source", width=12)
    table.add_column("Headline", width=46)
    table.add_column("Sentiment", width=12, justify="center")

    for item in items:
        sent = item.get("sentiment") or "NEUTRAL"
        sent_style = "green" if sent == "POSITIVE" else ("red" if sent == "NEGATIVE" else "dim")
        pub_dt = str(item["published_at"])[:10]
        table.add_row(
            pub_dt,
            item.get("source", "NSE"),
            item.get("headline", "")[:46],
            f"[{sent_style}]{sent}[/{sent_style}]",
        )

    console.print(table)
    console.print()


@app.command("fundamentals")
def fundamentals_command(
    symbol: str = typer.Argument(..., help="Stock ticker symbol (e.g. RELIANCE)"),
    date: Optional[str] = typer.Option(None, "--date", help="As-of reference date (YYYY-MM-DD)"),
) -> None:
    """
    Query point-in-time financial fundamentals, valuation multiples, and promoter metrics.
    """
    target_date = None
    if date:
        try:
            target_date = datetime.datetime.strptime(date.strip(), "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid date format '{date}'. Expected YYYY-MM-DD.", style="bold")
            raise typer.Exit(code=1)

    svc = ResearchService()
    res = svc.get_fundamentals_snapshot(symbol=symbol, as_of_date=target_date)

    if res["data_status"] in ("DATA_NOT_AVAILABLE", "DATA_UNAVAILABLE"):
        console.print(f"\n[yellow]No fundamentals snapshot recorded for {symbol.upper()}.[/yellow]")
        console.print("[dim]Negative evidence rule: Absence of records does not prove absence of risk.[/dim]\n")
        return

    r = res["result"]
    table = Table(
        title=f"Company Financial Fundamentals -- {symbol.upper()} (As Of {r.get('as_of_date', 'N/A')})",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Fundamental Metric", width=26)
    table.add_column("Value", width=32, justify="right")

    rev = f"Rs. {Decimal(r['revenue']):,.2f}" if r.get("revenue") is not None else "N/A"
    table.add_row("Total Revenue", rev)

    ebitda = f"Rs. {Decimal(r['ebitda']):,.2f}" if r.get("ebitda") is not None else "N/A"
    table.add_row("EBITDA", ebitda)

    pat = f"Rs. {Decimal(r['pat']):,.2f}" if r.get("pat") is not None else "N/A"
    table.add_row("Profit After Tax (PAT)", pat)

    eps = f"Rs. {Decimal(r['eps']):,.2f}" if r.get("eps") is not None else "N/A"
    table.add_row("Diluted EPS", eps)

    pe = f"{Decimal(r['pe_ratio']):.2f}x" if r.get("pe_ratio") is not None else "N/A"
    table.add_row("Price-to-Earnings (P/E)", pe)

    pb = f"{Decimal(r['pb_ratio']):.2f}x" if r.get("pb_ratio") is not None else "N/A"
    table.add_row("Price-to-Book (P/B)", pb)

    roe = f"{Decimal(r['roe']) * Decimal('100.00'):.2f}%" if r.get("roe") is not None else "N/A"
    table.add_row("Return on Equity (ROE)", roe)

    de = f"{Decimal(r['debt_to_equity']):.2f}" if r.get("debt_to_equity") is not None else "N/A"
    table.add_row("Debt-to-Equity Ratio", de)

    prom_hold = f"{Decimal(r['promoter_holding_pct']) * Decimal('100.00'):.2f}%" if r.get("promoter_holding_pct") is not None else "N/A"
    table.add_row("Promoter Shareholding", prom_hold)

    if r.get("promoter_pledge_pct") is not None:
        pledge = Decimal(r["promoter_pledge_pct"])
        pledge_pct = pledge * Decimal("100.00")
        pledge_style = "bold red" if pledge > Decimal("0.25") else "green"
        pledge_val = f"[{pledge_style}]{pledge_pct:.2f}%[/{pledge_style}]"
    else:
        pledge_val = "[yellow]UNKNOWN[/yellow]"
    table.add_row("Promoter Pledge", pledge_val)

    table.add_row("Period Type", r.get("period_type", "ANNUAL"))
    table.add_row("Data Source", r.get("data_source", "NSE_ANNUAL_REPORT"))

    console.print()
    console.print(table)
    console.print()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
