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


def run_stdio() -> None:
    """Runs the FastMCP server over standard input/output (stdio)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_stdio()
