import datetime
import logging
import sys
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table

from signal_atlas.ingestion.pipeline import IngestionPipeline, PipelineError

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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
