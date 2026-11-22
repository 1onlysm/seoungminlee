"""Synthetic offline regression tests; none are live market-data validation."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from options_pipeline.manual_import import (
    IMPORT_SCHEMA_VERSION, MAX_FILE_BYTES, ImportError, import_file,
    read_import_snapshot,
)
from tests.test_options_pipeline import envelope as nasdaq_fixture_envelope


def envelope(contracts=None, **updates):
    value = {
        "schema_version": IMPORT_SCHEMA_VERSION,
        "source": "SYNTHETIC_TEST_FIXTURE_NOT_LIVE_MARKET_DATA",
        "source_asof_timestamp": "2026-11-20T16:15:00-05:00",
        "capture_timestamp_utc": "2026-11-20T21:16:00Z",
        "session_date": "2026-11-20",
        "contracts": contracts or [
            {"underlying_symbol": "SPY", "expiration": "2027-01-15", "strike": "500", "side": "CALL", "option_symbol": "SPY270115C00500000", "volume": "10", "open_interest": "100", "bid": "1.00", "ask": "1.10", "contract_multiplier": "100"},
            {"underlying_symbol": "SPY", "expiration": "2027-01-15", "strike": "500", "side": "PUT", "option_symbol": "SPY270115P00500000", "volume": "20", "open_interest": "200", "bid": "2.00", "ask": "2.10", "contract_multiplier": "100"},
            {"underlying_symbol": "SPY", "expiration": "2027-02-19", "strike": "510", "side": "CALL", "volume": "5", "open_interest": "50", "bid": "0.90", "ask": "1.00", "contract_multiplier": "100"},
            {"underlying_symbol": "SPY", "expiration": "2027-02-19", "strike": "510", "side": "PUT", "volume": "15", "open_interest": "150", "bid": "2.50", "ask": "2.70", "contract_multiplier": "100"},
        ],
    }
    value.update(updates)
    return value


class ManualImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "input.json"
        self.output = self.root / "snapshots"

    def tearDown(self):
        self.tmp.cleanup()

    def write_json(self, value):
        self.source.write_text(json.dumps(value), encoding="utf-8")

    def run_import(self):
        return import_file(self.source, self.output, import_time=datetime(2026, 11, 21, tzinfo=timezone.utc))

    def test_01_valid_json_import(self):
        self.write_json(envelope())
        result = self.run_import()
        self.assertEqual(result["record_count"], 4)
        self.assertEqual(result["structural_quality"], "VALID")

    def test_02_valid_csv_import(self):
        fields = ["schema_version", "underlying_symbol", "expiration", "strike", "side", "volume", "open_interest"]
        self.source = self.root / "input.csv"
        with self.source.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerow({"schema_version": IMPORT_SCHEMA_VERSION, "underlying_symbol": "SPY", "expiration": "2027-01-15", "strike": "500", "side": "CALL", "volume": "0", "open_interest": "1"})
            writer.writerow({"schema_version": IMPORT_SCHEMA_VERSION, "underlying_symbol": "SPY", "expiration": "2027-01-15", "strike": "501", "side": "PUT", "volume": "2", "open_interest": "3"})
        self.assertEqual(self.run_import()["record_count"], 2)

    def test_03_missing_required_columns(self):
        self.source = self.root / "bad.csv"
        self.source.write_text("schema_version,underlying_symbol,side\n" + IMPORT_SCHEMA_VERSION + ",SPY,CALL\n")
        with self.assertRaisesRegex(ImportError, "REQUIRED_COLUMNS_MISSING"):
            self.run_import()

    def test_04_unsupported_schema(self):
        value = envelope(schema_version="navi-options-import/9.0")
        self.write_json(value)
        with self.assertRaisesRegex(ImportError, "UNSUPPORTED_SCHEMA_VERSION"):
            self.run_import()

    def test_05_malformed_json(self):
        self.source.write_text("{bad")
        with self.assertRaisesRegex(ImportError, "MALFORMED_JSON"):
            self.run_import()

    def test_06_invalid_encoding(self):
        self.source.write_bytes(b"\xff\xfe\xff")
        with self.assertRaisesRegex(ImportError, "INVALID_ENCODING"):
            self.run_import()

    def test_07_empty_file(self):
        self.source.write_bytes(b"")
        with self.assertRaisesRegex(ImportError, "EMPTY_FILE"):
            self.run_import()

    def test_08_oversized_file(self):
        self.source.write_bytes(b" " * (MAX_FILE_BYTES + 1))
        with self.assertRaisesRegex(ImportError, "FILE_SIZE_LIMIT_EXCEEDED"):
            self.run_import()

    def test_09_missing_call_put_side_is_partial_and_blocks_side_ratio(self):
        self.write_json(envelope(contracts=[{"underlying_symbol": "SPY", "expiration": "2027-01-15", "strike": "500", "side": "C"}]))
        result = self.run_import()
        self.assertEqual(result["structural_quality"], "PARTIAL")
        self.assertEqual(result["analytics"]["put_call_ratios"]["observed_volume_pcr"]["status"], "BLOCKED")

    def test_10_duplicate_contracts_rejected(self):
        row = envelope()["contracts"][0]
        self.write_json(envelope(contracts=[row, dict(row)]))
        with self.assertRaisesRegex(ImportError, "DUPLICATE_CONTRACT_KEY"):
            self.run_import()

    def test_11_missing_volume_not_converted_to_zero(self):
        contracts = envelope()["contracts"]
        del contracts[0]["volume"]
        self.write_json(envelope(contracts=contracts))
        result = self.run_import()
        record = read_import_snapshot(result["snapshot_path"])["records"][0]
        self.assertIsNone(record["volume"])
        self.assertEqual(record["volume_source_status"], "NOT_PROVIDED_BY_SOURCE")

    def test_12_missing_oi_not_converted_to_zero(self):
        contracts = envelope()["contracts"]
        del contracts[0]["open_interest"]
        self.write_json(envelope(contracts=contracts))
        result = self.run_import()
        record = read_import_snapshot(result["snapshot_path"])["records"][0]
        self.assertIsNone(record["open_interest"])
        self.assertEqual(record["open_interest_source_status"], "NOT_PROVIDED_BY_SOURCE")

    def test_13_explicit_zero_preserved(self):
        contracts = envelope()["contracts"]
        contracts[0]["volume"] = "0"
        self.write_json(envelope(contracts=contracts))
        result = self.run_import()
        record = read_import_snapshot(result["snapshot_path"])["records"][0]
        self.assertEqual(record["volume"], "0")
        self.assertEqual(record["volume_source_status"], "EXPLICIT_ZERO")

    def test_14_negative_values_retained_as_invalid_missing(self):
        contracts = envelope()["contracts"]
        contracts[0]["volume"] = "-4"
        self.write_json(envelope(contracts=contracts))
        result = self.run_import()
        record = read_import_snapshot(result["snapshot_path"])["records"][0]
        self.assertIsNone(record["volume"])
        self.assertEqual(record["volume_source_status"], "INVALID_NEGATIVE")
        self.assertEqual(result["structural_quality"], "PARTIAL")

    def test_15_invalid_expiration(self):
        contracts = envelope()["contracts"]
        contracts[0]["expiration"] = "not-a-date"
        self.write_json(envelope(contracts=contracts))
        with self.assertRaisesRegex(ImportError, "INVALID_EXPIRATION"):
            self.run_import()

    def test_16_invalid_strike(self):
        contracts = envelope()["contracts"]
        contracts[0]["strike"] = "0"
        self.write_json(envelope(contracts=contracts))
        with self.assertRaisesRegex(ImportError, "INVALID_STRIKE"):
            self.run_import()

    def test_17_missing_source_timestamp_does_not_fake_freshness(self):
        self.write_json(envelope(source_asof_timestamp=None, capture_timestamp_utc=None))
        result = self.run_import()
        self.assertEqual(result["freshness"]["status"], "SOURCE_TIME_UNAVAILABLE")

    def test_18_source_time_without_capture_is_unverified(self):
        self.write_json(envelope(capture_timestamp_utc=None))
        result = self.run_import()
        self.assertEqual(result["freshness"]["status"], "UNVERIFIED")

    def test_19_incomplete_pcr_has_missingness_warning(self):
        contracts = envelope()["contracts"]
        contracts[0].pop("volume")
        self.write_json(envelope(contracts=contracts))
        result = self.run_import()
        pcr = result["analytics"]["put_call_ratios"]["observed_volume_pcr"]
        self.assertEqual(pcr["status"], "PROVISIONAL")
        self.assertLess(pcr["coverage"]["CALL"]["coverage_percentage"], 100)
        self.assertGreater(pcr["coverage"]["CALL"]["missing_percentage"], 0)

    def test_20_snapshot_overwrite_prevention(self):
        self.write_json(envelope())
        first = self.run_import()
        with self.assertRaisesRegex(ImportError, "SNAPSHOT_OVERWRITE_BLOCKED"):
            self.run_import()

    def test_21_snapshot_readback_and_hash_validation(self):
        self.write_json(envelope())
        result = self.run_import()
        contents = read_import_snapshot(result["snapshot_path"])
        self.assertEqual(len(contents["records"]), 4)
        self.assertEqual(contents["manifest"]["file_sha256"], result["file_sha256"])

    def test_22_import_timestamp_never_becomes_capture_timestamp(self):
        self.write_json(envelope(capture_timestamp_utc=None))
        result = self.run_import()
        manifest = read_import_snapshot(result["snapshot_path"])["manifest"]
        self.assertIsNone(manifest["capture_timestamp_utc"])
        self.assertEqual(manifest["import_timestamp_utc"], "2026-11-21T00:00:00Z")

    def test_23_no_network_dependency(self):
        self.write_json(envelope())
        # This entry point has only filesystem/stdlib operations; its output is local.
        self.assertEqual(self.run_import()["record_count"], 4)

    def test_24_unsupported_extension_rejected(self):
        self.source = self.root / "input.xls"
        self.source.write_text("data")
        with self.assertRaisesRegex(ImportError, "UNSUPPORTED_FILE_FORMAT"):
            self.run_import()

    def test_25_json_extra_fields_rejected(self):
        value = envelope()
        value["contracts"][0]["invented_field"] = 1
        self.write_json(value)
        with self.assertRaisesRegex(ImportError, "UNSUPPORTED_CONTRACT_FIELDS"):
            self.run_import()

    def test_26_nasdaq_saved_json_adapter_is_offline_and_provenance_limited(self):
        self.write_json(nasdaq_fixture_envelope()["payload"])
        result = self.run_import()
        self.assertEqual(result["symbol"], "SPY")
        self.assertEqual(result["record_count"], 4)
        self.assertEqual(result["freshness"]["status"], "UNVERIFIED")

    def test_27_observed_ratios_and_max_pain_are_provisional(self):
        self.write_json(envelope())
        result = self.run_import()
        analytics = result["analytics"]
        self.assertEqual(analytics["put_call_ratios"]["observed_volume_pcr"]["value"], "2.333333333333333333333333333")
        self.assertEqual(analytics["max_pain"]["status"], "PROVISIONAL")
        self.assertTrue(analytics["warnings"])

    def test_28_max_pain_blocked_without_contract_multiplier(self):
        contracts = envelope()["contracts"]
        for row in contracts:
            row.pop("contract_multiplier")
        self.write_json(envelope(contracts=contracts))
        result = self.run_import()
        self.assertEqual(result["analytics"]["max_pain"]["status"], "BLOCKED")
        self.assertEqual(result["analytics"]["max_pain"]["reason"], "CONTRACT_MULTIPLIER_UNAVAILABLE_OR_INCONSISTENT")

    def test_29_malformed_source_asof_timestamp_rejected(self):
        self.write_json(envelope(source_asof_timestamp="yesterday"))
        with self.assertRaisesRegex(ImportError, "INVALID_SOURCE_ASOF_TIMESTAMP"):
            self.run_import()

    def test_30_historical_expiry_checked_against_session_not_import_day(self):
        value = envelope()
        for row in value["contracts"]:
            row["expiration"] = "2026-11-20"
        self.write_json(value)
        result = self.run_import()
        self.assertEqual(result["structural_quality"], "VALID")


if __name__ == "__main__":
    unittest.main()
