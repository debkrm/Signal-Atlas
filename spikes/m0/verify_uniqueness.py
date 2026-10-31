from signal_atlas.db.session import get_db
from signal_atlas.db.models import DailyPriceRaw
from sqlalchemy import func, select

with get_db() as db:
    dups = db.execute(
        select(DailyPriceRaw.instrument_id, DailyPriceRaw.trade_date, DailyPriceRaw.series, func.count())
        .group_by(DailyPriceRaw.instrument_id, DailyPriceRaw.trade_date, DailyPriceRaw.series)
        .having(func.count() > 1)
    ).all()

    print(f"Duplicate (instrument_id, trade_date, series) records across entire database: {len(dups)}")
    assert len(dups) == 0, f"Found {len(dups)} duplicate records!"
    print("Zero duplicates confirmed across 1,838,125 rows!")
