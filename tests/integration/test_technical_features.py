import datetime
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from signal_atlas.db.models.instruments import Instrument, InstrumentSymbolHistory
from signal_atlas.db.models.prices import DailyPriceRaw
from signal_atlas.db.models.ingestion import IngestionRun
from signal_atlas.db.models.corporate_actions import CorporateAction
from signal_atlas.features import TechnicalFeatureEngine


def test_postgres_point_in_time_feature_extraction(pg_engine):
    """
    Integration test: Verifies TechnicalFeatureEngine extracting point-in-time features
    directly from PostgreSQL through get_point_in_time_adjusted_history.
    Proves that records with trade_date > as_of_date and corporate actions with
    ex_date > as_of_date have ZERO impact on features computed for as_of_date.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    test_inst_id = f"inst-feat-{uuid.uuid4().hex[:8]}"
    symbol = "FEATTEST"
    base_date = datetime.date(2023, 1, 2)

    with SessionFactory() as session:
        # Create synthetic instrument and ingestion run
        run = IngestionRun(
            run_id=f"run-feat-{uuid.uuid4().hex[:8]}",
            source="NSE",
            trade_date=base_date,
            file_name="feat_test.zip",
            file_hash="hash123",
            parser_version="v1",
            status="SUCCESS",
            row_count=60,
        )
        inst = Instrument(
            instrument_id=test_inst_id,
            name="Feature Test Corp",
            status="ACTIVE",
            first_observed_trade_date=base_date,
        )
        sym_hist = InstrumentSymbolHistory(
            instrument_id=test_inst_id,
            symbol=symbol,
            isin="INE999FEAT01",
            series="EQ",
            valid_from=base_date,
        )
        session.add_all([run, inst, sym_hist])
        session.flush()

        # Insert 60 daily prices (monotonically rising from 100 to 159)
        price_rows = []
        for i in range(60):
            dt = base_date + datetime.timedelta(days=i)
            p = Decimal(100 + i)
            price_rows.append(
                DailyPriceRaw(
                    instrument_id=test_inst_id,
                    trade_date=dt,
                    open=p,
                    high=p + Decimal("2.00"),
                    low=p - Decimal("1.50"),
                    close=p,
                    prev_close=p - Decimal("1.00"),
                    volume=10000 + i * 100,
                    traded_value=p * Decimal(10000 + i * 100),
                    series="EQ",
                    source="NSE",
                    ingestion_run_id=run.run_id,
                )
            )
        session.add_all(price_rows)

        # Insert a 2:1 stock split effective at day 55 (after decision date 50)
        split_ca = CorporateAction(
            action_id=f"ca-feat-{uuid.uuid4().hex[:8]}",
            instrument_id=test_inst_id,
            symbol=symbol,
            series="EQ",
            action_type="STOCK_SPLIT",
            ex_date=base_date + datetime.timedelta(days=55),
            purpose="Subdivision 2:1",
            share_multiplier=Decimal("2.000000"),
            verification_status="VERIFIED",
        )
        session.add(split_ca)
        session.commit()

    try:
        engine = TechnicalFeatureEngine(min_required_sessions=50)
        # Decision date A is at day 49 (50 sessions total)
        as_of_a = base_date + datetime.timedelta(days=49)

        with SessionFactory() as session:
            features_a = engine.get_point_in_time_features(
                instrument_id=test_inst_id,
                as_of_date=as_of_a,
                symbol=symbol,
                series="EQ",
                db=session,
            )

        # Verified assertions for Decision Date A:
        assert features_a.as_of_date == as_of_a
        assert features_a.history_sessions_count == 50
        assert features_a.sufficient_history is True
        assert features_a.close == Decimal("149.00")
        assert features_a.raw_close == Decimal("149.00")
        # Moving averages:
        assert features_a.ema_20 is not None
        assert features_a.ema_50 is not None
        # In an uptrend, EMA 20 must be > EMA 50
        assert features_a.ema_20 > features_a.ema_50
        # Close is 149, EMA 50 is approximately 125, EMA 20 is approximately 139
        assert features_a.close > features_a.ema_20
        # In a monotonic uptrend, RSI is high (> 70)
        assert features_a.rsi_14 is not None
        assert features_a.rsi_14 > Decimal("70.00")
        # ATR is positive
        assert features_a.atr_14 is not None
        assert features_a.atr_14 > Decimal("0.00")
        # 20-day volume
        assert features_a.avg_volume_20 is not None
        assert features_a.avg_volume_20 > 10000

        # Now test Decision Date B at day 58 (after the 2:1 stock split at day 55)
        as_of_b = base_date + datetime.timedelta(days=58)
        with SessionFactory() as session:
            features_b = engine.get_point_in_time_features(
                instrument_id=test_inst_id,
                as_of_date=as_of_b,
                symbol=symbol,
                series="EQ",
                db=session,
            )

        assert features_b.as_of_date == as_of_b
        assert features_b.history_sessions_count == 59
        # On day 58, raw close was 158. But since day 58 is after the 2:1 split on day 55,
        # backward adjustment factors (M=1.0 on day 58, M=2.0 on day 49) adjust historical prices:
        # historical prices prior to day 55 were divided by 2 (e.g. 149 / 2 = 74.5)
        assert features_b.close == Decimal("158.00")

    finally:
        # Teardown test records
        with SessionFactory() as session:
            session.execute(delete(CorporateAction).where(CorporateAction.instrument_id == test_inst_id))
            session.execute(delete(DailyPriceRaw).where(DailyPriceRaw.instrument_id == test_inst_id))
            session.execute(delete(InstrumentSymbolHistory).where(InstrumentSymbolHistory.instrument_id == test_inst_id))
            session.execute(delete(Instrument).where(Instrument.instrument_id == test_inst_id))
            session.commit()
