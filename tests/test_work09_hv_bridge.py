import copy
import hashlib
import json
import unittest
from datetime import date
from pathlib import Path

from options_collector.hv_bridge import (
    ARTIFACT_TYPE, FORMULA_ID, HVImportError, EXPECTED_FIELDS,
    payload_sha256, research_panel_state, validate_hv_artifact,
)


TEST_ONLY_RIGHTS = {
    "verified": True, "provider": "TIINGO",
    "scope": "PERSONAL_CROSS_PROJECT_DERIVED_METRICS",
    "evidence_ref": "TEST_ONLY:fixture-policy",
}


def fixture():
    payload = {
        "schema_version": "1.0", "artifact_type": ARTIFACT_TYPE,
        "symbol": "NVDA", "provider": "TIINGO_EOD", "price_field": "adjClose",
        "adjustment_basis": "SPLIT_AND_DIVIDEND_ADJUSTED",
        "as_of_session": "2026-11-17", "observations": 125,
        "formula_id": FORMULA_ID,
        "hv": {"hv10": 12.5, "hv20": 13.5, "hv30": 14.5, "hv60": 15.5},
        "annualization_sessions": 252, "standard_deviation_ddof": 1,
        "status": "PROVISIONAL", "rights_status": "AUTHORIZED",
        "raw_ohlcv_included": False, "token_included": False,
        "integrity": {"algorithm": "SHA-256", "sha256": ""},
    }
    payload["integrity"]["sha256"] = payload_sha256(payload)
    return payload


class Work09HVBridgeTests(unittest.TestCase):
    def test_import_requires_external_rights_evidence_not_payload_checkbox(self):
        payload = fixture()
        with self.assertRaisesRegex(HVImportError, "RIGHTS_AUTHORIZATION_EVIDENCE_REQUIRED"):
            validate_hv_artifact(payload, today=date(2026, 11, 18))
        self.assertEqual(validate_hv_artifact(payload, rights_evidence=TEST_ONLY_RIGHTS,
                                              today=date(2026, 11, 18))["status"], "PROVISIONAL")

    def test_schema_and_integrity_are_strict(self):
        payload = fixture()
        self.assertEqual(set(payload), EXPECTED_FIELDS)
        self.assertEqual(validate_hv_artifact(json.dumps(payload), rights_evidence=TEST_ONLY_RIGHTS,
                                              today=date(2026, 11, 18))["hv"]["hv10"], 12.5)
        payload["hv"]["hv10"] = 999.0
        with self.assertRaisesRegex(HVImportError, "PAYLOAD_INTEGRITY_FAILED"):
            validate_hv_artifact(payload, rights_evidence=TEST_ONLY_RIGHTS, today=date(2026, 11, 18))

    def test_rejects_malformed_wrong_provider_symbol_and_version(self):
        with self.assertRaisesRegex(HVImportError, "MALFORMED_JSON"):
            validate_hv_artifact("{")
        for key, value, reason in [("schema_version", "2.0", "UNSUPPORTED_SCHEMA_VERSION"),
                                   ("symbol", "AMD", "ARTIFACT_OR_SYMBOL_MISMATCH"),
                                   ("provider", "OTHER", "PROVIDER_OR_PRICE_FIELD_MISMATCH")]:
            payload = fixture(); payload[key] = value
            payload["integrity"]["sha256"] = payload_sha256(payload)
            with self.assertRaisesRegex(HVImportError, reason):
                validate_hv_artifact(payload, rights_evidence=TEST_ONLY_RIGHTS, today=date(2026, 11, 18))

    def test_rejects_bad_metrics_raw_data_credentials_and_production_status(self):
        for mutation, reason in [
            (lambda p: p["hv"].__setitem__("hv10", "NaN"), "HV_VALUE_INVALID:hv10"),
            (lambda p: p.update({"raw_ohlcv": [{"date": "2026-11-17"}]}), "FORBIDDEN_RAW_OR_CREDENTIAL_FIELD"),
            (lambda p: p.update({"api_key": "TEST_ONLY"}), "FORBIDDEN_RAW_OR_CREDENTIAL_FIELD"),
            (lambda p: p.update({"status": "VERIFIED"}), "PRODUCTION_STATUS_NOT_ALLOWED"),
        ]:
            payload = fixture(); mutation(payload)
            payload["integrity"]["sha256"] = payload_sha256(payload)
            with self.assertRaisesRegex(HVImportError, reason):
                validate_hv_artifact(payload, rights_evidence=TEST_ONLY_RIGHTS, today=date(2026, 11, 18))

    def test_stale_and_mismatched_snapshot_dates_are_explicit(self):
        payload = fixture()
        stale = validate_hv_artifact(payload, rights_evidence=TEST_ONLY_RIGHTS, today=date(2026, 12, 1))
        self.assertEqual(stale["freshness"], "STALE")
        state = research_panel_state("2026-11-18", stale)
        self.assertTrue(state["timestamp_mismatch"])
        self.assertIn("다릅니다", state["warning"])
        same = research_panel_state("2026-11-17", validate_hv_artifact(
            payload, rights_evidence=TEST_ONLY_RIGHTS, today=date(2026, 11, 18)))
        self.assertFalse(same["timestamp_mismatch"])

    def test_unavailable_panel_does_not_substitute_fixture_or_options_values(self):
        state = research_panel_state("2026-11-18", None)
        self.assertFalse(state["available"])
        self.assertIsNone(state["hv_as_of_session"])
        self.assertNotIn("values", state)
        self.assertIn("권한 확인", state["warning"])

    def test_rights_metadata_in_payload_is_not_authority(self):
        payload = fixture()
        forged = {**TEST_ONLY_RIGHTS, "evidence_ref": ""}
        with self.assertRaisesRegex(HVImportError, "RIGHTS_AUTHORIZATION_EVIDENCE_REQUIRED"):
            validate_hv_artifact(payload, rights_evidence=forged, today=date(2026, 11, 18))

    def test_dashboard_has_separate_locked_hv_research_panel(self):
        source = Path(__file__).parents[1] / "options_collector" / "nvda_dashboard.py"
        html = source.read_text(encoding="utf-8")
        self.assertIn('id="hv-research-panel"', html)
        self.assertIn("Tiingo HV 가져오기", html)
        self.assertIn("권한 확인 대기", html)
        self.assertNotIn("60.70", html)


if __name__ == "__main__":
    unittest.main()
