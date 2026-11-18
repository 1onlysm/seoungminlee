"""Guarded, offline close-to-close historical volatility helpers.

This module never acquires market data. A caller must separately establish
source provenance, symbol identity, adjustment consistency, and the expected
trading-session sequence before a production calculation is permitted.
Synthetic data belongs in tests only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
import re
import statistics
from typing import Iterable, Sequence


class HistoricalVolatilityError(ValueError):
    """Input failed the frozen historical-volatility contract."""


@dataclass(frozen=True)
class OHLCObservation:
    session_date: str
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class HVResult:
    symbol: str
    window_returns: int
    annualized_percent: float
    first_session: str
    last_session: str
    source_sha256: str
    adjustment_convention: str
    annualization_factor: int = 252
    standard_deviation: str = "sample_ddof_1"
    return_method: str = "close_to_close_log_return"


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KNOWN_ADJUSTMENTS = {"RAW_UNADJUSTED", "SPLIT_ADJUSTED", "SPLIT_AND_DIVIDEND_ADJUSTED"}


def validate_ohlc_window(
    rows: Sequence[OHLCObservation],
    *,
    expected_sessions: Sequence[str],
    as_of_date: str,
    symbol: str,
    source_verdict: str,
    source_sha256: str,
    adjustment_convention: str,
    adjustment_consistent: bool,
) -> None:
    """Reject any window that has not passed explicit provenance/data gates."""
    if source_verdict != "VERIFIED_REUSABLE_HISTORY":
        raise HistoricalVolatilityError("source provenance is not verified reusable history")
    if symbol != "NVDA":
        raise HistoricalVolatilityError("ticker identity must be NVDA common stock")
    if not _SHA256.fullmatch(source_sha256 or ""):
        raise HistoricalVolatilityError("source SHA-256 is missing or invalid")
    if adjustment_convention not in _KNOWN_ADJUSTMENTS:
        raise HistoricalVolatilityError("price adjustment convention is unknown")
    if adjustment_consistent is not True:
        raise HistoricalVolatilityError("corporate-action adjustment consistency is unverified")
    try:
        as_of = date.fromisoformat(as_of_date)
    except (TypeError, ValueError) as exc:
        raise HistoricalVolatilityError("as-of date must be an ISO calendar date") from exc
    if len(rows) < 2:
        raise HistoricalVolatilityError("at least two closing prices are required")
    if len(expected_sessions) != len(rows):
        raise HistoricalVolatilityError("expected session list must match the supplied window")
    if [row.session_date for row in rows] != list(expected_sessions):
        raise HistoricalVolatilityError("missing, duplicate, unsorted, or unexpected trading session")

    previous: date | None = None
    for row in rows:
        try:
            session = date.fromisoformat(row.session_date)
        except (TypeError, ValueError) as exc:
            raise HistoricalVolatilityError("session dates must be ISO calendar dates") from exc
        if session > as_of:
            raise HistoricalVolatilityError("future observations are not permitted")
        if previous is not None and session <= previous:
            raise HistoricalVolatilityError("session dates must be strictly increasing and unique")
        previous = session
        values = (row.open, row.high, row.low, row.close)
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            raise HistoricalVolatilityError("OHLC values must be finite numbers")
        if any(value <= 0 for value in values):
            raise HistoricalVolatilityError("OHLC prices must be positive")
        if row.low > row.open or row.low > row.close or row.open > row.high or row.close > row.high:
            raise HistoricalVolatilityError("OHLC relationship is invalid")


def calculate_historical_volatility(
    rows: Sequence[OHLCObservation],
    *,
    window_returns: int,
    expected_sessions: Sequence[str],
    as_of_date: str,
    symbol: str,
    source_verdict: str,
    source_sha256: str,
    adjustment_convention: str,
    adjustment_consistent: bool,
) -> HVResult:
    """Calculate annualized sample SD of N close-to-close log returns.

    Exactly N+1 eligible closes are required for N returns. This function is
    intentionally not wired to production dashboard data until an eligible
    source has independently passed the source audit.
    """
    if not isinstance(window_returns, int) or window_returns < 2:
        raise HistoricalVolatilityError("window_returns must be an integer of at least 2")
    if len(rows) != window_returns + 1:
        raise HistoricalVolatilityError("N returns require exactly N+1 closing-price observations")
    validate_ohlc_window(
        rows,
        expected_sessions=expected_sessions,
        as_of_date=as_of_date,
        symbol=symbol,
        source_verdict=source_verdict,
        source_sha256=source_sha256,
        adjustment_convention=adjustment_convention,
        adjustment_consistent=adjustment_consistent,
    )
    returns = [math.log(float(current.close) / float(previous.close)) for previous, current in zip(rows, rows[1:])]
    value = statistics.stdev(returns) * math.sqrt(252) * 100
    if not math.isfinite(value):
        raise HistoricalVolatilityError("calculation produced a non-finite result")
    return HVResult(
        symbol=symbol,
        window_returns=window_returns,
        annualized_percent=value,
        first_session=rows[0].session_date,
        last_session=rows[-1].session_date,
        source_sha256=source_sha256,
        adjustment_convention=adjustment_convention,
    )


def calculate_available_windows(
    rows: Sequence[OHLCObservation], *, windows: Iterable[int] = (10, 20, 30, 60), **contract: object
) -> dict[str, HVResult | None]:
    """Calculate only windows with enough trailing rows; never bridge gaps.

    ``expected_sessions`` must be provided for the entire supplied sequence.
    Results are keyed HV10/HV20/...; insufficient windows map to None.
    """
    out: dict[str, HVResult | None] = {}
    for window in windows:
        key = f"HV{window}"
        if len(rows) < window + 1:
            out[key] = None
            continue
        trailing = rows[-(window + 1):]
        sessions = list(contract["expected_sessions"])[-(window + 1):]
        out[key] = calculate_historical_volatility(
            trailing,
            window_returns=window,
            expected_sessions=sessions,
            **{k: v for k, v in contract.items() if k != "expected_sessions"},
        )
    return out
