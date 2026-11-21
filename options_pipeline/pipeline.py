"""Per-symbol response processing; no batching or network call is performed here."""
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

from .contract import apply_capture_metadata, parse_nasdaq_payload
from .freshness import classify_freshness
from .quality import assess_quality
from .registry import normalize_symbol, endpoint_for_symbol
from .storage import write_snapshot, validate_collection_output
from . import SCHEMA_VERSION


def process_symbol_payload(symbol, raw_payload, http_status, captured_at_utc, output_dir, session_date_et=None,
                           evidence_kind="NASDAQ_RESPONSE_NOT_INDEPENDENTLY_VERIFIED",
                           raw_retention_permitted=False, error_report=None):
    """Normalize one supplied response into an independent append-only snapshot."""
    symbol = normalize_symbol(symbol)
    if http_status != 200:
        capture = datetime.fromisoformat(captured_at_utc.replace("Z", "+00:00"))
        if capture.tzinfo is None or capture.utcoffset() is None:
            raise ValueError("CAPTURE_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
        capture_et = capture.astimezone(ZoneInfo("America/New_York"))
        raw_bytes = raw_payload if isinstance(raw_payload, bytes) else raw_payload.encode("utf-8") if isinstance(raw_payload, str) else b""
        metadata = {
            "provider": "NASDAQ", "endpoint_identifier": endpoint_for_symbol(symbol),
            "requested_symbol": symbol, "http_status": http_status,
            "capture_timestamp_utc": capture.astimezone(ZoneInfo("UTC")).isoformat(),
            "capture_timestamp_et": capture_et.isoformat(),
            "us_trading_session_date": session_date_et,
            "normalization_schema_version": SCHEMA_VERSION,
            "parser_status": "FAILED", "freshness": classify_freshness(http_status, captured_at_utc, session_date_et, None),
            "data_quality_status": "BLOCKED", "evidence_kind": evidence_kind,
            "raw_payload_sha256": hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else None,
        }
        quality = {"overall_status": "BLOCKED", "reason": metadata["freshness"]["status"], "derived_metrics": {}}
        directory = write_snapshot(output_dir, metadata, [], quality, error_report=error_report or {"status": "HTTP_FAILURE", "http_status": http_status}, raw_payload=raw_bytes or None, raw_retention_permitted=raw_retention_permitted)
        return {"snapshot_path": str(directory), "record_count": 0, "quality_status": "BLOCKED",
                "freshness_status": "HTTP_FAILURE", "symbol": symbol, "failure_classification": "HTTP_403_BLOCKED" if http_status == 403 else "HTTP_OTHER_FAILURE"}
    parsed = parse_nasdaq_payload(raw_payload, symbol)
    metadata = apply_capture_metadata(parsed, http_status, captured_at_utc, session_date_et)
    metadata["endpoint_identifier"] = endpoint_for_symbol(symbol)
    metadata["evidence_kind"] = evidence_kind
    quality = assess_quality(metadata, parsed["records"])
    metadata["data_quality_status"] = quality["overall_status"]
    directory = write_snapshot(output_dir, metadata, parsed["records"], quality,
                               error_report=error_report, raw_payload=raw_payload,
                               raw_retention_permitted=raw_retention_permitted)
    validated = validate_collection_output(directory, require_production_evidence=False)
    return {"snapshot_path": str(directory), "record_count": validated["record_count"],
            "quality_status": validated["quality_status"], "freshness_status": metadata["freshness"]["status"],
            "symbol": symbol, "endpoint_identifier": metadata["endpoint_identifier"]}
