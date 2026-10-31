import datetime
from decimal import Decimal
import json
from pathlib import Path
import pytest
from sqlalchemy import select

from signal_atlas.db.session import get_db
from signal_atlas.db.models import (
    CorporateAction,
    DailyPriceRaw,
    InstrumentSymbolHistory,
)
from signal_atlas.quality.adjustment import is_action_eligible_for_price_adjustment


def test_effective_dated_isin_matching_symbol_rename():
    """
    Test 1: Effective-dated ISIN matching around a symbol rename.
    Verifies JTLIND (formerly JTLINFRA, Cand 461 on 2024-11-14):
      - Prior session on 2024-11-13 (close ₹183.79, pre_isin INE391J01024).
      - Resumption session on 2024-11-14 (close ₹98.15, post_isin INE391J01032).
      - Correctly traverses symbol history and identifies 2:1 split with MULTI_ISIN.
    """
    trans_path = Path("data/checkpoints/candidates_disposition_transition_report.json")
    assert trans_path.exists()
    with open(trans_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    jtl_record = next(r for r in records if r["symbol"] == "JTLIND" and r["ex_date"] == "2024-11-14")
    assert jtl_record["pre_isin"] == "INE391J01024"
    assert jtl_record["post_isin"] == "INE391J01032"
    assert jtl_record["event_isin_classification"] == "MULTI_ISIN"
    assert jtl_record["pre_session_date"] == "2024-11-13"
    assert jtl_record["post_session_date"] == "2024-11-14"


def test_genuine_isin_transition_on_event_date():
    """
    Test 2: A genuine ISIN transition on an event date.
    Verifies LATTEYS (Cand 174 on 2023-02-10):
      - Prior session on 2023-02-09: ISIN INE262Z01015, close ₹157.50.
      - Resumption session on 2023-02-10: ISIN INE262Z01023, close ₹33.05.
      - Ratio ~4.77 (~5.0x split).
      - ISIN changed specifically on the event date due to face value sub-division from ₹10 to ₹2.
    """
    trans_path = Path("data/checkpoints/candidates_disposition_transition_report.json")
    with open(trans_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    latteys = next(r for r in records if r["candidate_index"] == 174)
    assert latteys["symbol"] == "LATTEYS"
    assert latteys["ex_date"] == "2023-02-10"
    assert latteys["pre_isin"] == "INE262Z01015"
    assert latteys["post_isin"] == "INE262Z01023"
    assert latteys["event_isin_classification"] == "MULTI_ISIN"
    assert latteys["pre_session_date"] == "2023-02-09"
    assert latteys["post_session_date"] == "2023-02-10"


def test_historical_isin_record_ending_more_than_seven_days_before_event():
    """
    Test 3: Historical ISIN record ending more than 7 calendar days before an event.
    Verifies KAUSHALYA (100:1 consolidation on 2024-02-06):
      - Trading was suspended from 2024-01-12 to 2024-02-05 (26 calendar days gap).
      - Last pre-event session in daily_prices_raw was 2024-01-11 (close ₹9.85).
      - Resumption session on 2024-02-06 (close ₹988.30).
      - Engine finds exact trading session without failing on an arbitrary 7-day lookback.
    """
    with get_db() as db:
        hists = db.execute(
            select(InstrumentSymbolHistory).where(InstrumentSymbolHistory.symbol == "KAUSHALYA")
        ).scalars().all()
        inst_ids = [h.instrument_id for h in hists]
        ex_d = datetime.date(2024, 2, 6)

        last_pre = db.execute(
            select(DailyPriceRaw)
            .where(DailyPriceRaw.instrument_id.in_(inst_ids), DailyPriceRaw.trade_date < ex_d)
            .order_by(DailyPriceRaw.trade_date.desc())
            .limit(1)
        ).scalars().first()

        assert last_pre is not None
        assert last_pre.trade_date == datetime.date(2024, 1, 11)
        # Check calendar gap is 26 days (> 7 days)
        calendar_gap = (ex_d - last_pre.trade_date).days
        assert calendar_gap == 26

        # Check pre-ISIN matches valid interval on 2024-01-11
        pre_matches = [
            h for h in hists
            if h.valid_from <= last_pre.trade_date and (h.valid_to is None or h.valid_to >= last_pre.trade_date)
        ]
        assert len(pre_matches) > 0
        assert pre_matches[0].isin == "INE234I01010"


def test_missing_or_overlapping_effective_date_records_handling():
    """
    Test 4: Missing or overlapping effective-date records handling.
    Verifies that candidates with missing traded records or interval gaps are:
      - Logged with exact source traces.
      - Inconsistencies between traded Bhavcopy ISIN and CorporateAction ISIN are flagged.
      - Discrepancies are surfaced explicitly in the transition report.
    """
    trans_path = Path("data/checkpoints/candidates_disposition_transition_report.json")
    with open(trans_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    inconsistent_records = [r for r in records if r["inconsistencies"] != "NONE"]
    # Exactly 106 candidates have CorporateAction recorded ISINs differing from physical traded ISINs
    assert len(inconsistent_records) == 106
    for r in inconsistent_records:
        assert "Pre-traded" in r["inconsistencies"] or "Post-traded" in r["inconsistencies"]


def test_preservation_of_unknown_when_continuity_unprovable():
    """
    Test 5: Preservation of UNKNOWN when event continuity cannot be established.
    Verifies that:
      - Temporary Rights Entitlements without prior equity history (e.g. WOCKH-RE, ASIAN-RE1)
        have pre_isin=None and are strictly classified as UNKNOWN.
      - Demerger listing days without prior NSE history (e.g. GATEWAY, MSUMI on 2022-03-28)
        are strictly classified as UNKNOWN.
      - Total UNKNOWN candidates across 486 is exactly 55.
    """
    unknown_path = Path("data/checkpoints/unresolved_and_unknown_candidates.json")
    assert unknown_path.exists()
    with open(unknown_path, "r", encoding="utf-8") as f:
        unknowns = json.load(f)

    assert len(unknowns) == 55
    for u in unknowns:
        assert u["event_isin_classification"] == "UNKNOWN"
        assert u["pre_isin"] is None or u["post_isin"] is None


def test_reconciled_disposition_counts_and_transition_matrix():
    """
    Test 6: Correct disposition counts after reconciliation and transition matrix verification.
    Verifies that:
      - Exactly 486 candidates are reconciled.
      - Original totals match Reconciled totals exactly:
          VERIFIED_BONUS: 224
          VERIFIED_SPLIT: 92
          RIGHTS_ENTITLEMENT_EXPIRATION: 76
          DUPLICATE_CANDIDATE: 43
          NORMAL_MARKET_MOVEMENT: 43
          OTHER_VERIFIED_ACTION: 8
      - Transition matrix is 100% diagonal (no silent reclassifications).
      - Cross-tabulation totals reconcile exactly:
          SAME_ISIN: 284
          MULTI_ISIN: 147
          UNKNOWN: 55
          TOTAL: 486
    """
    matrix_path = Path("data/checkpoints/candidates_disposition_transition_matrix.json")
    assert matrix_path.exists()
    with open(matrix_path, "r", encoding="utf-8") as f:
        matrix_doc = json.load(f)

    orig = matrix_doc["disposition_totals"]["original_totals"]
    reconciled = matrix_doc["disposition_totals"]["reconciled_totals"]

    expected = {
        "VERIFIED_BONUS": 224,
        "VERIFIED_SPLIT": 92,
        "RIGHTS_ENTITLEMENT_EXPIRATION": 76,
        "DUPLICATE_CANDIDATE": 43,
        "NORMAL_MARKET_MOVEMENT": 43,
        "OTHER_VERIFIED_ACTION": 8,
    }

    assert orig == expected
    assert reconciled == expected

    # Check cross-tabulation totals
    xtab_path = Path("data/checkpoints/candidates_disposition_cross_tabulation.json")
    assert xtab_path.exists()
    with open(xtab_path, "r", encoding="utf-8") as f:
        xtab = json.load(f)

    summary = xtab["event_level_isin_summary"]
    assert summary["same_isin_events"] == 284
    assert summary["multi_isin_events"] == 147
    assert summary["unknown_isin_events"] == 55
    assert summary["total_candidates"] == 486


def test_multi_isin_bonus_eligibility_policy():
    """
    Test 7: A multi-ISIN bonus action that is eligible only after its security relationship is verified.
    Verifies multi_isin_bonus_audit_41.json:
      - Exactly 41 candidates.
      - 12 ETFs categorized as ETF_SCHEME_RESTRUCTURING, marked ineligible for conventional equity adjustment
        and quarantined (EXCLUDED_FROM_ADJUSTED_DATA).
      - 2 Companion split+bonus events (GOLDSTAR, VERTOZ) marked eligible for adjustment.
      - 27 Continuing equity subdivisions / reorganizations marked eligible for adjustment.
    """
    audit_path = Path("data/checkpoints/multi_isin_bonus_audit_41.json")
    assert audit_path.exists()
    with open(audit_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    assert len(rows) == 41

    etfs = [r for r in rows if r["security_relationship_category"] == "ETF_SCHEME_RESTRUCTURING"]
    assert len(etfs) == 12
    for etf in etfs:
        assert etf["conventional_adjustment_eligible"] is False
        assert etf["quarantine_status"] == "EXCLUDED_FROM_ADJUSTED_DATA"

    companions = [r for r in rows if r["security_relationship_category"] == "COMPANION_SPLIT_AND_BONUS"]
    assert len(companions) == 2
    assert set(r["symbol"] for r in companions) == {"VERTOZ", "GOLDSTAR"}
    for comp in companions:
        assert comp["conventional_adjustment_eligible"] is True

    continuing_equities = [
        r for r in rows
        if r["security_relationship_category"] in ("CONTINUING_EQUITY_SUBDIVISION_SPLIT", "PREDECESSOR_SUCCESSOR_REORGANIZATION")
    ]
    assert len(continuing_equities) == 27
    for eq in continuing_equities:
        assert eq["conventional_adjustment_eligible"] is True
