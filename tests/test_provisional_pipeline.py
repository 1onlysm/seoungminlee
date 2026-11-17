import csv
import json
import tempfile
import unittest
from pathlib import Path

from options_collector.provisional_analytics import analyze_contracts, write_outputs
from options_collector.provisional_pipeline import run_pipeline


class ProvisionalPipelineTests(unittest.TestCase):
    def _snapshot(self, root, symbol, rows, timestamp):
        folder = root / "data" / "options" / "2026-11-16" / symbol / "v1"
        folder.mkdir(parents=True)
        with (folder / "contracts.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["symbol", "c_volume", "p_volume", "c_openinterest", "p_openinterest"])
            writer.writeheader()
            for row in rows:
                writer.writerow({"symbol": symbol, **row})
        (folder / "manifest.json").write_text(json.dumps({"symbol": symbol, "collected_at_utc": timestamp, "version": "v1"}))
        return folder

    def test_reads_snapshot_and_writes_provenance_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "snapshots"
            self._snapshot(root, "SPY", [{"c_volume": "10", "p_volume": "15", "c_openinterest": "3", "p_openinterest": "7"}], "2026-11-17T03:00:00Z")
            output = Path(temp) / "output"
            result = run_pipeline(root, output, symbols=["SPY"])
            payload = json.loads(Path(result["json_path"]).read_text())
            with Path(result["csv_path"]).open(newline="") as handle:
                row = next(csv.DictReader(handle))
        self.assertEqual(result["symbols_processed"], 1)
        self.assertEqual(payload["symbols"][0]["observed_volume_pcr"], 1.5)
        self.assertEqual(payload["symbols"][0]["snapshot_timestamp"], "2026-11-17T03:00:00Z")
        self.assertIn("snapshot_path", payload["symbols"][0])
        self.assertEqual(row["call_volume"], "10")
        self.assertEqual(row["status"], "PROVISIONAL")
        self.assertIn("snapshot_path", row)

    def test_existing_analytics_comparison_matches(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "snapshots"
            rows = [{"c_volume": "10", "p_volume": "15", "c_openinterest": "3", "p_openinterest": "7"}]
            self._snapshot(root, "SPY", rows, "2026-11-17T03:00:00Z")
            expected_dir = Path(temp) / "expected"
            expected = analyze_contracts("SPY", rows, "2026-11-17T03:00:00Z")
            expected_dir.mkdir()
            write_outputs([expected], expected_dir)
            result = run_pipeline(root, Path(temp) / "output", expected_analytics=expected_dir / "provisional_analytics.json", symbols=["SPY"])
        self.assertEqual(result["comparison"]["matched_symbols"], 1)
        self.assertEqual(result["comparison"]["mismatched_symbols"], [])

    def test_missing_snapshot_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "snapshots"
            root.mkdir()
            with self.assertRaisesRegex(FileNotFoundError, "SNAPSHOT_UNAVAILABLE:SPY"):
                run_pipeline(root, Path(temp) / "output", symbols=["SPY"])

    def test_output_cannot_overwrite_existing_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "snapshots"
            self._snapshot(root, "SPY", [{"c_volume": "1", "p_volume": "1"}], "2026-11-17T03:00:00Z")
            output = Path(temp) / "output"
            output.mkdir()
            (output / "provisional_analytics.csv").write_text("prior")
            with self.assertRaisesRegex(FileExistsError, "PIPELINE_OUTPUT_ALREADY_EXISTS"):
                run_pipeline(root, output, symbols=["SPY"])
            self.assertEqual((output / "provisional_analytics.csv").read_text(), "prior")

    def test_pipeline_remains_offline_and_provisional(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "snapshots"
            self._snapshot(root, "MSTR", [{"c_volume": "--", "p_volume": "0"}], "2026-11-17T03:00:00Z")
            result = run_pipeline(root, Path(temp) / "output", symbols=["MSTR"])
            row = result["results"][0]
        self.assertEqual(row["status"], "PROVISIONAL")
        self.assertEqual(row["call_volume_missing_count"], 1)
        self.assertEqual(row["put_volume_observed_count"], 1)
        self.assertEqual(row["put_volume_observed_sum"], 0)
        self.assertIsNone(row["observed_volume_pcr"])
        self.assertIn("EOD_UNVERIFIED", row["limitations"])


if __name__ == "__main__":
    unittest.main()
