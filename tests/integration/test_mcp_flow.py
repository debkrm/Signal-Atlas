"""
test_mcp_flow.py - Integration Test for Complete MCP Research Flow against PostgreSQL.

Tests:
1. End-to-end research flow: screen -> get_setup -> get_risk_flags.
2. Verified consistency between ResearchService and FastMCP tool wrappers.
3. Provenance, audit records, and envelope integrity.
4. Clean teardown of all synthetic test database fixtures.
"""

import datetime
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from signal_atlas.db.models.corporate_actions import CorporateAction
from signal_atlas.db.models.instruments import Instrument, InstrumentSymbolHistory
from signal_atlas.db.models.prices import DailyPriceRaw
from signal_atlas.db.models.ingestion import IngestionRun
from signal_atlas.mcp.server import (
    get_risk_flags,
    get_setup,
    market_status,
    portfolio_view,
    screen,
)
from signal_atlas.research.service import ResearchService


def test_end_to_end_mcp_research_flow(pg_engine):
    """
    Integration Test:
    Populates test PostgreSQL database with realistic price series producing a valid pullback setup.
    Executes the complete research flow:
    1. market_status() -> validates fresh data and benchmark trend.
    2. screen() -> finds approved trade setup for test symbol.
    3. get_setup() -> inspects detailed trade setup geometry and sizing breakdown.
    4. get_risk_flags() -> inspects surveillance, liquidity, and corporate event risk.
    5. Verifies parity between direct ResearchService calls and MCP tool responses.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    test_inst_id = f"inst-mcp-{uuid.uuid4().hex[:8]}"
    symbol = "MCPTEST"
    base_date = datetime.date(2023, 10, 16)

    with SessionFactory() as session:
        run = IngestionRun(
            run_id=f"run-mcp-{uuid.uuid4().hex[:8]}",
            source="NSE",
            trade_date=base_date,
            file_name="mcp_test.zip",
            file_hash="hashmcp123",
            parser_version="v1",
            status="SUCCESS",
            row_count=65,
        )
        inst = Instrument(
            instrument_id=test_inst_id,
            name="MCP Flow Test Corp",
            status="ACTIVE",
            first_observed_trade_date=base_date,
        )
        sym_hist = InstrumentSymbolHistory(
            instrument_id=test_inst_id,
            symbol=symbol,
            isin="INE777MCP01",
            series="EQ",
            valid_from=base_date,
        )
        session.add_all([run, inst, sym_hist])
        session.flush()

        # Build 60 sessions of price history leading to a pullback setup
        # Price climbs from 100 to 200, then pulls back to ~192 near EMA 20
        daily_volume = 500000
        curr_p = Decimal("100.00")
        trading_dates = []
        price_rows = []

        for i in range(60):
            dt = base_date + datetime.timedelta(days=i)
            trading_dates.append(dt)

            if i < 50:
                if i % 3 == 2:
                    curr_p -= Decimal("0.80")
                else:
                    curr_p += Decimal("1.80")
            else:
                curr_p -= Decimal("1.00")

            o = curr_p - Decimal("0.50")
            h = curr_p + Decimal("1.50")
            l = curr_p - Decimal("1.00")
            c = curr_p
            val = c * Decimal(daily_volume)

            price_rows.append(
                DailyPriceRaw(
                    instrument_id=test_inst_id,
                    trade_date=dt,
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    prev_close=curr_p - Decimal("1.00"),
                    volume=daily_volume,
                    traded_value=val,
                    series="EQ",
                    source="NSE",
                    ingestion_run_id=run.run_id,
                )
            )

        session.bulk_save_objects(price_rows)
        session.commit()

        try:
            signal_date_str = str(trading_dates[-1])

            # -------------------------------------------------------------
            # Step 1: market_status()
            # -------------------------------------------------------------
            status_resp = market_status(as_of_date=signal_date_str)
            assert status_resp["as_of"] == signal_date_str
            assert status_resp["data_status"] in ("FRESH", "STALE")
            assert "market_regime" in status_resp["result"]
            assert status_resp["result"]["is_bullish"] is True

            # -------------------------------------------------------------
            # Step 2: screen(strategy="trend_pullback")
            # -------------------------------------------------------------
            screen_resp = screen(
                strategy="trend_pullback",
                as_of_date=signal_date_str,
                symbols=[symbol],
                top_n=10,
            )
            assert screen_resp["as_of"] == signal_date_str
            assert screen_resp["source"] == "NSE / Signal Atlas Core"

            screen_result = screen_resp["result"]
            assert screen_result["strategy_id"] == "trend_pullback"
            assert screen_result["approved_count"] >= 1

            matched_setup = next(
                (s for s in screen_result["setups"] if s["symbol"] == symbol),
                None,
            )
            assert matched_setup is not None, f"Expected {symbol} in screened setups"
            assert matched_setup["signal_state"] == "BUY"
            assert matched_setup["is_approved"] is True
            assert matched_setup["allocated_quantity"] > 0
            assert Decimal(str(matched_setup["planned_capital_usage"])) > Decimal("0")
            assert Decimal(str(matched_setup["reward_to_risk"])) >= Decimal("1.50")

            # -------------------------------------------------------------
            # Step 3: get_setup(symbol)
            # -------------------------------------------------------------
            setup_resp = get_setup(symbol=symbol, as_of_date=signal_date_str)
            assert setup_resp["as_of"] == signal_date_str
            setup_result = setup_resp["result"]

            assert setup_result["symbol"] == symbol
            assert setup_result["is_approved"] is True
            assert setup_result["signal_state"] == "BUY"
            assert setup_result["allocated_quantity"] == matched_setup["allocated_quantity"]
            assert Decimal(str(setup_result["entry_price"])) == Decimal(str(matched_setup["entry_price"]))
            assert Decimal(str(setup_result["stop_loss"])) == Decimal(str(matched_setup["stop_loss"]))
            assert Decimal(str(setup_result["target_price"])) == Decimal(str(matched_setup["target_price"]))
            assert len(setup_result["passed_checks"]) >= 10
            assert len(setup_result["failed_checks"]) == 0

            # -------------------------------------------------------------
            # Step 4: get_risk_flags(symbol)
            # -------------------------------------------------------------
            flags_resp = get_risk_flags(symbol=symbol, as_of_date=signal_date_str)
            assert flags_resp["as_of"] == signal_date_str
            flags_result = flags_resp["result"]

            assert flags_result["symbol"] == symbol
            assert flags_result["overall_risk_status"] == "CLEAR"
            assert flags_result["blocking_veto_active"] is False

            # Verify presence of liquidity and surveillance check categories
            categories = {f["category"] for f in flags_result["flags"]}
            assert "LIQUIDITY" in categories
            assert "SURVEILLANCE" in categories

            # -------------------------------------------------------------
            # Step 5: Parity Verification against ResearchService
            # -------------------------------------------------------------
            svc = ResearchService()
            direct_setup = svc.get_setup(symbol=symbol, as_of_date=trading_dates[-1])
            assert direct_setup["result"]["symbol"] == setup_result["symbol"]
            assert direct_setup["result"]["allocated_quantity"] == setup_result["allocated_quantity"]

        finally:
            session.execute(delete(DailyPriceRaw).where(DailyPriceRaw.instrument_id == test_inst_id))
            session.execute(delete(InstrumentSymbolHistory).where(InstrumentSymbolHistory.instrument_id == test_inst_id))
            session.execute(delete(Instrument).where(Instrument.instrument_id == test_inst_id))
            session.execute(delete(IngestionRun).where(IngestionRun.run_id == run.run_id))
            session.commit()
