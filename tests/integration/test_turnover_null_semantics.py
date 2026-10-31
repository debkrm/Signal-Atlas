"""
test_turnover_null_semantics.py - Nullable Traded Value and Turnover Semantics Verification.

Verifies:
  1. Actual source-reported zero turnover:
       - traded_value == Decimal("0.00")
       - raw_traded_value == Decimal("0.00")
       - raw_vwap == Decimal("0.000000") (when volume > 0)
       - adjusted_vwap == Decimal("0.000000")
  2. Null/missing turnover:
       - traded_value is None
       - raw_traded_value is None
       - raw_vwap is None
       - adjusted_vwap is None
       - No fabricated Decimal("0.00")
  3. Zero volume with known turnover:
       - volume == 0, traded_value == Decimal("0.00")
       - raw_vwap is None (safe against division by zero)
       - adjusted_vwap is None
  4. Zero volume with missing turnover:
       - volume == 0, traded_value is None
       - raw_vwap is None
       - adjusted_vwap is None
  5. Normal valid positive volume and turnover:
       - volume > 0, traded_value > 0
       - raw_vwap == traded_value / volume
       - adjusted_vwap == raw_vwap / M
  6. Liquidity Ranking Interface:
       - Distinguishes unknown/missing turnover (None) from genuine source-reported zero (0.00).
       - Records with missing turnover are disqualified from liquidity ranking.
"""

import datetime
from decimal import Decimal
import pytest

from signal_atlas.quality.corporate_actions import CorporateActionEvent
from signal_atlas.quality.adjustment import (
    apply_backward_adjustment,
    AdjustedPriceRecord,
)


def _make_dummy_action(mult: Decimal = Decimal("2.000000")) -> CorporateActionEvent:
    return CorporateActionEvent(
        action_id="CA-TEST-2024-06-01-SPLIT",
        instrument_id="inst-test-123",
        symbol="TESTSYM",
        series="EQ",
        action_type="STOCK_SPLIT",
        ex_date=datetime.date(2024, 6, 1),
        old_face_value=Decimal("10.00"),
        new_face_value=Decimal("5.00"),
        share_multiplier=mult,
        purpose="2:1 stock split",
        source_circular="NSE/CML/TEST",
        verification_status="VERIFIED",
    )


def test_scenario_1_source_reported_zero_turnover():
    """1. Actual source-reported zero turnover (traded_value = Decimal('0.00'))."""
    raw_records = [
        {
            "trade_date": datetime.date(2024, 5, 30),
            "open": Decimal("100.00"),
            "high": Decimal("105.00"),
            "low": Decimal("95.00"),
            "close": Decimal("100.00"),
            "prev_close": Decimal("100.00"),
            "volume": 500,
            "traded_value": Decimal("0.00"),
        }
    ]
    ca = _make_dummy_action()
    adj = apply_backward_adjustment(raw_records, [ca])
    r = adj[0]

    assert r.traded_value == Decimal("0.00")
    assert r.raw_traded_value == Decimal("0.00")
    assert r.traded_value is not None
    assert r.verify_turnover_invariance() is True
    # Zero turnover with positive volume yields 0.000000 VWAP
    assert r.raw_vwap == Decimal("0.000000")
    assert r.adjusted_vwap == Decimal("0.000000")
    assert r.verify_vwap_turnover_relationship() is True


def test_scenario_2_null_missing_turnover():
    """2. Missing/null source turnover (traded_value = None). Must NOT fabricate Decimal('0.00')."""
    raw_records = [
        {
            "trade_date": datetime.date(2024, 5, 30),
            "open": Decimal("100.00"),
            "high": Decimal("105.00"),
            "low": Decimal("95.00"),
            "close": Decimal("100.00"),
            "prev_close": Decimal("100.00"),
            "volume": 500,
            "traded_value": None,
        }
    ]
    ca = _make_dummy_action()
    adj = apply_backward_adjustment(raw_records, [ca])
    r = adj[0]

    assert r.traded_value is None, "Missing turnover must remain None, not fabricated 0.00"
    assert r.raw_traded_value is None
    assert r.verify_turnover_invariance() is True
    # Missing turnover cannot produce VWAP
    assert r.raw_vwap is None
    assert r.adjusted_vwap is None
    assert r.verify_vwap_turnover_relationship() is True


def test_scenario_3_zero_volume_known_turnover():
    """3. Zero volume with known turnover (volume = 0, traded_value = Decimal('0.00'))."""
    raw_records = [
        {
            "trade_date": datetime.date(2024, 5, 30),
            "open": Decimal("100.00"),
            "high": Decimal("100.00"),
            "low": Decimal("100.00"),
            "close": Decimal("100.00"),
            "prev_close": Decimal("100.00"),
            "volume": 0,
            "traded_value": Decimal("0.00"),
        }
    ]
    ca = _make_dummy_action()
    adj = apply_backward_adjustment(raw_records, [ca])
    r = adj[0]

    assert r.volume == Decimal("0.000000")
    assert r.raw_volume == 0
    assert r.traded_value == Decimal("0.00")
    assert r.raw_traded_value == Decimal("0.00")
    # Zero volume safely prevents zero-division
    assert r.raw_vwap is None
    assert r.adjusted_vwap is None
    assert r.verify_vwap_turnover_relationship() is True


