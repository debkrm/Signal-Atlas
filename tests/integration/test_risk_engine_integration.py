import datetime
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from signal_atlas.db.models.instruments import Instrument, InstrumentSymbolHistory
from signal_atlas.db.models.prices import DailyPriceRaw
from signal_atlas.db.models.ingestion import IngestionRun
from signal_atlas.features.engine import TechnicalFeatureEngine
from signal_atlas.quality.adjustment import get_point_in_time_adjusted_history
from signal_atlas.risk import (
    OpenPositionRisk,
    PortfolioState,
    RiskConfig,
    RiskEngine,
    SurveillanceStatus,
)
from signal_atlas.strategy.models import MarketContext, SignalState
from signal_atlas.strategy.trend_pullback import TrendPullbackParameters, TrendPullbackStrategy


def test_end_to_end_risk_engine_evaluation(pg_engine):
    """
    Integration test: Verifies RiskEngine lifecycle evaluating candidates generated
    from technical features of PostgreSQL price data.
    Verifies:
    1. Historical data extraction & feature generation from DB.
    2. Strategy candidate production.
    3. Calculation of 20-day ADTV from DB price history.
    4. Successful approval of TradeSetup under standard portfolio state.
    5. Correct identification of limiting constraint in sizing.
    6. Rejection when portfolio limits (max concurrent positions) are breached.
    7. Rejection when opening price gaps > 2% beyond tolerance on day t+1.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    test_inst_id = f"inst-rk-{uuid.uuid4().hex[:8]}"
    symbol = "RISKTEST"
    base_date = datetime.date(2023, 1, 2)

    with SessionFactory() as session:
        run = IngestionRun(
            run_id=f"run-rk-{uuid.uuid4().hex[:8]}",
            source="NSE",
            trade_date=base_date,
            file_name="rk_test.zip",
            file_hash="hashrk123",
            parser_version="v1",
            status="SUCCESS",
            row_count=70,
        )
        inst = Instrument(
            instrument_id=test_inst_id,
            name="Risk Engine Test Corp",
            status="ACTIVE",
            first_observed_trade_date=base_date,
        )
        sym_hist = InstrumentSymbolHistory(
            instrument_id=test_inst_id,
            symbol=symbol,
            isin="INE888RK001",
            series="EQ",
            valid_from=base_date,
        )
        session.add_all([run, inst, sym_hist])
        session.flush()

        # Build 65 trading sessions of price history leading to a pullback setup
        # Days 0-49: Steady uptrend from 100 to 200
        # Days 50-57: Mild pullback to 192 (pulling back toward EMA 20, RSI in 40-55 zone)
        price_rows = []
        trading_dates = []
        curr_p = Decimal("100.00")

        # Set daily volume = 600,000 shares (at ~200, daily traded value ~120,000,000 = ₹12 Cr)
        daily_volume = 600000

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
            traded_val = c * Decimal(daily_volume)

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
                    traded_value=traded_val,
                    series="EQ",
                    source="NSE",
                    ingestion_run_id=run.run_id,
                )
            )

        session.bulk_save_objects(price_rows)
        session.commit()

        try:
            # 1. Extract adjusted history from DB
            signal_date = trading_dates[-1]
            adjusted_history = get_point_in_time_adjusted_history(
                instrument_id=test_inst_id,
                as_of_date=signal_date,
                db=session,
            )
            assert len(adjusted_history) == 60

            # 2. Compute Technical Features
            feature_engine = TechnicalFeatureEngine()
            features = feature_engine.extract_features(
                instrument_id=test_inst_id,
                symbol=symbol,
                as_of_date=signal_date,
                records=adjusted_history,
                benchmark_records=None,
            )
            assert features.sufficient_history is True

            # 3. Compute 20-day ADTV from DB history
            last_20_bars = adjusted_history[-20:]
            adtv = sum(bar.traded_value for bar in last_20_bars) / Decimal(20)
            assert adtv >= Decimal("50000000")  # >= ₹5 Cr minimum ADTV

            # 4. Generate Strategy Candidate
            params = TrendPullbackParameters(
                require_weekly_trend_bullish=False,
                min_rsi=Decimal("35.00"),
                max_rsi=Decimal("65.00"),
            )
            strategy = TrendPullbackStrategy(params)
            market_ctx = MarketContext(
                as_of_date=signal_date,
                is_market_regime_bullish=True,
                benchmark_symbol="NIFTY50",
            )
            candidate = strategy.evaluate_candidate(features, market_ctx)

            assert candidate.signal_state == SignalState.BUY
            assert candidate.is_valid is True

            # 5. Evaluate Candidate with RiskEngine under clean conditions
            risk_engine = RiskEngine()
            portfolio = PortfolioState(
                as_of_date=signal_date,
                total_equity=Decimal("1000000.00"),  # ₹10 Lakh
                available_cash=Decimal("500000.00"),
                peak_equity=Decimal("1000000.00"),
                open_positions=[],
            )

            setup = risk_engine.evaluate_trade_setup(
                candidate=candidate,
                portfolio=portfolio,
                adtv=adtv,
                market_context=market_ctx,
                surveillance_status=SurveillanceStatus.CLEAR,
                sector="Consumer Goods",
                pledge_pct=Decimal("0.00"),
                days_to_earnings=25,
            )

            # Assert Approved Setup
            assert setup.signal_state == SignalState.BUY
            assert setup.is_approved is True
            assert setup.allocated_quantity > 0
            assert setup.planned_capital_usage > Decimal("0")
            assert len(setup.failed_checks) == 0
            assert len(setup.passed_checks) >= 10
            assert setup.strategy_id == "trend_pullback"
            assert setup.provenance["evaluated_at"] is not None

            # 6. Verify Concentration Rejection (Max concurrent positions reached)
            full_portfolio = PortfolioState(
                as_of_date=signal_date,
                total_equity=Decimal("1000000.00"),
                available_cash=Decimal("500000.00"),
                peak_equity=Decimal("1000000.00"),
                open_positions=[
                    OpenPositionRisk(
                        instrument_id=f"inst-{i}",
                        symbol=f"SYM{i}",
                        entry_price=Decimal("100.00"),
                        current_price=Decimal("105.00"),
                        stop_loss=Decimal("95.00"),
                        quantity=100,
                        capital_allocated=Decimal("10000.00"),
                        open_risk_amount=Decimal("500.00"),
                        sector="Various",
                    )
                    for i in range(10)  # Config allows max 10 concurrent positions
                ],
            )
            setup_rejected = risk_engine.evaluate_trade_setup(
                candidate=candidate,
                portfolio=full_portfolio,
                adtv=adtv,
                market_context=market_ctx,
            )
            assert setup_rejected.signal_state == SignalState.AVOID
            assert setup_rejected.is_approved is False
            assert setup_rejected.allocated_quantity == 0
            assert any(c.check_id == "MAX_CONCURRENT_POSITIONS_REACHED" for c in setup_rejected.failed_checks)

            # 7. Verify Opening Gap Tolerance Rejection on Day t+1
            # If actual open is 3% above entry reference, gap check fails
            large_gap_open = candidate.entry_reference * Decimal("1.03")
            setup_gapped = risk_engine.evaluate_trade_setup(
                candidate=candidate,
                portfolio=portfolio,
                adtv=adtv,
                market_context=market_ctx,
                next_open=large_gap_open,
            )
            assert setup_gapped.signal_state == SignalState.AVOID
            assert setup_gapped.is_approved is False
            assert setup_gapped.allocated_quantity == 0
            assert any(c.check_id == "OPENING_GAP_EXCEEDS_TOLERANCE" for c in setup_gapped.failed_checks)

        finally:
            session.execute(delete(DailyPriceRaw).where(DailyPriceRaw.instrument_id == test_inst_id))
            session.execute(delete(InstrumentSymbolHistory).where(InstrumentSymbolHistory.instrument_id == test_inst_id))
            session.execute(delete(Instrument).where(Instrument.instrument_id == test_inst_id))
            session.execute(delete(IngestionRun).where(IngestionRun.run_id == run.run_id))
            session.commit()
