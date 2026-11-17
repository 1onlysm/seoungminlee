import csv
import json
import tempfile
import unittest
from pathlib import Path

from options_collector.provisional_analytics import analyze_contracts, write_outputs


class ProvisionalAnalyticsTests(unittest.TestCase):
    def test_missing_placeholders_are_not_zero(self):
        row = {"c_volume": "--", "p_volume": None, "c_openinterest": "", "p_openinterest": "--"}
        result = analyze_contracts("SPY", [row])
        self.assertEqual(result["call_volume_observed_sum"], 0)
        self.assertEqual(result["call_volume_observed_count"], 0)
        self.assertEqual(result["call_volume_missing_count"], 1)
        self.assertEqual(result["put_volume_missing_count"], 1)
        self.assertIsNone(result["observed_volume_pcr"])

    def test_explicit_zero_is_an_observed_value(self):
        result = analyze_contracts("SPY", [{"c_volume": "0", "p_volume": "4"}])
        self.assertEqual(result["call_volume_observed_count"], 1)
        self.assertEqual(result["call_volume_missing_count"], 0)
        self.assertEqual(result["call_volume_observed_sum"], 0)
        self.assertIsNone(result["observed_volume_pcr"])
        self.assertEqual(result["pcr_unavailable_reason"], "CALL_VOLUME_SUM_ZERO")

    def test_sums_coverage_and_pcr(self):
        rows = [
            {"c_volume": "10", "p_volume": "--", "c_openinterest": "2", "p_openinterest": "3"},
            {"c_volume": "5", "p_volume": "15", "c_openinterest": "0", "p_openinterest": "4"},
        ]
        result = analyze_contracts("MSTR", rows, "2026-11-17T03:00:00Z")
        self.assertEqual(result["call_volume_observed_sum"], 15)
        self.assertEqual(result["put_volume_observed_sum"], 15)
        self.assertEqual(result["call_oi_observed_sum"], 2)
        self.assertEqual(result["put_oi_observed_sum"], 7)
        self.assertEqual(result["call_volume_coverage_pct"], 100)
        self.assertEqual(result["put_volume_coverage_pct"], 50)
        self.assertEqual(result["observed_volume_pcr"], 1)
        self.assertEqual(result["status"], "PROVISIONAL")

    def test_no_contracts_has_null_coverage_and_pcr(self):
        result = analyze_contracts("MARA", [])
        self.assertIsNone(result["call_volume_coverage_pct"])
        self.assertIsNone(result["put_volume_coverage_pct"])
        self.assertIsNone(result["observed_volume_pcr"])
        self.assertEqual(result["pcr_unavailable_reason"], "NO_NUMERIC_CALL_VOLUME")

    def test_symbols_are_aggregated_independently(self):
        spy = analyze_contracts("SPY", [{"c_volume": "100", "p_volume": "10"}])
        qqq = analyze_contracts("QQQ", [{"c_volume": "2", "p_volume": "8"}])
        self.assertEqual((spy["call_volume_observed_sum"], spy["put_volume_observed_sum"]), (100, 10))
        self.assertEqual((qqq["call_volume_observed_sum"], qqq["put_volume_observed_sum"]), (2, 8))

    def test_invalid_count_is_not_silently_ignored(self):
        with self.assertRaisesRegex(ValueError, "NON_INTEGER_COUNT"):
            analyze_contracts("SPY", [{"c_volume": "--"}, {"c_volume": "unknown"}])

    def test_json_and_csv_outputs_round_trip(self):
        rows = [analyze_contracts("SPY", [{"c_volume": "10", "p_volume": "5", "c_openinterest": "3", "p_openinterest": "7"}])]
        with tempfile.TemporaryDirectory() as directory:
            json_path, csv_path = write_outputs(rows, directory)
            loaded = json.loads(json_path.read_text())
            with csv_path.open(newline="", encoding="utf-8") as handle:
                csv_rows = list(csv.DictReader(handle))
        self.assertEqual(loaded["symbols"][0]["observed_volume_pcr"], 0.5)
        self.assertEqual(csv_rows[0]["symbol"], "SPY")
        self.assertEqual(csv_rows[0]["status"], "PROVISIONAL")


if __name__ == "__main__":
    unittest.main()
