"""
test_kaushalya_reverse_split.py - Exhaustive Database Integration Verification for Reverse Splits.

Verifies the KAUSHALYA 100:1 reverse split / consolidation (ex-date: 2024-02-06, M=0.010000):
  1. Corporate action registry entry exists, is VERIFIED, and is_action_eligible_for_price_adjustment is True.
  2. Multiplier is strictly 0.010000 (below 1.0).
  3. Pre-event historical adjusted OHLC is raw OHLC divided by 0.01 (100 * P_raw).
  4. Pre-event historical adjusted volume is raw volume multiplied by 0.01 (0.01 * V_raw).
  5. Close-volume product invariance is preserved within numerical precision:
       P_adj * V_adj == (P_raw / 0.01) * (V_raw * 0.01) == P_raw * V_raw.
  6. Exchange turnover (traded_value) is preserved strictly unchanged.
  7. Ex-date adjusted previous-close alignment:
       On 2024-02-06, adj_prev_close matches the previous trading session's (2024-01-11) adjusted close (985.00).
  8. Point-in-Time (PIT) consistency after ex-date (as-of 2024-02-15):
       Historical prices reflect M=0.01 backward adjustment.
  9. Point-in-Time (PIT) invariance before ex-date (as-of 2024-01-15):
       Future reverse split has M=1.000000 and does NOT adjust historical prices before ex-date.
  10. Adjustment engine and provenance report parity:
       affects_adjusted_prices in provenance report is guaranteed identical to is_action_eligible_for_price_adjustment.
"""

import datetime
from decimal import Decimal
import json
import pytest
from sqlalchemy import select

from signal_atlas.db.session import get_db
from signal_atlas.db.models import (
    CorporateAction,
    DailyPriceRaw,
    DailyPriceAdjusted,
    Instrument,
)
from signal_atlas.quality.adjustment import (
    is_action_eligible_for_price_adjustment,
    get_point_in_time_adjusted_history,
)


@pytest.fixture(autouse=True)
def require_kaushalya_data():
    with get_db() as db:
        ca = db.execute(
            select(CorporateAction).where(CorporateAction.symbol == "KAUSHALYA")
        ).scalars().first()
        if ca is None:
            pytest.skip("KAUSHALYA corporate action not loaded in test database")


def test_kaushalya_corporate_action_eligibility():
    """Verify KAUSHALYA corporate action entry and eligibility in registry."""
    with get_db() as db:
        ca = db.execute(
            select(CorporateAction).where(CorporateAction.symbol == "KAUSHALYA")
        ).scalars().first()
        if ca is None:
            pytest.skip("KAUSHALYA corporate action not loaded in test database")

        assert ca.action_type == "STOCK_SPLIT"
        assert ca.ex_date == datetime.date(2024, 2, 6)
        assert ca.share_multiplier == Decimal("0.010000")
        assert ca.verification_status == "VERIFIED"

        # Direct eligibility predicate check
        assert is_action_eligible_for_price_adjustment(ca) is True, (
            "Reverse split with M=0.01 must be eligible for price adjustment"
        )


