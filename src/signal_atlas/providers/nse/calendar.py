import datetime
from typing import Dict, List, Optional, Set, Tuple

# Authoritative NSE Capital Market (Equities) Trading Holidays (2022–2024)
# Sourced from official NSE Circulars:
# 2022: Circular NSE/CMTR/50560 (Ref: 117/2021)
# 2023: Circular NSE/CMTR/54759 (Ref: 153/2022)
# 2024: Circular NSE/CMTR/59648 (Ref: 173/2023) + Additional Government Declarations
NSE_CONFIRMED_HOLIDAYS: Dict[datetime.date, str] = {
    # 2022
    datetime.date(2022, 1, 26): "Republic Day",
    datetime.date(2022, 3, 1): "Mahashivratri",
    datetime.date(2022, 3, 18): "Holi",
    datetime.date(2022, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti / Mahavir Jayanti",
    datetime.date(2022, 4, 15): "Good Friday",
    datetime.date(2022, 5, 3): "Id-Ul-Fitr (Ramzan Id)",
    datetime.date(2022, 8, 9): "Moharram",
    datetime.date(2022, 8, 15): "Independence Day",
    datetime.date(2022, 8, 31): "Ganesh Chaturthi",
    datetime.date(2022, 10, 5): "Dussehra",
    datetime.date(2022, 10, 26): "Diwali Balipratipada",
    datetime.date(2022, 11, 8): "Gurunanak Jayanti",
    # 2023
    datetime.date(2023, 1, 26): "Republic Day",
    datetime.date(2023, 3, 7): "Holi",
    datetime.date(2023, 3, 30): "Ram Navami",
    datetime.date(2023, 4, 4): "Mahavir Jayanti",
    datetime.date(2023, 4, 7): "Good Friday",
    datetime.date(2023, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    datetime.date(2023, 5, 1): "Maharashtra Day",
    datetime.date(2023, 6, 29): "Bakri Id (Eid-ul-Adha) (shifted from June 28 by circular NSE/CMTR/57324)",
    datetime.date(2023, 8, 15): "Independence Day",
    datetime.date(2023, 9, 19): "Ganesh Chaturthi",
    datetime.date(2023, 10, 2): "Mahatma Gandhi Jayanti",
    datetime.date(2023, 10, 24): "Dussehra",
    datetime.date(2023, 11, 14): "Diwali Balipratipada",
    datetime.date(2023, 11, 27): "Gurunanak Jayanti",
    datetime.date(2023, 12, 25): "Christmas",
    # 2024
    datetime.date(2024, 1, 22): "Ayodhya Ram Mandir Ceremony",
    datetime.date(2024, 1, 26): "Republic Day",
    datetime.date(2024, 3, 8): "Mahashivratri",
    datetime.date(2024, 3, 25): "Holi",
    datetime.date(2024, 3, 29): "Good Friday",
    datetime.date(2024, 4, 11): "Id-Ul-Fitr",
    datetime.date(2024, 4, 17): "Shri Ram Navmi",
    datetime.date(2024, 5, 1): "Maharashtra Day",
    datetime.date(2024, 5, 20): "General Parliamentary Elections (Mumbai)",
    datetime.date(2024, 6, 17): "Bakri Id",
    datetime.date(2024, 7, 17): "Moharram",
    datetime.date(2024, 8, 15): "Independence Day / Parsi New Year",
    datetime.date(2024, 10, 2): "Mahatma Gandhi Jayanti",
    datetime.date(2024, 11, 15): "Gurunanak Jayanti",
    datetime.date(2024, 11, 20): "Maharashtra Assembly Elections",
    datetime.date(2024, 12, 25): "Christmas",
}

# Special Weekend Trading Sessions (e.g. disaster recovery drills or Sunday Muhurat trading)
SPECIAL_WEEKEND_SESSIONS: Set[datetime.date] = {
    datetime.date(2023, 11, 12),  # Sunday Muhurat Trading session
    datetime.date(2024, 1, 20),   # Saturday Full-day Live session (pre-Jan 22 compensatory)
    datetime.date(2024, 3, 2),    # Saturday DR Live Switchover session
    datetime.date(2024, 5, 18),   # Saturday DR Live Switchover session
}


class NSETradingCalendar:
    """
    Authoritative trading calendar for NSE Cash Equities.
    Differentiates confirmed holidays, weekends, expected trading days,
    and missing/unresolved trading dates.
    """

    @staticmethod
    def is_confirmed_holiday(dt: datetime.date) -> Tuple[bool, Optional[str]]:
        """Check if date is a confirmed official NSE holiday."""
        if dt in NSE_CONFIRMED_HOLIDAYS:
            return True, NSE_CONFIRMED_HOLIDAYS[dt]
        return False, None

    @classmethod
    def is_expected_trading_day(cls, dt: datetime.date) -> Tuple[bool, str]:
        """
        Determine whether dt was an expected trading session according to the authoritative calendar.

        Returns:
            Tuple of (is_expected: bool, reason: str)
        """
        is_hol, hol_name = cls.is_confirmed_holiday(dt)
        if is_hol:
            return False, f"HOLIDAY: {hol_name}"

        if dt in SPECIAL_WEEKEND_SESSIONS:
            return True, "SPECIAL_WEEKEND_TRADING_SESSION"

        if dt.weekday() >= 5:
            day_name = dt.strftime("%A")
            return False, f"WEEKEND ({day_name})"

        return True, "EXPECTED_TRADING_DAY"

    @classmethod
    def get_expected_trading_days(
        cls,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> List[datetime.date]:
        """Return list of all scheduled trading dates between start_date and end_date."""
        expected = []
        curr = start_date
        while curr <= end_date:
            is_expected, _ = cls.is_expected_trading_day(curr)
            if is_expected:
                expected.append(curr)
            curr += datetime.timedelta(days=1)
        return expected

    @classmethod
    def get_missing_trading_days(
        cls,
        start_date: datetime.date,
        end_date: datetime.date,
        completed_dates: Set[datetime.date],
    ) -> List[datetime.date]:
        """
        Identify any expected trading day in [start_date, end_date]
        that is NOT in completed_dates (finds internal gaps as well as trailing gaps).
        """
        expected = cls.get_expected_trading_days(start_date, end_date)
        return [d for d in expected if d not in completed_dates]
