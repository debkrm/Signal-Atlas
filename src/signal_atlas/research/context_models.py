"""
context_models.py - Pydantic Domain Models for Filings, News, and Fundamentals.
"""

import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class FilingCategory(str, Enum):
    RESULTS = "RESULTS"
    FUNDRAISING = "FUNDRAISING"
    PROMOTER_ACTION = "PROMOTER_ACTION"
    REGULATORY_LITIGATION = "REGULATORY_LITIGATION"
    M_AND_A = "M_AND_A"
    MATERIAL_CONTRACT = "MATERIAL_CONTRACT"
    GENERAL = "GENERAL"
    OTHER = "OTHER"


class CorporateFiling(BaseModel):
    """Domain model representing an authoritative corporate filing / exchange announcement."""
    model_config = ConfigDict(from_attributes=True)

    filing_id: str
    symbol: str
    instrument_id: Optional[str] = None
    source: str = "NSE"
    title: str
    category: Union[FilingCategory, str] = FilingCategory.GENERAL
    published_at: datetime.datetime
    retrieved_at: datetime.datetime
    file_url: Optional[str] = None
    file_hash: str
    summary: Optional[str] = None
    is_material_risk: bool = False
    verification_status: str = "VERIFIED"


class CompanyNews(BaseModel):
    """Domain model representing a verified news item or discovery announcement."""
    model_config = ConfigDict(from_attributes=True)

    news_id: str
    symbol: str
    instrument_id: Optional[str] = None
    source: str = "NSE"
    headline: str
    url: Optional[str] = None
    published_at: datetime.datetime
    retrieved_at: datetime.datetime
    content_hash: str
    summary: Optional[str] = None
    sentiment: Optional[str] = None
    verification_status: str = "UNVERIFIED"


class CompanyFundamentals(BaseModel):
    """Point-in-time financial fundamentals snapshot for a company."""
    model_config = ConfigDict(from_attributes=True)

    fundamental_id: str
    symbol: str
    instrument_id: Optional[str] = None
    as_of_date: datetime.date
    filing_date: Optional[datetime.date] = None
    period_type: str = "ANNUAL"
    revenue: Optional[Decimal] = None
    ebitda: Optional[Decimal] = None
    pat: Optional[Decimal] = None
    eps: Optional[Decimal] = None
    pe_ratio: Optional[Decimal] = None
    pb_ratio: Optional[Decimal] = None
    roe: Optional[Decimal] = None
    debt_to_equity: Optional[Decimal] = None
    promoter_holding_pct: Optional[Decimal] = None
    promoter_pledge_pct: Optional[Decimal] = None
    data_source: str = "NSE_ANNUAL_REPORT"
    retrieved_at: datetime.datetime


class PreTradeRiskItem(BaseModel):
    """Single item in the pre-trade qualitative checklist."""
    category: str
    status: str  # CLEAR, WARNING, BLOCKING, UNKNOWN
    description: str
    source_reference: Optional[str] = None


class PreTradeEventChecklist(BaseModel):
    """
    Comprehensive pre-trade qualitative event risk checklist.
    Audits upcoming results announcements, fundraising/dilution, promoter actions,
    and material regulatory/litigation issues per Architecture Section 13.3.
    """
    symbol: str
    as_of_date: datetime.date
    overall_status: str  # CLEAR, CAUTION, BLOCKED
    items: List[PreTradeRiskItem] = Field(default_factory=list)
    has_results_risk: bool = False
    has_dilution_risk: bool = False
    has_promoter_risk: bool = False
    has_regulatory_risk: bool = False
    notes: List[str] = Field(default_factory=list)
