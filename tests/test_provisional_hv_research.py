"""TEST_ONLY fixtures for the isolated provisional HV research adapter."""

from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import statistics
import tempfile
import unittest

from options_collector.historical_volatility import OHLCObservation
from options_collector.provisional_hv_research import (
    ProvisionalResearchBlocked,
    ResearchEvidence,
    audit_candidate_bundle_bytes,
    calculate_provisional_hv,
    write_local_research_json,
)


TEST_ONLY_SOURCE_SHA = "a" * 64
TEST_ONLY_PAYLOAD_SHA = "b" * 64


def _test_sessions(count: int) -> list[str]:
    sessions = []
    current = date(2026, 1, 5)
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(current.isoformat())
        current += timedelta(days=1)
    return sessions


def _test_bars(count: int) -> list[OHLCObservation]:
    sessions = _test_sessions(count)
    closes = [100.0]
    for index in range(1, count):
        closes.append(closes[-1] * math.exp(((index % 7) - 3) * 0.002))
    return [
        OHLCObservation(session_date=day, open=close * 0.995, high=close * 1.02,
                        low=close * 0.98, close=close)
        for day, close in zip(sessions, closes)
    ]


def _test_evidence(rows, **overrides) -> ResearchEvidence:
    values = dict(
        symbol="NVDA", source_status="UPSTREAM_SOURCE_UNVERIFIED",
        source_sha256=TEST_ONLY_SOURCE_SHA, payload_sha256=TEST_ONLY_PAYLOAD_SHA,
        actual_bytes_recovered=True, observation_count=len(rows),
        first_session=rows[0].session_date, last_session=rows[-1].session_date,
        local_research_permission="VERIFIED_ALLOWED", permission_evidence_ref="TEST_ONLY:fixture-policy",
        adjustment_status="UNKNOWN", corporate_action_status="NO_AFFECTING_ACTION_VERIFIED",
        observation_class="TEST_ONLY", redistribution_status="NOT_VERIFIED", publication_eligible=False,
    )
    values.update(overrides)
    return ResearchEvidence(**values)


