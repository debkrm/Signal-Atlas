"""create corporate filings, company news, and fundamentals tables

Revision ID: 0014_news_filings_fundamentals
Revises: 0013_trade_journal
Create Date: 2026-11-01 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0014_news_filings_fundamentals"
down_revision: Union[str, None] = "0013_trade_journal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Corporate Filings
    op.create_table(
        "corporate_filings",
        sa.Column("filing_id", sa.String(length=64), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="NSE"),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("file_url", sa.String(length=512), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("is_material_risk", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verification_status", sa.String(length=32), nullable=False, server_default="VERIFIED"),
    )
    op.create_index("ix_corporate_filings_symbol", "corporate_filings", ["symbol"])
    op.create_index("ix_corporate_filings_instrument_id", "corporate_filings", ["instrument_id"])
    op.create_index("ix_corporate_filings_category", "corporate_filings", ["category"])
    op.create_index("ix_corporate_filings_published_at", "corporate_filings", ["published_at"])
    op.create_index("ix_corporate_filings_file_hash", "corporate_filings", ["file_hash"])

    # 2. Company News
    op.create_table(
        "company_news",
        sa.Column("news_id", sa.String(length=64), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="NSE"),
        sa.Column("headline", sa.String(length=256), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("sentiment", sa.String(length=16), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=False, server_default="UNVERIFIED"),
    )
    op.create_index("ix_company_news_symbol", "company_news", ["symbol"])
    op.create_index("ix_company_news_instrument_id", "company_news", ["instrument_id"])
    op.create_index("ix_company_news_published_at", "company_news", ["published_at"])
    op.create_index("ix_company_news_content_hash", "company_news", ["content_hash"])

    # 3. Company Fundamentals
    op.create_table(
        "company_fundamentals",
        sa.Column("fundamental_id", sa.String(length=64), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("period_type", sa.String(length=16), nullable=False, server_default="ANNUAL"),
        sa.Column("revenue", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("ebitda", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("pat", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("eps", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("pe_ratio", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("pb_ratio", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("roe", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("debt_to_equity", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("promoter_holding_pct", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("promoter_pledge_pct", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("data_source", sa.String(length=64), nullable=False, server_default="NSE_ANNUAL_REPORT"),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_company_fundamentals_symbol", "company_fundamentals", ["symbol"])
    op.create_index("ix_company_fundamentals_instrument_id", "company_fundamentals", ["instrument_id"])
    op.create_index("ix_company_fundamentals_as_of_date", "company_fundamentals", ["as_of_date"])


def downgrade() -> None:
    op.drop_table("company_fundamentals")
    op.drop_table("company_news")
    op.drop_table("corporate_filings")
