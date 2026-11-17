import csv
import json
import tempfile
import unittest
from pathlib import Path

from options_collector.nvda_strike_map import aggregate_strikes, write_outputs

REAL_SNAPSHOT = Path("/workspace/scratch/navi-options-work04r-live/naviopt04r-20261117T051903Z-80a05c75/snapshots/data/options/2026-11-17/NVDA/2026-11-17T05-19-47.924836Z")


class NvdaStrikeMapTests(unittest.TestCase):
    def test_same_strike_across_expirations_is_aggregated(self):
        result = aggregate_strikes([
            {"symbol": "NVDA", "expiration": "2026-11-20", "strike": "100.00", "c_volume": "10", "p_volume": "2", "c_openinterest": "4", "p_openinterest": "8"},
            {"symbol": "NVDA", "expiration": "2026-12-18", "strike": "100", "c_volume": "3", "p_volume": "5", "c_openinterest": "6", "p_openinterest": "7"},
        ])
        row = result["rows"][0]
        self.assertEqual(result["totals"]["strike_count"], 1)
        self.assertEqual(row["expiration_count"], 2)
        self.assertEqual(row["call_volume_observed_sum"], 13)
        self.assertEqual(row["put_volume_observed_sum"], 7)
        self.assertEqual(row["call_oi_observed_sum"], 10)
        self.assertEqual(row["put_oi_observed_sum"], 15)

    def test_missing_values_and_explicit_zero_remain_distinct(self):
        result = aggregate_strikes([
            {"symbol": "NVDA", "strike": "100", "c_volume": "--", "p_volume": "0", "c_openinterest": None, "p_openinterest": ""},
            {"symbol": "NVDA", "strike": "100", "c_volume": "--", "p_volume": "--", "c_openinterest": "--", "p_openinterest": "--"},
        ])
        row = result["rows"][0]
        self.assertIsNone(row["call_volume_observed_sum"])
        self.assertEqual(row["call_volume_observed_count"], 0)
        self.assertEqual(row["call_volume_missing_count"], 2)
        self.assertEqual(row["put_volume_observed_sum"], 0)
        self.assertEqual(row["put_volume_observed_count"], 1)
        self.assertEqual(row["put_volume_missing_count"], 1)
        self.assertIsNone(row["call_oi_observed_sum"])

    def test_top5_order_and_share_use_observed_sum(self):
        contracts = []
        for strike, vol in [(90, 1), (95, 5), (100, 9), (105, 7), (110, 3), (115, 2)]:
            contracts.append({"symbol": "NVDA", "expiration": "2026-11-20", "strike": str(strike),
                              "c_volume": str(vol), "p_volume": str(vol * 2),
                              "c_openinterest": "0", "p_openinterest": "--"})
        result = aggregate_strikes(contracts)
        leaders = result["top5"]["call_volume"]
        self.assertEqual([row["strike"] for row in leaders], [100, 105, 95, 110, 115])
        self.assertAlmostEqual(leaders[0]["share_pct"], 9 / 27 * 100)

    def test_work04r_real_csv_totals_match_reference(self):
        if not REAL_SNAPSHOT.exists():
            self.skipTest("WORK 04-R NVDA snapshot unavailable outside the evidence workspace")
        with (REAL_SNAPSHOT / "contracts.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        result = aggregate_strikes(rows)
        self.assertEqual(result["totals"]["contracts"], 2188)
        self.assertEqual(result["totals"]["strike_count"], 444)
        self.assertEqual(result["totals"]["call_volume_observed_sum"], 1457430)
        self.assertEqual(result["totals"]["put_volume_observed_sum"], 953110)
        self.assertEqual(result["totals"]["call_oi_observed_sum"], 9839124)
        self.assertEqual(result["totals"]["put_oi_observed_sum"], 8636754)

    def test_output_files_csv_json_and_png_are_written(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "contracts.csv"
            manifest = root / "manifest.json"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["symbol", "expiration", "strike", "c_volume", "p_volume", "c_openinterest", "p_openinterest"])
                writer.writeheader()
                writer.writerow({"symbol": "NVDA", "expiration": "2026-11-20", "strike": "100", "c_volume": "1", "p_volume": "--", "c_openinterest": "0", "p_openinterest": "2"})
            manifest.write_text(json.dumps({"symbol": "NVDA", "collected_at_utc": "2026-11-17T05:19:47Z", "collected_at_et": "2026-11-17T00:19:47-05:00", "trading_date_et": "2026-11-17"}), encoding="utf-8")
            out = root / "out"
            result = write_outputs(source, manifest, out)
            summary = json.loads((out / "nvda_strike_summary.json").read_text())
            with (out / "nvda_strike_volume.csv").open(encoding="utf-8", newline="") as handle:
                volume = list(csv.DictReader(handle))
            with (out / "nvda_strike_oi.csv").open(encoding="utf-8", newline="") as handle:
                oi = list(csv.DictReader(handle))
            self.assertIsNone(json.loads((out / "nvda_strike_summary.json").read_text())["rows"][0]["put_volume_observed_sum"])
            self.assertEqual(len(volume), 1)
            self.assertEqual(len(oi), 1)
            self.assertEqual(summary["status"], "PROVISIONAL")
            self.assertGreaterEqual(summary["chart_display"]["volume"]["displayed_observed_total_share_pct"], 99.0)
            self.assertGreaterEqual(summary["chart_display"]["open_interest"]["displayed_observed_total_share_pct"], 99.0)
            self.assertEqual(len(result["files"]), 5)
            for name in ("nvda_volume_map.png", "nvda_oi_map.png"):
                self.assertTrue((out / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
