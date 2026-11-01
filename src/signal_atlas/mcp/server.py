"""
server.py - FastMCP Server for Signal Atlas.

Exposes read-only quantitative research tools over MCP (Model Context Protocol).
Per Section 2.2 of the Architecture, the MCP server is a thin adapter over ResearchService;
it does not contain core financial or risk logic and cannot execute broker orders or override risk rules.
"""

import datetime
from decimal import Decimal
import json
import logging
from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP

from signal_atlas.mcp.models import MCPResponseEnvelope
from signal_atlas.research.service import ResearchService, SUPPORTED_STRATEGIES

logger = logging.getLogger(__name__)

mcp = FastMCP("signal-atlas")
_service: Optional[ResearchService] = None


def get_research_service() -> ResearchService:
    global _service
    if _service is None:
        _service = ResearchService()
    return _service


def _parse_date(date_str: Optional[str]) -> Optional[datetime.date]:
    if not date_str:
        return None
    try:
        return datetime.datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format '{date_str}'. Expected format is YYYY-MM-DD.")


@mcp.tool()
def market_status(as_of_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Retrieves the latest data freshness, benchmark market regime (NIFTY 50 trend),
    and active risk parameters.

    Args:
        as_of_date: Optional historical market date (YYYY-MM-DD). If omitted, evaluates latest available data.
    """
    dt = _parse_date(as_of_date)
    svc = get_research_service()
    raw = svc.get_market_status(as_of_date=dt)
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


@mcp.tool()
def screen(
    strategy: str = "trend_pullback",
    as_of_date: Optional[str] = None,
    symbols: Optional[List[str]] = None,
    top_n: int = 15,
) -> Dict[str, Any]:
    """
    Screens NSE cash equities for swing trade setups matching a registered strategy on as_of_date.

    Args:
        strategy: Identifier of registered strategy (defaults to 'trend_pullback').
        as_of_date: Optional market date (YYYY-MM-DD). If omitted, screens latest trading session.
        symbols: Optional list of stock symbols to restrict screening to.
        top_n: Maximum number of ranked trade setups to return (default: 15).
    """
    if strategy not in SUPPORTED_STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy}'. Supported strategies: {list(SUPPORTED_STRATEGIES)}")

    dt = _parse_date(as_of_date)
    svc = get_research_service()
    raw = svc.screen(strategy_id=strategy, as_of_date=dt, symbols=symbols, top_n=top_n)
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


@mcp.tool()
def get_setup(
    symbol: str,
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrieves complete trade setup, deterministic position sizing, and risk checks for a specific stock.

    Args:
        symbol: NSE stock symbol (e.g. 'RELIANCE', 'TCS').
        as_of_date: Optional market date (YYYY-MM-DD). If omitted, evaluates latest trading session.
    """
    if not symbol or not symbol.strip():
        raise ValueError("Stock symbol is required.")

    clean_symbol = symbol.strip().upper()
    dt = _parse_date(as_of_date)
    svc = get_research_service()
    raw = svc.get_setup(symbol=clean_symbol, as_of_date=dt)
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


@mcp.tool()
def get_risk_flags(
    symbol: str,
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Audits surveillance status (ASM/GSM/circuits), corporate actions, and liquidity constraints for a stock.

    Args:
        symbol: NSE stock symbol (e.g. 'INFY', 'HDFCBANK').
        as_of_date: Optional market date (YYYY-MM-DD). If omitted, evaluates latest trading session.
    """
    if not symbol or not symbol.strip():
        raise ValueError("Stock symbol is required.")

    clean_symbol = symbol.strip().upper()
    dt = _parse_date(as_of_date)
    svc = get_research_service()
    raw = svc.get_risk_flags(symbol=clean_symbol, as_of_date=dt)
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


@mcp.tool()
def get_backtest(
    strategy: str = "trend_pullback",
) -> Dict[str, Any]:
    """
    Retrieves realistic historical backtest performance, execution assumptions, and benchmark comparisons.

    Args:
        strategy: Strategy identifier (default: 'trend_pullback').
    """
    if strategy not in SUPPORTED_STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy}'. Supported strategies: {list(SUPPORTED_STRATEGIES)}")

    svc = get_research_service()
    raw = svc.get_backtest(strategy_id=strategy)
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


@mcp.tool()
def portfolio_view() -> Dict[str, Any]:
    """
    Retrieves current portfolio cash, total equity, open positions count, open risk, and sector concentration.
    """
    svc = get_research_service()
    raw = svc.portfolio_view()
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


@mcp.tool()
def get_fundamentals_snapshot(symbol: str) -> Dict[str, Any]:
    """
    Retrieves company fundamentals and quarterly financial disclosures.
    (Note: Scheduled for integration in Phase 6; returns graceful advisory status).

    Args:
        symbol: NSE stock symbol.
    """
    clean_symbol = symbol.strip().upper() if symbol else ""
    svc = get_research_service()
    raw = svc.get_fundamentals_snapshot(symbol=clean_symbol)
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


@mcp.tool()
def get_filings(symbol: str, days: int = 30) -> Dict[str, Any]:
    """
    Retrieves official NSE corporate announcements and filings over trailing N days.
    (Note: Scheduled for integration in Phase 6; returns graceful advisory status).

    Args:
        symbol: NSE stock symbol.
        days: Trailing calendar days to scan (default: 30).
    """
    clean_symbol = symbol.strip().upper() if symbol else ""
    svc = get_research_service()
    raw = svc.get_filings(symbol=clean_symbol, days=days)
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


@mcp.tool()
def get_news(symbol: str, days: int = 30) -> Dict[str, Any]:
    """
    Retrieves verified news articles and discovery events for a company over trailing N days.
    (Note: Scheduled for integration in Phase 6; returns graceful advisory status).

    Args:
        symbol: NSE stock symbol.
        days: Trailing calendar days to scan (default: 30).
    """
    clean_symbol = symbol.strip().upper() if symbol else ""
    svc = get_research_service()
    raw = svc.get_news(symbol=clean_symbol, days=days)
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


@mcp.tool()
def journal_add(
    symbol: str,
    signal_date: str,
    decision: str,
    planned_entry_price: float,
    planned_stop_loss: float,
    planned_target_price: float,
    planned_quantity: int,
    decision_reason: Optional[str] = None,
    actual_entry_date: Optional[str] = None,
    actual_entry_price: Optional[float] = None,
    actual_quantity: Optional[int] = None,
    strategy_id: str = "trend_pullback",
    notes: Optional[str] = None,
    tags: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Records a taken or skipped trade decision in the trade journal.
    Restricted write tool per Architecture Section 14.2: Writes strictly to trade journal,
    never places broker orders, never mutates market data or risk parameters.

    Args:
        symbol: NSE stock symbol (e.g. 'RELIANCE').
        signal_date: Signal generation date (YYYY-MM-DD).
        decision: Decision state: 'TAKEN' or 'SKIPPED'.
        planned_entry_price: Model planned entry reference price.
        planned_stop_loss: Model planned stop loss level.
        planned_target_price: Model planned profit target.
        planned_quantity: Model planned share quantity.
        decision_reason: Optional justification for taking or skipping setup.
        actual_entry_date: Optional actual fill date (YYYY-MM-DD). Defaults to signal_date + 1.
        actual_entry_price: Optional actual manual fill price. Defaults to planned_entry_price.
        actual_quantity: Optional actual manual fill quantity. Defaults to planned_quantity.
        strategy_id: Strategy identifier (default: 'trend_pullback').
        notes: Optional trade notes or execution observations.
        tags: Optional comma-separated tags.
    """
    clean_sym = symbol.strip().upper() if symbol else ""
    if not clean_sym:
        raise ValueError("Stock symbol is required")

    sig_dt = _parse_date(signal_date)
    if not sig_dt:
        raise ValueError("Signal date is required (format: YYYY-MM-DD)")

    act_entry_dt = _parse_date(actual_entry_date) if actual_entry_date else None

    svc = get_research_service()
    raw = svc.record_journal_decision(
        symbol=clean_sym,
        signal_date=sig_dt,
        decision=decision,
        planned_entry_price=Decimal(str(planned_entry_price)),
        planned_stop_loss=Decimal(str(planned_stop_loss)),
        planned_target_price=Decimal(str(planned_target_price)),
        planned_quantity=planned_quantity,
        decision_reason=decision_reason,
        actual_entry_date=act_entry_dt,
        actual_entry_price=Decimal(str(actual_entry_price)) if actual_entry_price is not None else None,
        actual_quantity=actual_quantity,
        strategy_id=strategy_id,
        notes=notes,
        tags=tags,
    )
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


@mcp.tool()
def journal_close(
    entry_id: str,
    exit_date: str,
    exit_price: float,
    exit_reason: str = "MANUAL",
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Closes an active OPEN journal trade with manual exit fill and calculates all-inclusive financial metrics.
    Restricted write tool per Architecture Section 14.2: Writes strictly to trade journal,
    never places broker orders, never mutates market data or risk parameters.

    Args:
        entry_id: Journal entry identifier (e.g. 'JRN-20241025-RELIANCE-abcd1234').
        exit_date: Execution exit date (YYYY-MM-DD).
        exit_price: Actual manual exit fill price.
        exit_reason: Reason for exit ('PROFIT_TARGET', 'STOP_LOSS', 'TIME_STOP', 'MANUAL', 'DISCRETIONARY').
        notes: Optional exit notes or post-trade review observations.
    """
    clean_id = entry_id.strip() if entry_id else ""
    if not clean_id:
        raise ValueError("Entry ID is required")

    exit_dt = _parse_date(exit_date)
    if not exit_dt:
        raise ValueError("Exit date is required (format: YYYY-MM-DD)")

    svc = get_research_service()
    raw = svc.close_journal_entry(
        entry_id=clean_id,
        exit_date=exit_dt,
        exit_price=Decimal(str(exit_price)),
        exit_reason=exit_reason,
        notes=notes,
    )
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


@mcp.tool()
def journal_list(
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lists trade journal entries filtered by status, symbol, or date range.

    Args:
        status: Optional lifecycle filter ('OPEN', 'CLOSED', 'SKIPPED', 'CANCELLED').
        symbol: Optional stock symbol filter.
        start_date: Optional start signal date (YYYY-MM-DD).
        end_date: Optional end signal date (YYYY-MM-DD).
    """
    svc = get_research_service()
    clean_sym = symbol.strip().upper() if symbol else None
    start_dt = _parse_date(start_date) if start_date else None
    end_dt = _parse_date(end_date) if end_date else None

    raw = svc.list_journal_entries(
        status=status,
        symbol=clean_sym,
        start_date=start_dt,
        end_date=end_dt,
    )
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


@mcp.tool()
def journal_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrieves aggregate paper-trading performance analytics across closed journal trades.

    Args:
        start_date: Optional start signal date (YYYY-MM-DD).
        end_date: Optional end signal date (YYYY-MM-DD).
    """
    svc = get_research_service()
    start_dt = _parse_date(start_date) if start_date else None
    end_dt = _parse_date(end_date) if end_date else None

    raw = svc.get_journal_summary(
        start_date=start_dt,
        end_date=end_dt,
    )
    envelope = MCPResponseEnvelope.create(
        as_of=raw["as_of"],
        data_status=raw["data_status"],
        warnings=raw["warnings"],
        result=raw["result"],
    )
    return envelope.model_dump(mode="json")


def run_stdio() -> None:
    """Runs the FastMCP server over standard input/output (stdio)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_stdio()