class ProvisionalHVResearchTests(unittest.TestCase):
    def test_embedded_candidate_hashes_are_checked_from_actual_bytes(self):
        rows = _test_bars(90)
        payload = [
            {"date": row.session_date, "open": row.open, "high": row.high,
             "low": row.low, "close": row.close, "volume": 1000}
            for row in rows
        ]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        payload_sha = hashlib.sha256(canonical).hexdigest()
        bundle = {"execution_bundle": {"producer_attendance": [
            {"output": {}} for _ in range(5)
        ] + [{"output": {"symbol": "NVDA", "raw_ohlcv_90d": payload,
                         "raw_ohlcv_90d_sha256": payload_sha}}]}}
        bundle_bytes = json.dumps(bundle, separators=(",", ":")).encode()
        bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
        audit = audit_candidate_bundle_bytes(
            bundle_bytes, expected_bundle_sha256=bundle_sha,
            expected_payload_sha256=payload_sha,
        )
        self.assertEqual(len(audit.rows), 90)
        self.assertEqual(audit.first_session, rows[0].session_date)
        self.assertEqual(audit.last_session, rows[-1].session_date)
        with self.assertRaisesRegex(ProvisionalResearchBlocked, "BUNDLE_SHA256_MISMATCH"):
            audit_candidate_bundle_bytes(
                bundle_bytes, expected_bundle_sha256="0" * 64,
                expected_payload_sha256=payload_sha,
            )
        with self.assertRaisesRegex(ProvisionalResearchBlocked, "PAYLOAD_SHA256_MISMATCH"):
            audit_candidate_bundle_bytes(
                bundle_bytes, expected_bundle_sha256=bundle_sha,
                expected_payload_sha256="0" * 64,
            )

    def test_unverified_local_rights_blocks_candidate_calculation(self):
        rows = _test_bars(61)
        evidence = _test_evidence(rows, local_research_permission="UNVERIFIED", permission_evidence_ref=None)
        with self.assertRaisesRegex(ProvisionalResearchBlocked, "LOCAL_RESEARCH_PERMISSION_UNVERIFIED"):
            calculate_provisional_hv(rows, expected_sessions=[r.session_date for r in rows], evidence=evidence)

    def test_missing_original_bytes_and_digest_are_rejected(self):
        rows = _test_bars(11)
        evidence = _test_evidence(rows, actual_bytes_recovered=False)
        with self.assertRaisesRegex(ProvisionalResearchBlocked, "ORIGINAL_BYTES_UNAVAILABLE"):
            calculate_provisional_hv(rows, expected_sessions=[r.session_date for r in rows], evidence=evidence)
        evidence = _test_evidence(rows, payload_sha256="bad")
        with self.assertRaisesRegex(ProvisionalResearchBlocked, "INVALID_PAYLOAD_SHA256"):
            calculate_provisional_hv(rows, expected_sessions=[r.session_date for r in rows], evidence=evidence)

    def test_wrong_symbol_and_unresolved_corporate_actions_block(self):
        rows = _test_bars(11)
        with self.assertRaisesRegex(ProvisionalResearchBlocked, "WRONG_SYMBOL"):
            calculate_provisional_hv(rows, expected_sessions=[r.session_date for r in rows], evidence=_test_evidence(rows, symbol="NVDX"))
        with self.assertRaisesRegex(ProvisionalResearchBlocked, "CORPORATE_ACTION_STATUS_UNVERIFIED"):
            calculate_provisional_hv(rows, expected_sessions=[r.session_date for r in rows], evidence=_test_evidence(rows, corporate_action_status="UNKNOWN"))

    def test_duplicate_missing_or_unsorted_sessions_are_rejected(self):
        rows = _test_bars(11)
        sessions = [r.session_date for r in rows]
        with self.assertRaisesRegex(ProvisionalResearchBlocked, "MISSING_DUPLICATE_OR_UNSORTED_SESSION"):
            calculate_provisional_hv(rows, expected_sessions=sessions[:-1] + [sessions[-2]], evidence=_test_evidence(rows))
        reordered = rows[:]
        reordered[-1], reordered[-2] = reordered[-2], reordered[-1]
        with self.assertRaisesRegex(ProvisionalResearchBlocked, "MISSING_DUPLICATE_OR_UNSORTED_SESSION"):
            calculate_provisional_hv(reordered, expected_sessions=sessions, evidence=_test_evidence(rows))

    def test_invalid_nonfinite_or_nonpositive_ohlc_is_rejected(self):
        rows = _test_bars(11)
        rows[4] = OHLCObservation(rows[4].session_date, rows[4].open, float("nan"), rows[4].low, rows[4].close)
        with self.assertRaisesRegex(ProvisionalResearchBlocked, "NONFINITE_OR_NONNUMERIC_OHLC"):
            calculate_provisional_hv(rows, expected_sessions=[r.session_date for r in rows], evidence=_test_evidence(rows))
        rows = _test_bars(11)
        rows[4] = OHLCObservation(rows[4].session_date, rows[4].open, rows[4].high, rows[4].low, 0)
        with self.assertRaisesRegex(ProvisionalResearchBlocked, "NONPOSITIVE_OHLC"):
            calculate_provisional_hv(rows, expected_sessions=[r.session_date for r in rows], evidence=_test_evidence(rows))

    def test_all_horizons_use_exact_n_returns_sample_sd_and_annualize_once(self):
        rows = _test_bars(90)
        evidence = _test_evidence(rows)
        report = calculate_provisional_hv(rows, expected_sessions=[r.session_date for r in rows], evidence=evidence)
        self.assertEqual([v.name for v in report.values], ["HV10", "HV20", "HV30", "HV60"])
        for value in report.values:
            window = value.window_returns
            closes = [r.close for r in rows[-(window + 1):]]
            returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
            expected = statistics.stdev(returns) * math.sqrt(252) * 100
            self.assertAlmostEqual(value.annualized_percent, expected, places=12)
            self.assertEqual(value.valid_closes, window + 1)
            self.assertEqual(value.valid_returns, window)

    def test_insufficient_history_omits_unavailable_windows(self):
        rows = _test_bars(21)
        report = calculate_provisional_hv(rows, expected_sessions=[r.session_date for r in rows], evidence=_test_evidence(rows))
        self.assertEqual([v.name for v in report.values], ["HV10", "HV20"])

    def test_output_is_provisional_historical_and_never_iv_or_production(self):
        rows = _test_bars(61)
        report = calculate_provisional_hv(rows, expected_sessions=[r.session_date for r in rows], evidence=_test_evidence(rows))
        payload = report.to_dict()
        self.assertEqual(payload["research_lane"], "PROVISIONAL")
        self.assertEqual(payload["as_of_session"], rows[-1].session_date)
        self.assertFalse(payload["production_eligible"])
        self.assertFalse(payload["publication_eligible"])
        self.assertIsNone(payload["implied_volatility"])
        self.assertIn("NOT_CURRENT", payload["labels"])
        self.assertIn("NOT_IMPLIED_VOLATILITY", payload["labels"])
        self.assertIn("UPSTREAM_SOURCE_UNVERIFIED", payload["warnings"])
        self.assertIn("PRICE_ADJUSTMENT_UNVERIFIED", payload["warnings"])
        self.assertIn("TEST_ONLY_FIXTURE", payload["warnings"])

    def test_research_output_writer_refuses_repository_paths(self):
        rows = _test_bars(11)
        report = calculate_provisional_hv(rows, expected_sessions=[r.session_date for r in rows], evidence=_test_evidence(rows))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ProvisionalResearchBlocked, "RESEARCH_OUTPUT_MUST_REMAIN_OUTSIDE_REPOSITORY"):
                write_local_research_json(report, root / "candidate-hv.json", repository_root=root)
            path = write_local_research_json(report, root.parent / (root.name + "-local") / "candidate-hv.json", repository_root=root)
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
