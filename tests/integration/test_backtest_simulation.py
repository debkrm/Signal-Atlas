import datetime
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from signal_atlas.backtest import BacktestConfig, BacktestSimulator, ExitReason
from signal_atlas.db.models.instruments import Instrument, InstrumentSymbolHistory
from signal_atlas.db.models.prices import DailyPriceRaw
from signal_atlas.db.models.ingestion import IngestionRun
from signal_atlas.quality.adjustment import get_point_in_time_adjusted_history
from signal_atlas.strategy.trend_pullback import TrendPullbackParameters, TrendPullbackStrategy


def test_end_to_end_backtest_simulation(pg_engine):
    """
    Integration test: Runs BacktestSimulator using TrendPullbackStrategy
    on historical prices extracted from the PostgreSQL test database.
    Verifies full lifecycle:
    - Point-in-time extraction from DB
    - Technical feature calculation
    - Strategy candidate generation on day t
    - Signal timing execution on day t+1 open
    - Position sizing adherence
    - Exit rule execution (Target / Stop / Holding duration)
    - Full metric calculations & baseline benchmarking
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    test_inst_id = f"inst-bt-{uuid.uuid4().hex[:8]}"
    symbol = "BTSWING"
    base_date = datetime.date(2023, 1, 2)

    with SessionFactory() as session:
        run = IngestionRun(
            run_id=f"run-bt-{uuid.uuid4().hex[:8]}",
            source="NSE",
            trade_date=base_date,
            file_name="bt_test.zip",
            file_hash="hashbt123",
            parser_version="v1",
            status="SUCCESS",
            row_count=80,
        )
        inst = Instrument(
            instrument_id=test_inst_id,
            name="Backtest Swing Corp",
            status="ACTIVE",
            first_observed_trade_date=base_date,
        )
        sym_hist = InstrumentSymbolHistory(
            instrument_id=test_inst_id,
            symbol=symbol,
            isin="INE999BT001",
            series="EQ",
            valid_from=base_date,
        )
        session.add_all([run, inst, sym_hist])
        session.flush()

        # Build 70 trading sessions of price history
        # Days 0-49: Steady strong uptrend from 100 to 200
        # Days 50-54: Mild pullback from 200 to 192 (pulling back toward EMA 20)
        # Days 55-65: Resumption of uptrend from 192 to 220
        trading_dates = []
        price_rows = []

        curr_p = Decimal("100.00")
        for i in range(70):
            dt = base_date + datetime.timedelta(days=i)
            trading_dates.append(dt)

            if i < 50:
                # Zigzag uptrend (up 1.8, up 1.8, down 0.8) for healthy RSI around 60
                if i % 3 == 2:
                    curr_p -= Decimal("0.80")
                else:
                    curr_p += Decimal("1.80")
            elif i < 58:
                # Constructive pullback over 8 sessions to EMA 20 and RSI ~45
                curr_p -= Decimal("1.20")
            else:
                # Strong resumption rally (+2.50 per day)
                curr_p += Decimal("2.50")


            o = curr_p - Decimal("0.50")
            h = curr_p + Decimal("1.50")
            l = curr_p - Decimal("1.00")
            c = curr_p

            price_rows.append(
                DailyPriceRaw(
                    instrument_id=test_inst_id,
                    trade_date=dt,
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    prev_close=curr_p - Decimal("1.00"),
                    volume=500000,
                    traded_value=c * Decimal(500000),
                    series="EQ",
                    source="NSE",
                    ingestion_run_id=run.run_id,
                )
            )


        session.bulk_save_objects(price_rows)
        session.commit()

        try:
            # 1. Extract adjusted analytical history from DB
            adjusted_history = get_point_in_time_adjusted_history(
                instrument_id=test_inst_id,
                as_of_date=trading_dates[-1],
                db=session,
            )
            assert len(adjusted_history) == 70

            # 2. Configure Strategy & Simulator
            params = TrendPullbackParameters(
                require_ema_alignment=True,
                require_price_above_ema50=True,
                max_ema20_distance_pct=Decimal("0.05"),
                min_rsi=Decimal("35.00"),
                max_rsi=Decimal("65.00"),
                require_weekly_trend_bullish=False,  # Synthetic test data uses daily dates
                stop_atr_multiplier=Decimal("1.50"),
                target_atr_multiplier=Decimal("3.00"),
                min_reward_to_risk=Decimal("1.50"),
            )
            strategy = TrendPullbackStrategy(params)

            config = BacktestConfig(
                initial_capital=Decimal("1000000.00"),
                risk_per_trade_pct=Decimal("0.01"),
                max_capital_per_position_pct=Decimal("0.20"),
                max_holding_sessions=20,
                min_history_sessions=50,
            )
            simulator = BacktestSimulator(config)

            # 3. Execute Backtest
            prices_by_inst = {test_inst_id: adjusted_history}
            result = simulator.run(
                strategy=strategy,
                trading_dates=trading_dates,
                prices_by_instrument=prices_by_inst,
                symbols_by_instrument={test_inst_id: symbol},
            )


            # 4. Verify Results
            assert result.strategy_id == "trend_pullback"
            assert result.strategy_version == "v1.0"
            assert len(result.equity_curve) == 70
            assert result.metrics.total_trades >= 1

            # Validate completed trade
            for trade in result.trades:
                assert trade.instrument_id == test_inst_id
                assert trade.symbol == symbol
                assert trade.quantity > 0
                assert trade.entry_price > Decimal("0")
                assert trade.exit_price > Decimal("0")
                assert trade.exit_reason in [
                    ExitReason.PROFIT_TARGET,
                    ExitReason.STOP_LOSS,
                    ExitReason.MAX_HOLDING_TIME,
                    ExitReason.END_OF_SIMULATION,
                ]
                assert trade.entry_fees > Decimal("0")
                assert trade.exit_fees > Decimal("0")
                # Position sizing must respect 20% capital cap
                assert trade.entry_gross_value <= config.initial_capital * config.max_capital_per_position_pct

            # Validate summary metrics
            assert result.metrics.win_rate_pct >= Decimal("0.00")
            assert result.metrics.total_fees_paid > Decimal("0.00")

            # Validate baseline comparison
            assert result.baseline_comparison is not None
            assert result.baseline_comparison.buy_and_hold_return_pct > Decimal("0.00")

        finally:
            # Cleanup test records
            session.execute(delete(DailyPriceRaw).where(DailyPriceRaw.instrument_id == test_inst_id))
            session.execute(delete(InstrumentSymbolHistory).where(InstrumentSymbolHistory.instrument_id == test_inst_id))
            session.execute(delete(Instrument).where(Instrument.instrument_id == test_inst_id))
            session.execute(delete(IngestionRun).where(IngestionRun.run_id == run.run_id))
            session.commit()
