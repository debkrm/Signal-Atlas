import datetime
from collections import defaultdict
from signal_atlas.providers.nse.calendar import (
    NSE_CONFIRMED_HOLIDAYS,
    SPECIAL_WEEKEND_SESSIONS,
    NSETradingCalendar,
)
from signal_atlas.db.session import get_db
from signal_atlas.db.models import TradingCalendar

def reconcile_calendar():
    by_yr = defaultdict(list)
    for dt, name in sorted(NSE_CONFIRMED_HOLIDAYS.items()):
        by_yr[dt.year].append((dt, name))

    print("=== NSE_CONFIRMED_HOLIDAYS in calendar.py ===")
    total_hols = 0
    for yr in sorted(by_yr.keys()):
        print(f"{yr}: {len(by_yr[yr])} holidays")
        for dt, name in by_yr[yr]:
            print(f"  {dt} ({dt.strftime('%a')}): {name}")
        total_hols += len(by_yr[yr])
    print(f"Total confirmed holidays in calendar.py: {total_hols}")

    with get_db() as db:
        db_entries = db.query(TradingCalendar).filter(TradingCalendar.is_trading_day == False).all()
        print(f"\n=== Non-Trading Entries in Database trading_calendar ({len(db_entries)} rows) ===")
        db_by_yr = defaultdict(list)
        for h in db_entries:
            db_by_yr[h.trade_date.year].append(h)
        for yr in sorted(db_by_yr.keys()):
            print(f"{yr} in DB: {len(db_by_yr[yr])} entries")
            for h in sorted(db_by_yr[yr], key=lambda x: x.trade_date):
                print(f"  {h.trade_date} ({h.trade_date.strftime('%a')}): {h.holiday_name}")

if __name__ == "__main__":
    reconcile_calendar()
