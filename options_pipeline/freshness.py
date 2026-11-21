"""Options-chain freshness classification; capture time is never source time."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .market_calendar import CalendarCoverageError, is_trading_day, previous_trading_day, session_close

ET = ZoneInfo("America/New_York")
FRESHNESS_STATUSES = (
    "CURRENT_VERIFIED", "RECENT_NOT_CURRENT", "STALE",
    "SOURCE_TIME_UNAVAILABLE", "HTTP_FAILURE", "UNVERIFIED",
)


def parse_aware_datetime(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def classify_freshness(http_status, captured_at_utc, session_date_et, option_chain_asof):
    if http_status != 200:
        return {"status": "HTTP_FAILURE", "reason": f"HTTP_STATUS_{http_status}", "source_asof_et": None}
    capture = parse_aware_datetime(captured_at_utc)
    if capture is None or not isinstance(session_date_et, str):
        return {"status": "UNVERIFIED", "reason": "CAPTURE_OR_SESSION_DATE_UNVERIFIED", "source_asof_et": None}
    try:
        session = date.fromisoformat(session_date_et)
    except ValueError:
        return {"status": "UNVERIFIED", "reason": "INVALID_SESSION_DATE", "source_asof_et": None}
    if is_trading_day(session) is not True:
        return {"status": "UNVERIFIED", "reason": "SESSION_NOT_VERIFIED_BY_CALENDAR", "source_asof_et": None}
    source = parse_aware_datetime(option_chain_asof)
    if source is None:
        return {"status": "SOURCE_TIME_UNAVAILABLE", "reason": "OPTIONS_CHAIN_ASOF_MISSING_OR_UNTIMEZONED", "source_asof_et": None}
    capture_et, source_et = capture.astimezone(ET), source.astimezone(ET)
    if source_et > capture_et:
        return {"status": "UNVERIFIED", "reason": "SOURCE_TIME_AFTER_CAPTURE", "source_asof_et": source_et.isoformat()}
    if source_et.date() == session:
        try:
            close = session_close(session)
        except CalendarCoverageError:
            return {"status": "UNVERIFIED", "reason": "SESSION_CLOSE_UNVERIFIED", "source_asof_et": source_et.isoformat()}
        if source_et.time().replace(tzinfo=None) >= close:
            return {"status": "CURRENT_VERIFIED", "reason": "CHAIN_ASOF_AT_OR_AFTER_SESSION_CLOSE", "source_asof_et": source_et.isoformat()}
        return {"status": "RECENT_NOT_CURRENT", "reason": "CHAIN_ASOF_BEFORE_SESSION_CLOSE", "source_asof_et": source_et.isoformat()}
    prior = previous_trading_day(session)
    if prior is not None and source_et.date() == prior:
        return {"status": "RECENT_NOT_CURRENT", "reason": "CHAIN_ASOF_PREVIOUS_SESSION", "source_asof_et": source_et.isoformat()}
    if source_et.date() < session:
        return {"status": "STALE", "reason": "CHAIN_ASOF_OLDER_THAN_PREVIOUS_SESSION", "source_asof_et": source_et.isoformat()}
    return {"status": "UNVERIFIED", "reason": "CHAIN_ASOF_SESSION_MISMATCH", "source_asof_et": source_et.isoformat()}

