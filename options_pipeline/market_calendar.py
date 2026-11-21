"""Conservative NYSE session calendar. Unknown calendar years fail closed.

The embedded calendar is verified against the published 2026 NYSE schedule.
Extend it only from an authoritative exchange calendar before using later years.
"""
from datetime import date, time, timedelta

SUPPORTED_YEAR = 2026
HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26),
    date(2026, 12, 25),
}
EARLY_CLOSES = {date(2026, 11, 27), date(2026, 12, 24)}


class CalendarCoverageError(ValueError):
    pass


def is_trading_day(day: date) -> bool | None:
    if day.year != SUPPORTED_YEAR:
        return None
    return day.weekday() < 5 and day not in HOLIDAYS


def session_close(day: date) -> time:
    if day.year != SUPPORTED_YEAR:
        raise CalendarCoverageError(f"CALENDAR_YEAR_UNVERIFIED:{day.year}")
    state = is_trading_day(day)
    if state is not True:
        raise CalendarCoverageError(f"NOT_A_TRADING_SESSION:{day.isoformat()}")
    return time(13, 0) if day in EARLY_CLOSES else time(16, 0)


def previous_trading_day(day: date) -> date | None:
    cursor = day - timedelta(days=1)
    for _ in range(8):
        state = is_trading_day(cursor)
        if state is None:
            return None
        if state:
            return cursor
        cursor -= timedelta(days=1)
    return None

