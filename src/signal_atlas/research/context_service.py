"""
context_service.py - Application Service for Corporate Filings, News, and Fundamentals.

Provides deterministic data ingestion, SHA-256 deduplication, point-in-time queries,
and pre-trade qualitative risk evaluation per Architecture Section 13.3.
"""

import datetime
from decimal import Decimal
import hashlib
import logging
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from signal_atlas.db.models.research_context import (
    CompanyFundamentalRecord,
    CompanyNewsRecord,
    CorporateFilingRecord,
)
from signal_atlas.db.models.instruments import InstrumentSymbolHistory
from signal_atlas.db.session import get_db
from signal_atlas.research.context_models import (
    CompanyFundamentals,
    CompanyNews,
    CorporateFiling,
    FilingCategory,
    PreTradeEventChecklist,
    PreTradeRiskItem,
)

logger = logging.getLogger(__name__)


def compute_sha256(content: str) -> str:
    """Computes deterministic SHA-256 hex digest for document/text deduplication."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ResearchContextService:
    """
    Application Service for qualitative research context:
    - Exchange corporate filings (results, corporate events, material disclosures)
    - Company news articles and discovery feeds
    - Point-in-time financial fundamentals and promoter shareholding
    - Pre-trade qualitative event risk checklists
    """

    def __init__(self, db_session: Optional[Session] = None):
        self._external_db = db_session

    def ingest_filing(
        self,
        symbol: str,
        title: str,
        category: str,
        published_at: datetime.datetime,
        source: str = "NSE",
        file_url: Optional[str] = None,
        summary: Optional[str] = None,
        is_material_risk: bool = False,
        verification_status: str = "VERIFIED",
        instrument_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> CorporateFiling:
        """
        Ingests an authoritative corporate filing announcement with SHA-256 deduplication.
        """
        clean_symbol = symbol.strip().upper()
        # Compute deterministic content hash for deduplication
        hash_payload = f"{clean_symbol}:{title.strip()}:{published_at.isoformat()}"
        file_hash = compute_sha256(hash_payload)

        # Ensure published_at is timezone-aware
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=datetime.timezone.utc)

        with get_db(db or self._external_db) as session:
            existing = session.execute(
                select(CorporateFilingRecord).where(CorporateFilingRecord.file_hash == file_hash)
            ).scalars().first()

            if existing:
                return CorporateFiling.model_validate(existing)

            resolved_inst_id = instrument_id
            if not resolved_inst_id:
                pub_date = published_at.date()
                inst_rec = session.execute(
                    select(InstrumentSymbolHistory.instrument_id).where(
                        InstrumentSymbolHistory.symbol == clean_symbol,
                        InstrumentSymbolHistory.valid_from <= pub_date,
                        (InstrumentSymbolHistory.valid_to == None) | (InstrumentSymbolHistory.valid_to >= pub_date),
                    )
                ).scalars().first()
                if inst_rec:
                    resolved_inst_id = inst_rec

            filing_id = f"FIL-{uuid.uuid4().hex[:12].upper()}"
            record = CorporateFilingRecord(
                filing_id=filing_id,
                symbol=clean_symbol,
                instrument_id=resolved_inst_id,
                source=source,
                title=title.strip(),
                category=category.upper(),
                published_at=published_at,
                retrieved_at=datetime.datetime.now(datetime.timezone.utc),
                file_url=file_url,
                file_hash=file_hash,
                summary=summary,
                is_material_risk=is_material_risk,
                verification_status=verification_status,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return CorporateFiling.model_validate(record)

    def ingest_news(
        self,
        symbol: str,
        headline: str,
        published_at: datetime.datetime,
        source: str = "NSE",
        url: Optional[str] = None,
        summary: Optional[str] = None,
        sentiment: Optional[str] = None,
        verification_status: str = "UNVERIFIED",
        instrument_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> CompanyNews:
        """
        Ingests a company news article or announcement with SHA-256 deduplication.
        News text is treated strictly as untrusted content per Section 13.3.
        """
        clean_symbol = symbol.strip().upper()
        hash_payload = f"{clean_symbol}:{headline.strip()}:{published_at.isoformat()}"
        content_hash = compute_sha256(hash_payload)

        # Ensure published_at is timezone-aware
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=datetime.timezone.utc)

        with get_db(db or self._external_db) as session:
            existing = session.execute(
                select(CompanyNewsRecord).where(CompanyNewsRecord.content_hash == content_hash)
            ).scalars().first()

            if existing:
                return CompanyNews.model_validate(existing)

            resolved_inst_id = instrument_id
            if not resolved_inst_id:
                pub_date = published_at.date()
                inst_rec = session.execute(
                    select(InstrumentSymbolHistory.instrument_id).where(
                        InstrumentSymbolHistory.symbol == clean_symbol,
                        InstrumentSymbolHistory.valid_from <= pub_date,
                        (InstrumentSymbolHistory.valid_to == None) | (InstrumentSymbolHistory.valid_to >= pub_date),
                    )
                ).scalars().first()
                if inst_rec:
                    resolved_inst_id = inst_rec

            news_id = f"NEWS-{uuid.uuid4().hex[:12].upper()}"
            record = CompanyNewsRecord(
                news_id=news_id,
                symbol=clean_symbol,
                instrument_id=resolved_inst_id,
                source=source,
                headline=headline.strip(),
                url=url,
                published_at=published_at,
                retrieved_at=datetime.datetime.now(datetime.timezone.utc),
                content_hash=content_hash,
                summary=summary,
                sentiment=sentiment,
                verification_status=verification_status,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return CompanyNews.model_validate(record)

    def record_fundamentals(
        self,
        symbol: str,
        as_of_date: datetime.date,
        filing_date: Optional[datetime.date] = None,
        period_type: str = "ANNUAL",
        revenue: Optional[Decimal] = None,
        ebitda: Optional[Decimal] = None,
        pat: Optional[Decimal] = None,
        eps: Optional[Decimal] = None,
        pe_ratio: Optional[Decimal] = None,
        pb_ratio: Optional[Decimal] = None,
        roe: Optional[Decimal] = None,
        debt_to_equity: Optional[Decimal] = None,
        promoter_holding_pct: Optional[Decimal] = None,
        promoter_pledge_pct: Optional[Decimal] = None,
        data_source: str = "NSE_ANNUAL_REPORT",
        instrument_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> CompanyFundamentals:
        """
        Records or updates point-in-time company financial fundamentals and promoter metrics.
        """
        clean_symbol = symbol.strip().upper()

        with get_db(db or self._external_db) as session:
            existing = session.execute(
                select(CompanyFundamentalRecord).where(
                    CompanyFundamentalRecord.symbol == clean_symbol,
                    CompanyFundamentalRecord.as_of_date == as_of_date,
                    CompanyFundamentalRecord.period_type == period_type,
                )
            ).scalars().first()

            if existing:
                existing.filing_date = filing_date
                existing.revenue = revenue
                existing.ebitda = ebitda
                existing.pat = pat
                existing.eps = eps
                existing.pe_ratio = pe_ratio
                existing.pb_ratio = pb_ratio
                existing.roe = roe
                existing.debt_to_equity = debt_to_equity
                existing.promoter_holding_pct = promoter_holding_pct
                existing.promoter_pledge_pct = promoter_pledge_pct
                existing.data_source = data_source
                existing.retrieved_at = datetime.datetime.now(datetime.timezone.utc)
                session.commit()
                session.refresh(existing)
                return CompanyFundamentals.model_validate(existing)

            resolved_inst_id = instrument_id
            if not resolved_inst_id:
                inst_rec = session.execute(
                    select(InstrumentSymbolHistory.instrument_id).where(
                        InstrumentSymbolHistory.symbol == clean_symbol,
                        InstrumentSymbolHistory.valid_from <= as_of_date,
                        (InstrumentSymbolHistory.valid_to == None) | (InstrumentSymbolHistory.valid_to >= as_of_date),
                    )
                ).scalars().first()
                if inst_rec:
                    resolved_inst_id = inst_rec

            fund_id = f"FUND-{uuid.uuid4().hex[:12].upper()}"
            record = CompanyFundamentalRecord(
                fundamental_id=fund_id,
                symbol=clean_symbol,
                instrument_id=resolved_inst_id,
                as_of_date=as_of_date,
                filing_date=filing_date,
                period_type=period_type,
                revenue=revenue,
                ebitda=ebitda,
                pat=pat,
                eps=eps,
                pe_ratio=pe_ratio,
                pb_ratio=pb_ratio,
                roe=roe,
                debt_to_equity=debt_to_equity,
                promoter_holding_pct=promoter_holding_pct,
                promoter_pledge_pct=promoter_pledge_pct,
                data_source=data_source,
                retrieved_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return CompanyFundamentals.model_validate(record)

    def get_filings(
        self,
        symbol: str,
        days: int = 30,
        category: Optional[str] = None,
        as_of_date: Optional[datetime.date] = None,
        db: Optional[Session] = None,
    ) -> List[CorporateFiling]:
        """
        Retrieves trailing official filings and announcements for a symbol.
        """
        clean_symbol = symbol.strip().upper()
        target_date = as_of_date or datetime.date.today()
        cutoff_dt = datetime.datetime.combine(
            target_date - datetime.timedelta(days=days),
            datetime.time.min,
            tzinfo=datetime.timezone.utc,
        )
        end_dt = datetime.datetime.combine(
            target_date,
            datetime.time.max,
            tzinfo=datetime.timezone.utc,
        )

        with get_db(db or self._external_db) as session:
            stmt = select(CorporateFilingRecord).where(
                CorporateFilingRecord.symbol == clean_symbol,
                CorporateFilingRecord.published_at >= cutoff_dt,
                CorporateFilingRecord.published_at <= end_dt,
            )
            if category:
                stmt = stmt.where(CorporateFilingRecord.category == category.upper())

            stmt = stmt.order_by(CorporateFilingRecord.published_at.desc())
            records = session.execute(stmt).scalars().all()
            return [CorporateFiling.model_validate(r) for r in records]

    def get_news(
        self,
        symbol: str,
        days: int = 30,
        as_of_date: Optional[datetime.date] = None,
        db: Optional[Session] = None,
    ) -> List[CompanyNews]:
        """
        Retrieves trailing news articles and announcements for a symbol.
        """
        clean_symbol = symbol.strip().upper()
        target_date = as_of_date or datetime.date.today()
        cutoff_dt = datetime.datetime.combine(
            target_date - datetime.timedelta(days=days),
            datetime.time.min,
            tzinfo=datetime.timezone.utc,
        )
        end_dt = datetime.datetime.combine(
            target_date,
            datetime.time.max,
            tzinfo=datetime.timezone.utc,
        )

        with get_db(db or self._external_db) as session:
            stmt = (
                select(CompanyNewsRecord)
                .where(
                    CompanyNewsRecord.symbol == clean_symbol,
                    CompanyNewsRecord.published_at >= cutoff_dt,
                    CompanyNewsRecord.published_at <= end_dt,
                )
                .order_by(CompanyNewsRecord.published_at.desc())
            )
            records = session.execute(stmt).scalars().all()
            return [CompanyNews.model_validate(r) for r in records]

    def get_fundamentals(
        self,
        symbol: str,
        as_of_date: Optional[datetime.date] = None,
        db: Optional[Session] = None,
    ) -> Optional[CompanyFundamentals]:
        """
        Retrieves point-in-time financial fundamentals and promoter metrics as of as_of_date.
        """
        clean_symbol = symbol.strip().upper()
        target_date = as_of_date or datetime.date.today()

        with get_db(db or self._external_db) as session:
            stmt = (
                select(CompanyFundamentalRecord)
                .where(
                    CompanyFundamentalRecord.symbol == clean_symbol,
                    CompanyFundamentalRecord.as_of_date <= target_date,
                )
                .order_by(
                    CompanyFundamentalRecord.as_of_date.desc(),
                    CompanyFundamentalRecord.retrieved_at.desc(),
                )
            )
            record = session.execute(stmt).scalars().first()
            if not record:
                return None
            return CompanyFundamentals.model_validate(record)

    def evaluate_pre_trade_checklist(
        self,
        symbol: str,
        as_of_date: Optional[datetime.date] = None,
        holding_days: int = 10,
        db: Optional[Session] = None,
    ) -> PreTradeEventChecklist:
        """
        Evaluates qualitative event risk checklist for a swing trade candidate:
        1. Results blackout window
        2. Equity dilution / fundraising notices
        3. Promoter holding and pledge risk (>25%)
        4. Material regulatory / litigation actions
        """
        clean_symbol = symbol.strip().upper()
        target_date = as_of_date or datetime.date.today()
        items: List[PreTradeRiskItem] = []

        with get_db(db or self._external_db) as session:
            # 1. Results Announcement Blackout Window
            window_end = target_date + datetime.timedelta(days=holding_days)
            cutoff_dt = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=datetime.timezone.utc)
            window_end_dt = datetime.datetime.combine(window_end, datetime.time.max, tzinfo=datetime.timezone.utc)

            upcoming_results = session.execute(
                select(CorporateFilingRecord).where(
                    CorporateFilingRecord.symbol == clean_symbol,
                    CorporateFilingRecord.category == FilingCategory.RESULTS.value,
                    CorporateFilingRecord.published_at >= cutoff_dt,
                    CorporateFilingRecord.published_at <= window_end_dt,
                )
            ).scalars().all()

            if upcoming_results:
                res_date = upcoming_results[0].published_at.date()
                items.append(
                    PreTradeRiskItem(
                        category="RESULTS_ANNOUNCEMENT",
                        status="BLOCKING",
                        description=f"Earnings results disclosure scheduled on {res_date} inside {holding_days}-day holding window",
                        source_reference=upcoming_results[0].filing_id,
                    )
                )
            else:
                items.append(
                    PreTradeRiskItem(
                        category="RESULTS_ANNOUNCEMENT",
                        status="CLEAR",
                        description=f"No results announcement scheduled within {holding_days}-day holding window",
                        source_reference=None,
                    )
                )

            # 2. Fundraising / Dilution
            trail_30_dt = datetime.datetime.combine(
                target_date - datetime.timedelta(days=30), datetime.time.min, tzinfo=datetime.timezone.utc
            )
            fundraising = session.execute(
                select(CorporateFilingRecord).where(
                    CorporateFilingRecord.symbol == clean_symbol,
                    CorporateFilingRecord.category == FilingCategory.FUNDRAISING.value,
                    CorporateFilingRecord.published_at >= trail_30_dt,
                    CorporateFilingRecord.published_at <= cutoff_dt,
                )
            ).scalars().all()

            if fundraising:
                items.append(
                    PreTradeRiskItem(
                        category="FUNDRAISING_DILUTION",
                        status="WARNING",
                        description=f"Recent equity fundraising / dilution notice ({fundraising[0].title}) in trailing 30 days",
                        source_reference=fundraising[0].filing_id,
                    )
                )
            else:
                items.append(
                    PreTradeRiskItem(
                        category="FUNDRAISING_DILUTION",
                        status="CLEAR",
                        description="No recent equity dilution / fundraising notices in trailing 30 days",
                        source_reference=None,
                    )
                )

            # 3. Promoter Holding & Pledge
            fund_stmt = (
                select(CompanyFundamentalRecord)
                .where(
                    CompanyFundamentalRecord.symbol == clean_symbol,
                    CompanyFundamentalRecord.as_of_date <= target_date,
                )
                .order_by(CompanyFundamentalRecord.as_of_date.desc())
            )
            fund_rec = session.execute(fund_stmt).scalars().first()

            if fund_rec and fund_rec.promoter_pledge_pct is not None:
                pledge_pct = Decimal(str(fund_rec.promoter_pledge_pct))
                if pledge_pct > Decimal("0.25"):
                    items.append(
                        PreTradeRiskItem(
                            category="PROMOTER_PLEDGE",
                            status="BLOCKING",
                            description=f"Promoter pledge ({pledge_pct * Decimal('100'):.2f}%) exceeds 25.0% threshold",
                            source_reference=fund_rec.fundamental_id,
                        )
                    )
                else:
                    items.append(
                        PreTradeRiskItem(
                            category="PROMOTER_PLEDGE",
                            status="CLEAR",
                            description=f"Promoter pledge compliant ({pledge_pct * Decimal('100'):.2f}%)",
                            source_reference=fund_rec.fundamental_id,
                        )
                    )
            else:
                items.append(
                    PreTradeRiskItem(
                        category="PROMOTER_PLEDGE",
                        status="UNKNOWN",
                        description="Promoter pledge data is unavailable (non-blocking advisory)",
                        source_reference=None,
                    )
                )

            # 4. Regulatory & Litigation Filings
            trail_60_dt = datetime.datetime.combine(
                target_date - datetime.timedelta(days=60), datetime.time.min, tzinfo=datetime.timezone.utc
            )
            reg_filings = session.execute(
                select(CorporateFilingRecord).where(
                    CorporateFilingRecord.symbol == clean_symbol,
                    (CorporateFilingRecord.category == FilingCategory.REGULATORY_LITIGATION.value)
                    | (CorporateFilingRecord.is_material_risk == True),
                    CorporateFilingRecord.published_at >= trail_60_dt,
                    CorporateFilingRecord.published_at <= cutoff_dt,
                )
            ).scalars().all()

            if reg_filings:
                items.append(
                    PreTradeRiskItem(
                        category="REGULATORY_LITIGATION",
                        status="WARNING",
                        description=f"Material regulatory/legal action disclosed ({reg_filings[0].title}) in trailing 60 days",
                        source_reference=reg_filings[0].filing_id,
                    )
                )
            else:
                items.append(
                    PreTradeRiskItem(
                        category="REGULATORY_LITIGATION",
                        status="CLEAR",
                        description="No material regulatory or legal actions disclosed in trailing 60 days",
                        source_reference=None,
                    )
                )

        has_blocking = any(item.status == "BLOCKING" for item in items)
        has_warning_or_unknown = any(item.status in ("WARNING", "UNKNOWN") for item in items)

        if has_blocking:
            overall = "BLOCKED"
        elif has_warning_or_unknown:
            overall = "CAUTION"
        else:
            overall = "CLEAR"

        return PreTradeEventChecklist(
            symbol=clean_symbol,
            as_of_date=target_date,
            overall_status=overall,
            items=items,
        )
