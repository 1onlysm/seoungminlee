import copy
import json
import tempfile
import unittest
import urllib.error
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from options_pipeline.client import LivePilotBlocked, NasdaqClient, PILOT_CONFIRMATION, pilot_preflight
from options_pipeline.contract import PayloadError, apply_capture_metadata, classify_source_value, parse_nasdaq_payload
from options_pipeline.freshness import classify_freshness
from options_pipeline.market_calendar import is_trading_day, session_close
from options_pipeline.registry import SYMBOL_ASSET_CLASSES, endpoint_for_symbol
from options_pipeline.pipeline import process_symbol_payload
from options_pipeline.quality import assess_quality
from options_pipeline.storage import StorageError, validate_collection_output, write_snapshot
from options_pipeline.workflow_gate import validate_required_output


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nasdaq_spy_valid_synthetic.json"


def envelope():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def parsed_and_metadata(data=None, http_status=200, asof=None):
    data = data or envelope()
    payload = copy.deepcopy(data["payload"])
    if asof is not None:
        payload["data"]["table"]["asOf"] = asof
    parsed = parse_nasdaq_payload(payload, "SPY")
    metadata = apply_capture_metadata(parsed, http_status, data["capture_timestamp_utc"], data["session_date_et"])
    metadata["evidence_kind"] = "SYNTHETIC_OFFLINE_FIXTURE"
    return parsed, metadata


class StubOpener:
    def __init__(self, error):
        self.error = error
        self.calls = 0
        self.request = None

    def open(self, request, timeout):
        self.calls += 1
        self.request = request
        raise self.error


