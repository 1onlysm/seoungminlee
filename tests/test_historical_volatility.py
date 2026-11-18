"""All price rows in this module are synthetic TEST_ONLY fixtures."""

from datetime import date, timedelta
import math
import unittest

from options_collector.historical_volatility import (
    HistoricalVolatilityError,
    OHLCObservation,
    calculate_available_windows,
    calculate_historical_volatility,
)


TEST_ONLY_SHA = "a" * 64


def rows_from_closes(closes, start="2025-01-01"):
    first = date.fromisoformat(start)
    return [
        OHLCObservation((first + timedelta(days=i)).isoformat(), float(value), float(value), float(value), float(value))
        for i, value in enumerate(closes)
    ]


def contract(rows, **overrides):
    values = {
        "expected_sessions": [row.session_date for row in rows],
        "as_of_date": "2026-12-31",
        "symbol": "NVDA",
        "source_verdict": "VERIFIED_REUSABLE_HISTORY",
        "source_sha256": TEST_ONLY_SHA,
        "adjustment_convention": "SPLIT_ADJUSTED",
        "adjustment_consistent": True,
    }
    values.update(overrides)
    return values


class HistoricalVolatilityTests(unittest.TestCase):
    def test_constant_prices_yield_zero(self):
        rows = rows_from_closes([100] * 11)
        result = calculate_historical_volatility(rows, window_returns=10, **contract(rows))
        self.assertEqual(result.annualized_percent, 0.0)

    def test_known_analytical_series_uses_sample_sd_and_annualizes_once(self):
        # TEST_ONLY: log returns are [+a, -a, +a], a=ln(1.01).
        # Sample SD = 2a/sqrt(3); annualized percent = SD*sqrt(252)*100.
        rows = rows_from_closes([100, 101, 100, 101])
        result = calculate_historical_volatility(rows, window_returns=3, **contract(rows))
        expected = (2 * math.log(1.01) / math.sqrt(3)) * math.sqrt(252) * 100
        self.assertAlmostEqual(result.annualized_percent, expected, places=12)
        self.assertEqual(result.standard_deviation, "sample_ddof_1")
        self.assertEqual(result.annualization_factor, 252)

    def test_n_returns_require_n_plus_one_closes(self):
        rows = rows_from_closes([100, 101, 102])
        with self.assertRaisesRegex(HistoricalVolatilityError, r"N\+1"):
            calculate_historical_volatility(rows, window_returns=3, **contract(rows))

    def test_insufficient_window_returns_rejected(self):
        rows = rows_from_closes([100, 101])
        with self.assertRaises(HistoricalVolatilityError):
            calculate_historical_volatility(rows, window_returns=1, **contract(rows))

    def test_negative_and_zero_ohlc_prices_rejected(self):
        for bad in (-1.0, 0.0):
            rows = rows_from_closes([100, 101, 102])
            rows[1] = OHLCObservation(rows[1].session_date, bad, bad, bad, bad)
            with self.subTest(price=bad), self.assertRaisesRegex(HistoricalVolatilityError, "positive"):
                calculate_historical_volatility(rows, window_returns=2, **contract(rows))

    def test_nan_and_infinity_rejected(self):
        for bad in (float("nan"), float("inf")):
            rows = rows_from_closes([100, 101, 102])
            rows[1] = OHLCObservation(rows[1].session_date, 100, 101, 99, bad)
            with self.subTest(price=bad), self.assertRaisesRegex(HistoricalVolatilityError, "finite"):
                calculate_historical_volatility(rows, window_returns=2, **contract(rows))

    def test_duplicate_dates_rejected(self):
        rows = rows_from_closes([100, 101, 102])
        rows[2] = OHLCObservation(rows[1].session_date, 102, 102, 102, 102)
        with self.assertRaisesRegex(HistoricalVolatilityError, "strictly increasing"):
            calculate_historical_volatility(rows, window_returns=2, **contract(rows))

    def test_unsorted_dates_rejected(self):
        rows = rows_from_closes([100, 101, 102])
        rows[1], rows[2] = rows[2], rows[1]
        with self.assertRaises(HistoricalVolatilityError):
            calculate_historical_volatility(rows, window_returns=2, **contract(rows))

    def test_missing_expected_session_rejected(self):
        rows = rows_from_closes([100, 101, 102])
        expected = [rows[0].session_date, "2025-01-02", "2025-01-06"]
        with self.assertRaisesRegex(HistoricalVolatilityError, "missing, duplicate"):
            calculate_historical_volatility(rows, window_returns=2, **contract(rows, expected_sessions=expected))

    def test_wrong_ticker_blocks(self):
        rows = rows_from_closes([100, 101, 102])
        with self.assertRaisesRegex(HistoricalVolatilityError, "ticker identity"):
            calculate_historical_volatility(rows, window_returns=2, **contract(rows, symbol="NVDX"))

    def test_unverified_source_blocks(self):
        rows = rows_from_closes([100, 101, 102])
        for state in ("SOURCE_ABSENT", "PRESENT_PROVENANCE_PENDING", "TEST_FIXTURE_ONLY"):
            with self.subTest(state=state), self.assertRaisesRegex(HistoricalVolatilityError, "provenance"):
                calculate_historical_volatility(rows, window_returns=2, **contract(rows, source_verdict=state))

    def test_unknown_adjustment_blocks(self):
        rows = rows_from_closes([100, 101, 102])
        with self.assertRaisesRegex(HistoricalVolatilityError, "adjustment convention is unknown"):
            calculate_historical_volatility(rows, window_returns=2, **contract(rows, adjustment_convention="UNKNOWN"))

    def test_inconsistent_corporate_action_adjustment_blocks(self):
        rows = rows_from_closes([100, 101, 102])
        with self.assertRaisesRegex(HistoricalVolatilityError, "corporate-action"):
            calculate_historical_volatility(rows, window_returns=2, **contract(rows, adjustment_consistent=False))

    def test_bad_provenance_digest_blocks(self):
        rows = rows_from_closes([100, 101, 102])
        with self.assertRaisesRegex(HistoricalVolatilityError, "SHA-256"):
            calculate_historical_volatility(rows, window_returns=2, **contract(rows, source_sha256="not-a-digest"))

    def test_future_observations_rejected(self):
        rows = rows_from_closes([100, 101, 102])
        with self.assertRaisesRegex(HistoricalVolatilityError, "future observations"):
            calculate_historical_volatility(rows, window_returns=2, **contract(rows, as_of_date="2025-01-02"))

    def test_invalid_ohlc_relationship_rejected(self):
        rows = rows_from_closes([100, 101, 102])
        rows[1] = OHLCObservation(rows[1].session_date, 100, 99, 98, 100)
        with self.assertRaisesRegex(HistoricalVolatilityError, "OHLC relationship"):
            calculate_historical_volatility(rows, window_returns=2, **contract(rows))

    def test_available_windows_require_full_trailing_samples(self):
        rows = rows_from_closes([100 + i for i in range(31)])
        result = calculate_available_windows(rows, **contract(rows))
        self.assertIsNotNone(result["HV10"])
        self.assertIsNotNone(result["HV20"])
        self.assertIsNotNone(result["HV30"])
        self.assertIsNone(result["HV60"])

    def test_fixture_provenance_is_test_only_and_not_dashboard_payload(self):
        rows = rows_from_closes([100, 101, 100, 101])
        result = calculate_historical_volatility(rows, window_returns=3, **contract(rows))
        self.assertEqual(result.source_sha256, TEST_ONLY_SHA)
        self.assertEqual(result.symbol, "NVDA")
        # The helper returns a calculation record only; no dashboard serializer/output is provided.
        self.assertFalse(hasattr(result, "to_dashboard_payload"))


if __name__ == "__main__":
    unittest.main()
