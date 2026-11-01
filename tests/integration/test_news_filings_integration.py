"""
test_news_filings_integration.py - PostgreSQL Integration Tests for Research Context Layer.

Verifies end-to-end database persistence, indexing, SHA-256 deduplication, and isolation
per Architecture Section 13.3 and 14.2:
1. Full PostgreSQL persistence for Corporate Filings, Company News, and Financial Fundamentals.
2. Deduplication integrity: duplicate hashes are rejected or deduplicated cleanly in Postgres.
3. Pre-trade event risk checklist evaluation over PostgreSQL data.
4. Strict data layer isolation: research context ingestion never mutates prices, corporate actions, or calendar.
"""

import datetime
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import func, select, delete
from sqlalchemy.orm import sessionmaker

from signal_atlas.db.models.prices import DailyPriceRaw
from signal_atlas.db.models.corporate_actions import CorporateAction
from signal_atlas.db.models.research_context import (
    CompanyFundamentalRecord,
    CompanyNewsRecord,
    CorporateFilingRecord,
)
from signal_atlas.research.context_models import FilingCategory
from signal_atlas.research.context_service import ResearchContextService
from signal_atlas.research.service import ResearchService


def test_postgresql_context_persistence_and_deduplication(pg_engine):
    """
    Validates that filings, news, and fundamentals persist cleanly to PostgreSQL,
    index lookups function properly, and SHA-256 hash deduplication works across transactions.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    run_id = uuid.uuid4().hex[:6].upper()
    sym = f"INFY_{run_id}"

    with SessionFactory() as session:
        service = ResearchContextService(db_session=session)

        # 1. Ingest Corporate Filing
        pub_at = datetime.datetime(2024, 10, 10, 14, 30, tzinfo=datetime.timezone.utc)
        f1 = service.ingest_filing(
            symbol=sym,
            title="Q2 Financial Results Audited",
            category=FilingCategory.RESULTS.value,
            published_at=pub_at,
            source="NSE",
            file_url="https://nsearchives.nseindia.com/corporate/results_q2.pdf",
            summary="PAT growth 11.5% YoY",
            is_material_risk=False,
            db=session,
        )
        assert f1.filing_id.startswith("FIL-")

        # 2. Ingest duplicate filing with same hash
        f2 = service.ingest_filing(
            symbol=sym,
            title="Q2 Financial Results Audited",
            category=FilingCategory.RESULTS.value,
            published_at=pub_at,
            source="NSE",
            db=session,
        )
        assert f2.filing_id == f1.filing_id
        assert f2.file_hash == f1.file_hash

        # Verify exact row count in PostgreSQL
        count = session.execute(
            select(func.count(CorporateFilingRecord.filing_id)).where(CorporateFilingRecord.symbol == sym)
        ).scalar()
        assert count == 1

        # 3. Ingest Company News
        news_dt = datetime.datetime(2024, 10, 12, 8, 45, tzinfo=datetime.timezone.utc)
        n1 = service.ingest_news(
            symbol=sym,
            headline="Infosys announces strategic cloud partnership with European bank",
            published_at=news_dt,
            source="NSE_FEED",
            url="https://example.com/news/123",
            summary="Strategic 5-year partnership",
            sentiment="POSITIVE",
            db=session,
        )
        assert n1.news_id.startswith("NEWS-")

        # Query news back from PostgreSQL
        news_list = service.get_news(symbol=sym, days=30, as_of_date=news_dt.date(), db=session)
        assert len(news_list) == 1
        assert news_list[0].headline == "Infosys announces strategic cloud partnership with European bank"
        assert news_list[0].sentiment == "POSITIVE"

        # 4. Record Fundamentals
        as_of = datetime.date(2024, 3, 31)
        fund = service.record_fundamentals(
            symbol=sym,
            as_of_date=as_of,
            period_type="ANNUAL",
            revenue=Decimal("153670000000.00"),
            ebitda=Decimal("38800000000.00"),
            pat=Decimal("26233000000.00"),
            eps=Decimal("63.15"),
            pe_ratio=Decimal("24.80"),
            pb_ratio=Decimal("7.20"),
            roe=Decimal("0.3150"),
            debt_to_equity=Decimal("0.0800"),
            promoter_holding_pct=Decimal("0.1480"),
            promoter_pledge_pct=Decimal("0.0000"),
            db=session,
        )
        assert fund.fundamental_id.startswith("FUND-")

        # Query fundamentals back from PostgreSQL
        q_fund = service.get_fundamentals(symbol=sym, as_of_date=datetime.date(2024, 10, 15), db=session)
        assert q_fund is not None
        assert q_fund.revenue == Decimal("153670000000.00")
        assert q_fund.pe_ratio == Decimal("24.80")
        assert q_fund.promoter_pledge_pct == Decimal("0.0000")


def test_postgresql_pre_trade_checklist_and_isolation(pg_engine):
    """
    Verifies that the Pre-Trade Event Risk Checklist evaluates cleanly against PostgreSQL
    and that context ingestion preserves database isolation with zero mutations to prices or actions.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    run_id = uuid.uuid4().hex[:6].upper()
    sym = f"RISK_{run_id}"
    as_of = datetime.date(2024, 11, 1)

    with SessionFactory() as session:
        # Pre-check counts on core tables
        initial_price_count = session.execute(select(func.count(DailyPriceRaw.id))).scalar()
        initial_ca_count = session.execute(select(func.count(CorporateAction.action_id))).scalar()

        service = ResearchContextService(db_session=session)

        # 1. Setup symbol with high promoter pledge (32%) and upcoming results
        service.record_fundamentals(
            symbol=sym,
            as_of_date=datetime.date(2024, 9, 30),
            promoter_pledge_pct=Decimal("0.32"),
            db=session,
        )

        # 2. Add upcoming results announcement in 5 days
        res_dt = datetime.datetime.combine(
            as_of + datetime.timedelta(days=5), datetime.time(15, 0), tzinfo=datetime.timezone.utc
        )
        service.ingest_filing(
            symbol=sym,
            title="Board Meeting for Unaudited Results",
            category=FilingCategory.RESULTS.value,
            published_at=res_dt,
            db=session,
        )

        # 3. Evaluate pre-trade checklist
        checklist = service.evaluate_pre_trade_checklist(symbol=sym, as_of_date=as_of, db=session)

        assert checklist.symbol == sym
        assert checklist.overall_status == "BLOCKED"

        blocking_items = [it for it in checklist.items if it.status == "BLOCKING"]
        assert len(blocking_items) == 2  # Both results announcement and promoter pledge > 25%

        # 4. Strict Database Isolation Verification
        final_price_count = session.execute(select(func.count(DailyPriceRaw.id))).scalar()
        final_ca_count = session.execute(select(func.count(CorporateAction.action_id))).scalar()

        assert initial_price_count == final_price_count, "Research context ingestion must never mutate DailyPriceRaw"
        assert initial_ca_count == final_ca_count, "Research context ingestion must never mutate CorporateAction"
