"""
research_context.py - SQLAlchemy Models for Corporate Filings, News, and Fundamentals.
"""

import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from signal_atlas.db.base import Base


class CorporateFilingRecord(Base):
    """
    Official corporate filings and exchange announcements (NSE/BSE).
    Provides authoritative event classification, regulatory disclosure tracking,
    and deduplication via SHA-256 document hashes.
    """
    __tablename__ = "corporate_filings"

    filing_id = Column(String(64), primary_key=True)
    symbol = Column(String(32), nullable=False, index=True)
    instrument_id = Column(String(36), nullable=True, index=True)
    source = Column(String(32), nullable=False, default="NSE")
    title = Column(String(256), nullable=False)
    category = Column(String(64), nullable=False, index=True)
    published_at = Column(DateTime(timezone=True), nullable=False, index=True)
    retrieved_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    file_url = Column(String(512), nullable=True)
    file_hash = Column(String(64), nullable=False, index=True)
    summary = Column(Text, nullable=True)
    is_material_risk = Column(Boolean, nullable=False, default=False)
    verification_status = Column(String(32), nullable=False, default="VERIFIED")

    def __repr__(self) -> str:
        return f"<CorporateFilingRecord(filing_id='{self.filing_id}', symbol='{self.symbol}', category='{self.category}')>"


class CompanyNewsRecord(Base):
    """
    Company news articles and discovery events from verified feeds and RSS sources.
    Tracked with published timestamp, source attribution, and document hashing.
    """
    __tablename__ = "company_news"

    news_id = Column(String(64), primary_key=True)
    symbol = Column(String(32), nullable=False, index=True)
    instrument_id = Column(String(36), nullable=True, index=True)
    source = Column(String(64), nullable=False, default="NSE")
    headline = Column(String(256), nullable=False)
    url = Column(String(512), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=False, index=True)
    retrieved_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    content_hash = Column(String(64), nullable=False, index=True)
    summary = Column(Text, nullable=True)
    sentiment = Column(String(16), nullable=True)
    verification_status = Column(String(32), nullable=False, default="UNVERIFIED")

    def __repr__(self) -> str:
        return f"<CompanyNewsRecord(news_id='{self.news_id}', symbol='{self.symbol}', headline='{self.headline[:30]}')>"


class CompanyFundamentalRecord(Base):
    """
    Point-in-time company financial fundamentals and promoter shareholding.
    """
    __tablename__ = "company_fundamentals"

    fundamental_id = Column(String(64), primary_key=True)
    symbol = Column(String(32), nullable=False, index=True)
    instrument_id = Column(String(36), nullable=True, index=True)
    as_of_date = Column(Date, nullable=False, index=True)
    filing_date = Column(Date, nullable=True)
    period_type = Column(String(16), nullable=False, default="ANNUAL")
    revenue = Column(Numeric(16, 2), nullable=True)
    ebitda = Column(Numeric(16, 2), nullable=True)
    pat = Column(Numeric(16, 2), nullable=True)
    eps = Column(Numeric(10, 2), nullable=True)
    pe_ratio = Column(Numeric(10, 2), nullable=True)
    pb_ratio = Column(Numeric(10, 2), nullable=True)
    roe = Column(Numeric(8, 4), nullable=True)
    debt_to_equity = Column(Numeric(8, 4), nullable=True)
    promoter_holding_pct = Column(Numeric(6, 4), nullable=True)
    promoter_pledge_pct = Column(Numeric(6, 4), nullable=True)
    data_source = Column(String(64), nullable=False, default="NSE_ANNUAL_REPORT")
    retrieved_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<CompanyFundamentalRecord(symbol='{self.symbol}', as_of='{self.as_of_date}', pe='{self.pe_ratio}')>"
