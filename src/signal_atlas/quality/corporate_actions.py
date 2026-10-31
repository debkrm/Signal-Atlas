"""
corporate_actions.py - Canonical Corporate Action Registry and Normalization Module.

Manages verified structural capital events (stock splits, bonus issues, capital reorganizations,
share class changes, and scheme mergers) with explicit provenance, exact share multipliers,
and predecessor/successor identity relationships.
"""

import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from sqlalchemy import select, delete

from signal_atlas.db.models import CorporateAction, Instrument, InstrumentSymbolHistory
from signal_atlas.db.session import get_db


class CorporateActionEvent(BaseModel):
    action_id: str
    instrument_id: str
    symbol: str
    series: str = "EQ"
    action_type: str  # STOCK_SPLIT, BONUS_ISSUE, CAPITAL_REORGANIZATION, ETF_SCHEME_RESTRUCTURING, etc.
    ex_date: datetime.date
    record_date: Optional[datetime.date] = None
    old_isin: Optional[str] = None
    new_isin: Optional[str] = None
    old_face_value: Optional[Decimal] = None
    new_face_value: Optional[Decimal] = None
    old_share_qty: Optional[Decimal] = None
    new_share_qty: Optional[Decimal] = None
    share_multiplier: Decimal = Decimal("1.0")
    cash_entitlement: Optional[Decimal] = None
    purpose: str
    issuing_organisation: str = "NSE"
    source_type: str = "EXCHANGE_CIRCULAR"
    source_circular: Optional[str] = None
    source_url: Optional[str] = None
    source_hash: Optional[str] = None
    publication_date: Optional[datetime.date] = None
    retrieved_at: Optional[datetime.datetime] = None
    identity_decision: str = "UNIFIED_IDENTITY"  # UNIFIED_IDENTITY, PREDECESSOR_SUCCESSOR, UNRESOLVED
    verification_status: str = "VERIFIED"  # VERIFIED, UNRESOLVED, REJECTED
    parser_version: str = "v1.0"


class CorporateActionRegistry:
    """
    Registry for managing and querying verified corporate action events.
    """

    @classmethod
    def persist_events(cls, events: List[CorporateActionEvent], session=None) -> int:
        """Persist corporate action events to PostgreSQL."""
        with get_db(session) as db:
            count = 0
            for ev in events:
                # Upsert or replace
                existing = db.execute(
                    select(CorporateAction).where(CorporateAction.action_id == ev.action_id)
                ).scalar()
                if existing:
                    for k, v in ev.model_dump().items():
                        setattr(existing, k, v)
                else:
                    db.add(CorporateAction(**ev.model_dump()))
                count += 1
            db.commit()
            return count

    @classmethod
    def export_registry(
        cls,
        events: List[CorporateActionEvent],
        json_path: Path = Path("data/checkpoints/corporate_action_registry.json"),
        csv_path: Path = Path("data/checkpoints/corporate_action_registry.csv"),
    ) -> None:
        """Export registry to JSON and CSV artifacts."""
        json_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        # JSON
        data = [ev.model_dump(mode="json") for ev in events]
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        # CSV
        import pandas as pd
        df = pd.DataFrame(data)
        df.to_csv(csv_path, index=False)

    @classmethod
    def get_events_for_instrument(cls, instrument_id: str, session=None) -> List[CorporateAction]:
        with get_db(session) as db:
            return db.execute(
                select(CorporateAction)
                .where(CorporateAction.instrument_id == instrument_id)
                .order_by(CorporateAction.ex_date)
            ).scalars().all()

    @classmethod
    def get_events_for_symbol(cls, symbol: str, session=None) -> List[CorporateAction]:
        with get_db(session) as db:
            return db.execute(
                select(CorporateAction)
                .where(CorporateAction.symbol == symbol)
                .order_by(CorporateAction.ex_date)
            ).scalars().all()
