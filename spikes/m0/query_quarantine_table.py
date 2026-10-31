from signal_atlas.db.session import get_db
from signal_atlas.db.models import DailyPriceQuarantine
from sqlalchemy import select

def show_quarantine():
    with get_db() as db:
        rows = db.execute(select(DailyPriceQuarantine).order_by(DailyPriceQuarantine.trade_date, DailyPriceQuarantine.row_number)).scalars().all()
        print(f"Total rows in daily_price_quarantine: {len(rows)}\n")
        print(f"{'Date':<12} | {'Row':<5} | {'Symbol':<12} | {'Series':<6} | {'ISIN':<12} | {'Rule':<22} | {'Message':<60}")
        print("-" * 130)
        for r in rows:
            print(f"{str(r.trade_date):<12} | {r.row_number or 0:<5} | {r.symbol or '':<12} | {r.series or '':<6} | {r.isin or '':<12} | {r.validation_rule:<22} | {r.validation_message:<60}")

if __name__ == "__main__":
    show_quarantine()
