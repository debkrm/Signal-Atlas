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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