def test_scenario_4_zero_volume_missing_turnover():
    """4. Zero volume with missing turnover (volume = 0, traded_value = None)."""
    raw_records = [
        {
            "trade_date": datetime.date(2024, 5, 30),
            "open": Decimal("100.00"),
            "high": Decimal("100.00"),
            "low": Decimal("100.00"),
            "close": Decimal("100.00"),
            "prev_close": Decimal("100.00"),
            "volume": 0,
            "traded_value": None,
        }
    ]
    ca = _make_dummy_action()
    adj = apply_backward_adjustment(raw_records, [ca])
    r = adj[0]

    assert r.volume == Decimal("0.000000")
    assert r.raw_volume == 0
    assert r.traded_value is None
    assert r.raw_traded_value is None
    assert r.raw_vwap is None
    assert r.adjusted_vwap is None
    assert r.verify_turnover_invariance() is True
    assert r.verify_vwap_turnover_relationship() is True


def test_scenario_5_normal_valid_positive_volume_and_turnover():
    """5. Normal valid positive volume and turnover."""
    raw_records = [
        {
            "trade_date": datetime.date(2024, 5, 30),
            "open": Decimal("100.00"),
            "high": Decimal("105.00"),
            "low": Decimal("95.00"),
            "close": Decimal("102.00"),
            "prev_close": Decimal("98.00"),
            "volume": 1000,
            "traded_value": Decimal("101500.00"),
        }
    ]
    ca = _make_dummy_action(mult=Decimal("2.000000"))
    adj = apply_backward_adjustment(raw_records, [ca])
    r = adj[0]

    assert r.traded_value == Decimal("101500.00")
    assert r.raw_traded_value == Decimal("101500.00")
    assert r.volume == Decimal("2000.000000")
    assert r.close == Decimal("51.000000")
    # Raw VWAP = 101500 / 1000 = 101.500000
    assert r.raw_vwap == Decimal("101.500000")
    # Adjusted VWAP = 101.500000 / 2.0 = 50.750000
    assert r.adjusted_vwap == Decimal("50.750000")
    # Preserves turnover: 50.75 * 2000 = 101500.00
    assert r.verify_vwap_turnover_relationship() is True


def test_liquidity_ranking_filter_policy():
    """
    Verify that the future liquidity data interface can distinguish
    unknown/missing turnover from genuine zero turnover.
    """
    def is_eligible_for_liquidity_ranking(rec: AdjustedPriceRecord) -> bool:
        """
        Data quality policy: records with missing/null traded_value must be
        ineligible for liquidity ranking until explicitly addressed.
        Genuinely reported 0.00 turnover remains ranked as zero.
        """
        if rec.traded_value is None or rec.raw_traded_value is None:
            return False
        return True

    # Scenario 1: Reported 0.00 -> Eligible (ranks as 0 liquidity)
    r1 = AdjustedPriceRecord(
        trade_date=datetime.date(2024, 1, 1),
        open=Decimal("10"), high=Decimal("10"), low=Decimal("10"), close=Decimal("10"),
        prev_close=Decimal("10"), raw_prev_close=Decimal("10"),
        volume=Decimal("10"), raw_volume=10,
        traded_value=Decimal("0.00"), raw_traded_value=Decimal("0.00"),
        cumulative_multiplier=Decimal("1.0"), prev_close_multiplier=Decimal("1.0"),
    )
    assert is_eligible_for_liquidity_ranking(r1) is True

    # Scenario 2: Null/missing -> Ineligible (must NOT be treated as zero)
    r2 = AdjustedPriceRecord(
        trade_date=datetime.date(2024, 1, 1),
        open=Decimal("10"), high=Decimal("10"), low=Decimal("10"), close=Decimal("10"),
        prev_close=Decimal("10"), raw_prev_close=Decimal("10"),
        volume=Decimal("10"), raw_volume=10,
        traded_value=None, raw_traded_value=None,
        cumulative_multiplier=Decimal("1.0"), prev_close_multiplier=Decimal("1.0"),
    )
    assert is_eligible_for_liquidity_ranking(r2) is False

    # Scenario 5: Normal positive turnover -> Eligible
    r5 = AdjustedPriceRecord(
        trade_date=datetime.date(2024, 1, 1),
        open=Decimal("10"), high=Decimal("10"), low=Decimal("10"), close=Decimal("10"),
        prev_close=Decimal("10"), raw_prev_close=Decimal("10"),
        volume=Decimal("10"), raw_volume=10,
        traded_value=Decimal("100.00"), raw_traded_value=Decimal("100.00"),
        cumulative_multiplier=Decimal("1.0"), prev_close_multiplier=Decimal("1.0"),
    )
    assert is_eligible_for_liquidity_ranking(r5) is True