def test_kaushalya_historical_adjusted_series_v1_2():
    """
    Verify KAUSHALYA historical prices and volumes are correctly adjusted in v1.2:
      P_adj = P_raw / 0.01 = 100 * P_raw
      V_adj = V_raw * 0.01
    """
    with get_db() as db:
        ca = db.execute(
            select(CorporateAction).where(CorporateAction.symbol == "KAUSHALYA")
        ).scalars().first()

        raw_rows = db.execute(
            select(DailyPriceRaw)
            .where(DailyPriceRaw.instrument_id == ca.instrument_id)
            .order_by(DailyPriceRaw.trade_date)
        ).scalars().all()

        adj_rows = db.execute(
            select(DailyPriceAdjusted)
            .where(
                DailyPriceAdjusted.instrument_id == ca.instrument_id,
                DailyPriceAdjusted.adjustment_version == "v1.2",
            )
            .order_by(DailyPriceAdjusted.trade_date)
        ).scalars().all()

        assert len(adj_rows) == len(raw_rows), "Adjusted row count must match raw row count"

        adj_map = {r.trade_date: r for r in adj_rows}

        # Check last pre-event trading session: 2024-01-11
        pre_date = datetime.date(2024, 1, 11)
        raw_pre = next(r for r in raw_rows if r.trade_date == pre_date)
        adj_pre = adj_map[pre_date]

        assert raw_pre.close == Decimal("9.85")
        assert raw_pre.volume == 260228

        # 1. Adjusted close is raw close / 0.01 = 100 * raw close = 985.000000
        assert adj_pre.cumulative_multiplier == Decimal("0.010000")
        assert adj_pre.close == Decimal("985.000000")
        assert adj_pre.open == (raw_pre.open / Decimal("0.01")).quantize(Decimal("0.000001"))
        assert adj_pre.high == (raw_pre.high / Decimal("0.01")).quantize(Decimal("0.000001"))
        assert adj_pre.low == (raw_pre.low / Decimal("0.01")).quantize(Decimal("0.000001"))

        # 2. Adjusted volume is raw volume * 0.01 = 2602.280000
        assert adj_pre.volume == Decimal("2602.280000")
        assert adj_pre.raw_volume == 260228

        # 3. Product invariant: P_adj * V_adj == P_raw * V_raw
        raw_prod = raw_pre.close * Decimal(raw_pre.volume)
        adj_prod = adj_pre.close * adj_pre.volume
        assert abs(adj_prod - raw_prod) <= Decimal("0.01")

        # 4. Exchange turnover is preserved strictly unchanged
        assert adj_pre.traded_value == raw_pre.traded_value
        assert adj_pre.raw_traded_value == raw_pre.traded_value

        # 5. Ex-date: 2024-02-06
        ex_date = datetime.date(2024, 2, 6)
        raw_ex = next(r for r in raw_rows if r.trade_date == ex_date)
        adj_ex = adj_map[ex_date]

        assert adj_ex.cumulative_multiplier == Decimal("1.000000")
        assert adj_ex.close == raw_ex.close
        assert adj_ex.volume == Decimal(raw_ex.volume)

        # 6. Ex-date adjusted previous-close alignment:
        # Pre-event adjusted close on 2024-01-11 is 985.000000.
        # Ex-date adjusted previous close on 2024-02-06 must align to 985.000000.
        assert adj_ex.prev_close == Decimal("985.000000")
        assert adj_ex.prev_close == adj_pre.close
        # Raw exchange previous close is preserved unchanged
        assert adj_ex.raw_prev_close == Decimal("985.00")

        # Continuous overnight gap from 2024-01-11 close to 2024-02-06 open
        overnight_gap = (adj_ex.open - adj_ex.prev_close) / adj_ex.prev_close
        # Open 965.50 vs prev_close 985.00 -> -1.98% (realistic continuous trading)
        assert abs(overnight_gap - Decimal("-0.019797")) <= Decimal("0.001")


def test_kaushalya_point_in_time_behavior():
    """
    Verify KAUSHALYA dynamic point-in-time behavior:
      - As-of 2024-01-15 (before ex-date): corporate action does NOT affect historical series.
      - As-of 2024-02-15 (after ex-date): corporate action scales pre-event series by M=0.01.
    """
    with get_db() as db:
        ca = db.execute(
            select(CorporateAction).where(CorporateAction.symbol == "KAUSHALYA")
        ).scalars().first()

        # Decision date A = 2024-01-15 (before 2024-02-06)
        pit_before = get_point_in_time_adjusted_history(
            instrument_id=ca.instrument_id,
            as_of_date=datetime.date(2024, 1, 15),
            series="BE",
            db=db,
        )
        assert len(pit_before) > 0
        assert all(r.trade_date <= datetime.date(2024, 1, 15) for r in pit_before)
        r_pre_at_a1 = next(r for r in pit_before if r.trade_date == datetime.date(2024, 1, 11))
        # Unaffected by future reverse split
        assert r_pre_at_a1.cumulative_multiplier == Decimal("1.000000")
        assert r_pre_at_a1.close == Decimal("9.85")
        assert r_pre_at_a1.volume == Decimal("260228.000000")

        # Decision date A = 2024-02-15 (after 2024-02-06)
        pit_after = get_point_in_time_adjusted_history(
            instrument_id=ca.instrument_id,
            as_of_date=datetime.date(2024, 2, 15),
            series="BE",
            db=db,
        )
        assert len(pit_after) > 0
        r_pre_at_a2 = next(r for r in pit_after if r.trade_date == datetime.date(2024, 1, 11))
        # Scaled by active reverse split
        assert r_pre_at_a2.cumulative_multiplier == Decimal("0.010000")
        assert r_pre_at_a2.close == Decimal("985.000000")
        assert r_pre_at_a2.volume == Decimal("2602.280000")


def test_engine_and_provenance_report_parity():
    """
    Establish that affects_adjusted_prices in the provenance report is guaranteed
    identical to the adjustment engine predicate is_action_eligible_for_price_adjustment.
    Ensures report and adjustment engine cannot disagree.
    """
    with open("data/checkpoints/corporate_action_provenance_full_report.json", "r", encoding="utf-8") as f:
        prov_report = json.load(f)

    with get_db() as db:
        cas = db.execute(select(CorporateAction)).scalars().all()
        ca_map = {c.action_id: c for c in cas}

        disagreements = []
        for ev in prov_report["events"]:
            action_id = ev["action_id"]
            ca = ca_map.get(action_id)
            if not ca:
                continue
            engine_verdict = is_action_eligible_for_price_adjustment(ca)
            report_flag = ev["affects_adjusted_prices"]
            if engine_verdict != report_flag:
                disagreements.append((action_id, ca.symbol, ca.action_type, ca.share_multiplier, engine_verdict, report_flag))

    assert len(disagreements) == 0, f"Disagreements found between engine and report: {disagreements}"