class OptionsPipelineTests(unittest.TestCase):
    def test_01_valid_structural_response_normalizes_two_sides(self):
        parsed, metadata = parsed_and_metadata()
        self.assertEqual(parsed["parser_status"], "VALID")
        self.assertEqual([r["side"] for r in parsed["records"]], ["CALL", "PUT", "CALL", "PUT"])
        self.assertEqual(metadata["freshness"]["status"], "CURRENT_VERIFIED")

    def test_02_missing_bid_ask_remain_unavailable(self):
        data = envelope()
        row = data["payload"]["data"]["table"]["rows"][1]
        for key in ("c_Bid", "c_Ask", "p_Bid", "p_Ask"):
            row.pop(key)
        parsed = parse_nasdaq_payload(data["payload"])
        call = parsed["records"][0]
        self.assertIsNone(call["bid"])
        self.assertEqual(call["bid_source_status"], "NOT_PROVIDED_BY_SOURCE")

    def test_03_http_403_is_failure_not_empty_chain(self):
        result = classify_freshness(403, "2026-11-20T21:20:00Z", "2026-11-20", "2026-11-20T16:15:00-05:00")
        self.assertEqual(result["status"], "HTTP_FAILURE")

    def test_04_http_429_is_failure_not_empty_chain(self):
        self.assertEqual(classify_freshness(429, "2026-11-20T21:20:00Z", "2026-11-20", None)["status"], "HTTP_FAILURE")

    def test_05_http_500_is_failure_not_empty_chain(self):
        self.assertEqual(classify_freshness(500, "2026-11-20T21:20:00Z", "2026-11-20", None)["status"], "HTTP_FAILURE")

    def test_06_timeout_is_captured_without_network_or_retry(self):
        opener = StubOpener(TimeoutError("test timeout"))
        env = {"NAVI_OPTIONS_ACCESS_PATH_APPROVED": "YES", "NAVI_OPTIONS_RUNNER_APPROVED": "YES", "NAVI_OPTIONS_RETENTION_REVIEWED": "YES"}
        client = NasdaqClient(opener=opener)
        result = client.fetch_spy_once(PILOT_CONFIRMATION, env)
        self.assertIsNone(result.http_status)
        self.assertEqual(opener.calls, 1)
        self.assertEqual(result.request_count, 1)

    def test_07_empty_response_rows_are_rejected(self):
        payload = envelope()["payload"]
        payload["data"]["table"]["rows"] = []
        with self.assertRaisesRegex(PayloadError, "EMPTY_OR_MISSING_ROWS"):
            parse_nasdaq_payload(payload)

    def test_08_malformed_json_is_rejected(self):
        with self.assertRaisesRegex(PayloadError, "MALFORMED_JSON"):
            parse_nasdaq_payload(b"{broken")

    def test_09_missing_call_side_is_partial_and_blocks_metrics(self):
        data = envelope()
        row = data["payload"]["data"]["table"]["rows"][1]
        for key in tuple(row):
            if key.startswith("c_"):
                row.pop(key)
        parsed = parse_nasdaq_payload(data["payload"])
        metadata = apply_capture_metadata(parsed, 200, data["capture_timestamp_utc"], data["session_date_et"])
        quality = assess_quality(metadata, parsed["records"])
        self.assertIn("MISSING_CALL_SIDE:1", parsed["parser_issues"])
        self.assertEqual(quality["derived_metrics"]["PUT_CALL_VOLUME_RATIO"]["status"], "BLOCKED")

    def test_10_missing_put_side_is_partial_and_blocks_metrics(self):
        data = envelope()
        row = data["payload"]["data"]["table"]["rows"][1]
        for key in tuple(row):
            if key.startswith("p_"):
                row.pop(key)
        parsed = parse_nasdaq_payload(data["payload"])
        self.assertIn("MISSING_PUT_SIDE:1", parsed["parser_issues"])

    def test_11_missing_volume_is_not_zero(self):
        state, value, _ = classify_source_value({}, "c_Volume")
        self.assertEqual((state, value), ("NOT_PROVIDED_BY_SOURCE", None))

    def test_12_null_open_interest_is_distinct_from_missing(self):
        state, value, _ = classify_source_value({"p_Openinterest": None}, "p_Openinterest")
        self.assertEqual((state, value), ("NULL", None))

    def test_13_explicit_zero_volume_and_oi_are_counted_as_zero(self):
        state, value, _ = classify_source_value({"c_Volume": "0"}, "c_Volume")
        self.assertEqual((state, value), ("EXPLICIT_ZERO", "0"))

    def test_14_negative_volume_is_invalid_not_clamped(self):
        state, value, _ = classify_source_value({"c_Volume": "-1"}, "c_Volume")
        self.assertEqual((state, value), ("INVALID_NEGATIVE", None))

    def test_15_duplicate_contracts_are_detected(self):
        data = envelope()
        rows = data["payload"]["data"]["table"]["rows"]
        rows.insert(2, copy.deepcopy(rows[1]))
        data["payload"]["data"]["totalRecord"] = len(rows)
        parsed = parse_nasdaq_payload(data["payload"])
        self.assertTrue(any(issue.startswith("DUPLICATE_CONTRACT") for issue in parsed["parser_issues"]))

    def test_16_missing_expiration_is_reported(self):
        payload = envelope()["payload"]
        payload["data"]["table"]["rows"] = [{"strike": "500", "c_Option": "SPY 261120C00500000"}]
        payload["data"]["totalRecord"] = 1
        parsed = parse_nasdaq_payload(payload)
        self.assertIn("MISSING_OR_INVALID_EXPIRATION:0", parsed["parser_issues"])

    def test_17_invalid_strike_is_reported(self):
        payload = envelope()["payload"]
        payload["data"]["table"]["rows"][1]["strike"] = "-500"
        parsed = parse_nasdaq_payload(payload)
        self.assertTrue(any(issue.startswith("INVALID_STRIKE:") for issue in parsed["parser_issues"]))

    def test_18_missing_chain_timestamp_gets_explicit_status(self):
        _, metadata = parsed_and_metadata(asof=None)
        metadata["provider_asof_raw"] = None
        metadata["freshness"] = classify_freshness(200, "2026-11-20T21:20:00Z", "2026-11-20", None)
        self.assertEqual(metadata["freshness"]["status"], "SOURCE_TIME_UNAVAILABLE")

    def test_19_previous_session_chain_timestamp_is_stale_or_recent(self):
        result = classify_freshness(200, "2026-11-20T21:20:00Z", "2026-11-20", "2026-11-18T16:00:00-05:00")
        self.assertEqual(result["status"], "STALE")

    def test_20_adjusted_option_root_is_labeled_not_silently_merged(self):
        payload = envelope()["payload"]
        payload["data"]["table"]["rows"][1]["drillDownURL"] = "https://www.nasdaq.com/market/spy-b1spy--261120c00500000"
        parsed = parse_nasdaq_payload(payload)
        self.assertEqual(parsed["records"][0]["root"], "B1SPY")
        self.assertEqual(parsed["records"][0]["root_class"], "ADJUSTED")

    def test_34_quote_integrity_statistics_are_reported(self):
        parsed, metadata = parsed_and_metadata()
        quality = assess_quality(metadata, parsed["records"])
        call = quality["quote_integrity_by_side"]["CALL"]
        self.assertEqual(call["bid_ask"]["bid"]["missing_percentage"], 0.0)
        self.assertEqual(call["valid_spread_count"], 2)
        self.assertEqual(call["quote_timestamp_available_count"], 1)

    def test_35_live_403_is_explicitly_classified_without_retry(self):
        opener = StubOpener(urllib.error.HTTPError("https://api.nasdaq.com/test", 403, "Forbidden", {}, None))
        env = {"NAVI_OPTIONS_ACCESS_PATH_APPROVED": "YES", "NAVI_OPTIONS_RUNNER_APPROVED": "YES", "NAVI_OPTIONS_RETENTION_REVIEWED": "YES"}
        result = NasdaqClient(opener=opener).fetch_spy_once(PILOT_CONFIRMATION, env)
        self.assertEqual(result.classification, "HTTP_403_BLOCKED")
        self.assertEqual(opener.calls, 1)

    def test_36_registry_is_frozen_to_fourteen_symbols_and_endpoint_is_isolated(self):
        self.assertEqual(len(SYMBOL_ASSET_CLASSES), 14)
        self.assertIn("/quote/SPY/option-chain?assetclass=etf", endpoint_for_symbol("SPY"))
        self.assertIn("assetclass=stocks", endpoint_for_symbol("NVDA"))
        with self.assertRaisesRegex(ValueError, "UNREGISTERED_SYMBOL"):
            endpoint_for_symbol("FAKE")

    def test_37_http_failure_is_saved_as_independent_error_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            result = process_symbol_payload("SPY", b"Forbidden", 403, "2026-11-20T22:00:00Z", root,
                                            session_date_et="2026-11-20", error_report={"status": "HTTP_403_BLOCKED"})
            self.assertEqual(result["record_count"], 0)
            self.assertEqual(result["failure_classification"], "HTTP_403_BLOCKED")
            path = Path(result["snapshot_path"])
            self.assertEqual(json.loads((path / "error_report.json").read_text())["status"], "HTTP_403_BLOCKED")

    def test_38_chain_timestamp_does_not_stand_in_for_volume_or_oi_asof(self):
        parsed, metadata = parsed_and_metadata()
        quality = assess_quality(metadata, parsed["records"])
        self.assertEqual(metadata["freshness"]["status"], "CURRENT_VERIFIED")
        self.assertEqual(metadata["volume_freshness"]["status"], "SOURCE_TIME_UNAVAILABLE")
        self.assertEqual(metadata["open_interest_freshness"]["status"], "SOURCE_TIME_UNAVAILABLE")
        self.assertEqual(quality["derived_metrics"]["PUT_CALL_VOLUME_RATIO"]["reason"], "VOLUME_ASOF_SOURCE_TIME_UNAVAILABLE")
        self.assertEqual(quality["derived_metrics"]["PUT_CALL_OI_RATIO"]["reason"], "OPEN_INTEREST_ASOF_SOURCE_TIME_UNAVAILABLE")

    def test_21_missing_output_directory_fails(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(StorageError, "MISSING_ARTIFACT_OR_SNAPSHOT"):
                validate_required_output(Path(root) / "no-output")

    def test_22_missing_required_snapshot_file_fails(self):
        parsed, metadata = parsed_and_metadata()
        quality = assess_quality(metadata, parsed["records"])
        with tempfile.TemporaryDirectory() as root:
            path = write_snapshot(root, metadata, parsed["records"], quality)
            (path / "quality_report.json").unlink()
            with self.assertRaisesRegex(StorageError, "MISSING_REQUIRED_FILE"):
                validate_collection_output(path)

    def test_23_snapshot_overwrite_attempt_fails(self):
        parsed, metadata = parsed_and_metadata()
        quality = assess_quality(metadata, parsed["records"])
        with tempfile.TemporaryDirectory() as root:
            args = (root, metadata, parsed["records"], quality)
            write_snapshot(*args, capture_id="fixed-capture")
            with self.assertRaisesRegex(StorageError, "SNAPSHOT_OVERWRITE_BLOCKED"):
                write_snapshot(*args, capture_id="fixed-capture")

    def test_24_invalid_schema_version_fails_integrity_check(self):
        parsed, metadata = parsed_and_metadata()
        quality = assess_quality(metadata, parsed["records"])
        with tempfile.TemporaryDirectory() as root:
            path = write_snapshot(root, metadata, parsed["records"], quality)
            manifest = json.loads((path / "manifest.json").read_text())
            manifest["normalization_schema_version"] = "unknown"
            (path / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(StorageError, "INVALID_SCHEMA_VERSION"):
                validate_collection_output(path)

    def test_25_market_holiday_is_not_a_session(self):
        self.assertIs(is_trading_day(date(2026, 11, 26)), False)

    def test_26_dst_transition_uses_et_zone_rules(self):
        et = ZoneInfo("America/New_York")
        before = datetime(2026, 3, 8, 1, 30, tzinfo=et)
        after = datetime(2026, 3, 8, 3, 30, tzinfo=et)
        self.assertNotEqual(before.utcoffset(), after.utcoffset())

    def test_27_unknown_calendar_year_fails_closed(self):
        self.assertIsNone(is_trading_day(date(2027, 1, 4)))

    def test_28_metric_is_blocked_below_field_coverage_threshold(self):
        parsed, metadata = parsed_and_metadata()
        records = parsed["records"]
        records[0]["volume"] = None
        records[0]["volume_source_status"] = "NOT_PROVIDED_BY_SOURCE"
        quality = assess_quality(metadata, records)
        self.assertEqual(quality["derived_metrics"]["PUT_CALL_VOLUME_RATIO"]["status"], "BLOCKED")

    def test_29_http_200_without_output_is_not_collection_success(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(StorageError, "MISSING_ARTIFACT_OR_SNAPSHOT"):
                validate_required_output(Path(root) / "missing", require_live=True)

    def test_30_raw_payload_is_not_retained_without_permission(self):
        parsed, metadata = parsed_and_metadata()
        quality = assess_quality(metadata, parsed["records"])
        with tempfile.TemporaryDirectory() as root:
            path = write_snapshot(root, metadata, parsed["records"], quality, raw_payload=None, raw_retention_permitted=False)
            manifest = json.loads((path / "manifest.json").read_text())
            self.assertFalse(manifest["raw_payload_retained"])
            self.assertFalse((path / "raw_payload.json").exists())
            self.assertEqual(len(manifest["raw_payload_sha256"]), 64)

    def test_31_live_pilot_preflight_is_blocked_without_all_approvals(self):
        result = pilot_preflight(env={}, explicit_confirmation=None)
        self.assertFalse(result["ready"])
        self.assertEqual(result["request_budget"], 1)
        self.assertEqual(result["retry_count"], 0)

    def test_32_spy_client_refuses_request_before_preflight(self):
        opener = StubOpener(TimeoutError("should never be called"))
        client = NasdaqClient(opener=opener)
        with self.assertRaises(LivePilotBlocked):
            client.fetch_spy_once(env={}, explicit_confirmation=None)
        self.assertEqual(opener.calls, 0)

    def test_33_early_close_calendar_is_explicit(self):
        self.assertEqual(session_close(date(2026, 11, 27)).isoformat(), "13:00:00")


if __name__ == "__main__":
    unittest.main()
