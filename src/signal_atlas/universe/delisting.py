"""
delisting.py - Deterministic Point-in-Time Delisting and Inactivity Detection.

Tracks trading activity per instrument to identify delistings, suspensions, and trading halts.
Ensures point-in-time universe construction never looks ahead or relies on future status.
"""

import datetime
from typing import Any, Dict, Optional, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from signal_atlas.db.models.calendar import TradingCalendar
from signal_atlas.db.models.instruments import Instrument, InstrumentSymbolHistory


def get_point_in_time_delisted_instruments(
    session: Session,
    as_of_date: datetime.date,
    inactive_sessions_threshold: int = 20,
) -> Dict[str, datetime.date]:
    """
    Returns instruments that ceased trading at least inactive_sessions_threshold
    prior to as_of_date, based strictly on records on or before as_of_date.
    
    Returns:
        Dict mapping instrument_id -> last_observed_trade_date
    """
    # 1. Determine recent session cutoff
    sessions = session.execute(
        text("""
            SELECT trade_date FROM trading_calendar
            WHERE is_trading_day = true AND trade_date <= :as_of_date
            ORDER BY trade_date DESC
            LIMIT :lim
        """),
        {"as_of_date": as_of_date, "lim": inactive_sessions_threshold + 1},
    ).scalars().all()

    if len(sessions) <= inactive_sessions_threshold:
        return {}

    cutoff_date = sessions[inactive_sessions_threshold]

    # 2. Find instruments whose last trade on or before as_of_date was <= cutoff_date
    rows = session.execute(
        text("""
            SELECT instrument_id, max(trade_date) as last_trade
            FROM daily_prices_raw
            WHERE trade_date <= :as_of_date
            GROUP BY instrument_id
            HAVING max(trade_date) <= :cutoff_date
        """),
        {"as_of_date": as_of_date, "cutoff_date": cutoff_date},
    ).fetchall()

    return {r[0]: r[1] for r in rows}


def detect_and_record_delistings(
    session: Session,
    as_of_date: Optional[datetime.date] = None,
    inactive_sessions_threshold: int = 20,
) -> Dict[str, Any]:
    """
    Scans trading activity and records delisting metadata in the database:
    - Sets Instrument.delisting_date = last_trade_date
    - Sets Instrument.status = 'DELISTED'
    - Closes open InstrumentSymbolHistory.valid_to = last_trade_date
    
    Strictly uses data available on or before as_of_date (or latest ingested date if None).
    """
    db = session
    if as_of_date is None:
        max_dt = db.execute(text("SELECT max(trade_date) FROM daily_prices_raw")).scalar()
        if not max_dt:
            return {"delisted_count": 0, "as_of_date": None}
        as_of_date = max_dt

    delisted_map = get_point_in_time_delisted_instruments(
        db, as_of_date, inactive_sessions_threshold=inactive_sessions_threshold
    )

    if not delisted_map:
        return {"delisted_count": 0, "as_of_date": as_of_date}

    updated_count = 0
    delisted_ids = list(delisted_map.keys())
    now_ts = datetime.datetime.now(datetime.timezone.utc)
    
    # Update in chunks of 500
    chunk_size = 500
    for i in range(0, len(delisted_ids), chunk_size):
        chunk = delisted_ids[i:i + chunk_size]
        for inst_id in chunk:
            last_dt = delisted_map[inst_id]
            db.execute(
                text("""
                    UPDATE instruments
                    SET delisting_date = :last_dt, status = 'DELISTED', updated_at = :now_ts
                    WHERE instrument_id = :inst_id AND (delisting_date IS NULL OR delisting_date != :last_dt)
                """),
                {"inst_id": inst_id, "last_dt": last_dt, "now_ts": now_ts},
            )
            db.execute(
                text("""
                    UPDATE instrument_symbol_history
                    SET valid_to = :last_dt
                    WHERE instrument_id = :inst_id AND (valid_to IS NULL OR valid_to > :last_dt)
                """),
                {"inst_id": inst_id, "last_dt": last_dt},
            )
            updated_count += 1

    db.commit()
    return {
        "as_of_date": as_of_date,
        "delisted_count": len(delisted_map),
        "updated_count": updated_count,
    }
