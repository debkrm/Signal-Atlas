import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from signal_atlas.db.base import Base
from signal_atlas.db.models.calendar import TradingCalendar
from signal_atlas.db.models.corporate_actions import CorporateAction
from signal_atlas.db.models.ingestion import IngestionRun
from signal_atlas.db.models.instruments import Instrument, InstrumentSymbolHistory
from signal_atlas.db.models.prices import DailyPriceRaw
from signal_atlas.db.models.quarantine import DailyPriceQuarantine
from signal_atlas.universe.models import UniverseConfig
from signal_atlas.universe.provenance import RawDataManifest, _canonical_value, _dirty_fingerprint, compute_raw_data_manifest
from signal_atlas.universe.service import PointInTimeUniverseService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        run = IngestionRun(
            run_id="run-1", source="NSE", trade_date=datetime.date(2024, 1, 2),
            file_name="bhav.csv", file_hash="a" * 64, parser_version="v1", status="SUCCESS", row_count=2,
        )
        instrument = Instrument(instrument_id="instrument-1", name="Example", status="ACTIVE")
        session.add_all([run, instrument])
        session.flush()
        session.add_all([
            InstrumentSymbolHistory(
                instrument_id=instrument.instrument_id, exchange="NSE", symbol="EXAMPLE", isin="INE000A01001",
                series="EQ", valid_from=datetime.date(2024, 1, 1), source="NSE",
            ),
            TradingCalendar(trade_date=datetime.date(2024, 1, 2), is_trading_day=True),
            DailyPriceRaw(
                instrument_id=instrument.instrument_id, trade_date=datetime.date(2024, 1, 2),
                open=Decimal("10"), high=Decimal("12"), low=Decimal("9"), close=Decimal("11"),
                prev_close=Decimal("10"), volume=100, traded_value=Decimal("1100"), series="EQ",
                source="NSE", ingestion_run_id=run.run_id,
            ),
            DailyPriceRaw(
                instrument_id=instrument.instrument_id, trade_date=datetime.date(2024, 1, 3),
                open=Decimal("20"), high=Decimal("22"), low=Decimal("19"), close=Decimal("21"),
                prev_close=Decimal("20"), volume=100, traded_value=Decimal("2100"), series="EQ",
                source="NSE", ingestion_run_id=run.run_id,
            ),
            DailyPriceQuarantine(
                trade_date=datetime.date(2024, 1, 2), symbol="BAD", series="EQ", isin="INE000A01001",
                row_number=1, raw_payload={"field": "value"}, validation_rule="rule", validation_message="message",
                source_file="bhav.csv", source_file_hash="b" * 64, ingestion_run_id=run.run_id,
            ),
            CorporateAction(
                action_id="ca-1", instrument_id=instrument.instrument_id, symbol="EXAMPLE", series="EQ",
                action_type="STOCK_SPLIT", ex_date=datetime.date(2024, 1, 3), purpose="split",
                verification_status="VERIFIED",
            ),
        ])
        session.commit()
        yield session
    finally:
        session.close()
        engine.dispose()


def test_manifest_is_deterministic_and_hashes_raw_row_content(db):
    first = compute_raw_data_manifest(db)
    assert first == compute_raw_data_manifest(db)

    prices = db.query(DailyPriceRaw).order_by(DailyPriceRaw.id).all()
    # Preserve row count, dates, volume and both aggregate sums from the prior implementation.
    prices[0].close = Decimal("12")
    prices[1].close = Decimal("20")
    db.commit()

    assert compute_raw_data_manifest(db).manifest_fingerprint != first.manifest_fingerprint


