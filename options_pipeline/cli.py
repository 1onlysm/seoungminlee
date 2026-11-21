"""Offline fixture runner; live mode always stops at the explicit pilot gate."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .client import LivePilotBlocked, NasdaqClient
from .contract import PayloadError, apply_capture_metadata, parse_nasdaq_payload
from .quality import assess_quality
from .storage import write_snapshot
from .workflow_gate import validate_required_output


def run_offline(fixture_path, output_dir):
    envelope = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    if envelope.get("fixture_type") != "SYNTHETIC_TEST_FIXTURE_NOT_LIVE_NASDAQ_DATA":
        raise ValueError("OFFLINE_INPUT_MUST_BE_EXPLICITLY_LABELED_FIXTURE")
    payload_text = json.dumps(envelope["payload"], ensure_ascii=False, separators=(",", ":"))
    parsed = parse_nasdaq_payload(payload_text, "SPY")
    metadata = apply_capture_metadata(parsed, envelope["http_status"], envelope["capture_timestamp_utc"], envelope.get("session_date_et"))
    metadata["evidence_kind"] = "SYNTHETIC_OFFLINE_FIXTURE"
    quality = assess_quality(metadata, parsed["records"])
    metadata["data_quality_status"] = quality["overall_status"]
    target = write_snapshot(output_dir, metadata, parsed["records"], quality, raw_payload=payload_text.encode("utf-8"), raw_retention_permitted=False)
    result = validate_required_output(target, require_live=False)
    print(json.dumps({"status": "OFFLINE_FIXTURE_VALIDATED", "evidence_kind": "SYNTHETIC_OFFLINE_FIXTURE", "snapshot": str(target), "record_count": result["record_count"], "freshness": metadata["freshness"]["status"], "quality": result["quality_status"]}, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="NAVI OPTIONS LAB offline-first Nasdaq SPY pipeline")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--fixture", help="Explicit synthetic offline fixture JSON")
    parser.add_argument("--output", default=".work10b-output")
    parser.add_argument("--confirm-single-request", default=None)
    args = parser.parse_args(argv)
    if args.mode == "live":
        print(json.dumps({"status": "PILOT_BLOCKED", "reason": "WORK10B_LIVE_REQUESTS_DISABLED; separate pilot authorization and implementation required", "live_requests": 0}), file=sys.stderr)
        return 2
    if not args.fixture:
        parser.error("--fixture is required in offline mode")
    try:
        return run_offline(args.fixture, args.output)
    except (ValueError, OSError, KeyError, PayloadError) as exc:
        print(json.dumps({"status": "OFFLINE_VALIDATION_FAILED", "error": f"{type(exc).__name__}:{exc}"}), file=sys.stderr)
        return 1