@pytest.mark.parametrize(
    "model,attribute,new_value",
    [
        (Instrument, "delisting_date", datetime.date(2024, 12, 31)),
        (InstrumentSymbolHistory, "symbol", "RENAMED"),
        (TradingCalendar, "holiday_name", "Exchange holiday"),
        (DailyPriceQuarantine, "validation_message", "changed"),
        (IngestionRun, "file_hash", "c" * 64),
    ],
)
def test_manifest_hashes_every_universe_input_table(db, model, attribute, new_value):
    before = compute_raw_data_manifest(db).manifest_fingerprint
    row = db.query(model).first()
    setattr(row, attribute, new_value)
    db.commit()
    assert compute_raw_data_manifest(db).manifest_fingerprint != before


def test_canonical_serializer_distinguishes_null_and_empty_string():
    assert _canonical_value(None) != _canonical_value("")


def test_manifest_binding_rejects_a_stale_caller_hash(db):
    manifest = compute_raw_data_manifest(db)
    config = UniverseConfig(raw_data_manifest_hash="0" * 64)
    with pytest.raises(ValueError, match="does not match"):
        PointInTimeUniverseService._bind_manifest(config, manifest)


def test_code_revision_dirty_fingerprint_includes_every_change_class():
    clean = _dirty_fingerprint("", "", [])
    unstaged = _dirty_fingerprint("", "diff --git a/src/a.py b/src/a.py", [])
    staged = _dirty_fingerprint("diff --git a/src/a.py b/src/a.py", "", [])
    untracked = _dirty_fingerprint("", "", [("src/new_module.py", b"value = 3\n")])
    assert len({clean, unstaged, staged, untracked}) == 4


def test_manifest_and_code_revision_are_part_of_snapshot_identity():
    manifest_one = RawDataManifest(manifest_fingerprint="1" * 64)
    manifest_two = RawDataManifest(manifest_fingerprint="2" * 64)
    config = UniverseConfig(code_revision="revision-one")
    bound_one = PointInTimeUniverseService._bind_manifest(config, manifest_one)
    bound_two = PointInTimeUniverseService._bind_manifest(config, manifest_two)
    revised = PointInTimeUniverseService._bind_manifest(
        config.model_copy(update={"code_revision": "revision-two"}), manifest_one
    )
    assert len({bound_one.config_identifier, bound_two.config_identifier, revised.config_identifier}) == 3


def test_cache_hit_returns_current_manifest_metadata(monkeypatch):
    manifest = RawDataManifest(manifest_fingerprint="a" * 64)
    config = PointInTimeUniverseService._bind_manifest(UniverseConfig(code_revision="revision"), manifest)
    snapshot_record = SimpleNamespace(
        snapshot_id="snapshot", as_of_date=datetime.date(2024, 1, 2), lookback_sessions=126,
        lookback_start_date=datetime.date(2023, 7, 1), lookback_end_date=datetime.date(2024, 1, 2),
        config_identifier=config.config_identifier, adjustment_version=config.adjustment_version,
        raw_data_version=config.raw_data_version, data_coverage_start=config.data_coverage_start,
        data_coverage_end=config.data_coverage_end, code_revision=config.code_revision,
        total_instruments_evaluated=0, eligible_count=0, excluded_count=0,
    )

    class ScalarResult:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return self

        def first(self):
            return self.values[0] if self.values else None

        def all(self):
            return self.values

    class CacheSession:
        def __init__(self):
            self.calls = 0

        def execute(self, _query):
            self.calls += 1
            return ScalarResult([snapshot_record] if self.calls == 1 else [])

    session = CacheSession()
    service = PointInTimeUniverseService()
    monkeypatch.setattr("signal_atlas.universe.service.compute_raw_data_manifest", lambda _: manifest)
    monkeypatch.setattr(service, "build_universe", lambda *args, **kwargs: pytest.fail("cache hit rebuilt"))
    snapshot = service.get_universe(datetime.date(2024, 1, 2), config=config, session=session)
    assert session.calls == 2
    assert snapshot.raw_data_manifest_hash == manifest.manifest_fingerprint
    assert snapshot.raw_data_manifest == manifest.canonical_dict()
