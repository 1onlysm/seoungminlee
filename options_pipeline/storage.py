"""Append-only local snapshots with atomic writes and readback integrity checks."""
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from . import SCHEMA_VERSION


class StorageError(ValueError):
    pass


def _canonical_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _atomic_file(path, payload):
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _safe_component(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise StorageError(f"INVALID_{label.upper()}")
    return value


def _verify_snapshot(directory):
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("normalization_schema_version") != SCHEMA_VERSION:
        raise StorageError("INVALID_SCHEMA_VERSION")
    for filename, key in (("normalized_records.json", "normalized_records_sha256"), ("quality_report.json", "quality_report_sha256"), ("error_report.json", "error_report_sha256")):
        path = directory / filename
        if not path.is_file():
            raise StorageError(f"MISSING_REQUIRED_FILE:{filename}")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest.get(key):
            raise StorageError(f"HASH_MISMATCH:{filename}")
        json.loads(payload.decode("utf-8"))
    if manifest.get("raw_payload_retained"):
        raw = directory / "raw_payload.json"
        if not raw.is_file() or hashlib.sha256(raw.read_bytes()).hexdigest() != manifest.get("raw_payload_sha256"):
            raise StorageError("RAW_PAYLOAD_INTEGRITY_FAILURE")
    return manifest


def write_snapshot(base_dir, metadata, records, quality_report, error_report=None, raw_payload=None, raw_retention_permitted=False, capture_id=None):
    symbol = _safe_component(metadata.get("requested_symbol"), "symbol")
    session = metadata.get("us_trading_session_date") or "unknown-session"
    session = _safe_component(session, "session_date")
    captured = metadata.get("capture_timestamp_utc") or datetime.utcnow().isoformat(timespec="microseconds") + "Z"
    stamp = re.sub(r"[^0-9A-Za-z]+", "-", captured).strip("-")
    capture_id = _safe_component(capture_id or f"{stamp}-{uuid.uuid4().hex[:8]}", "capture_id")
    parent = Path(base_dir) / "data" / "options" / session / symbol
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / capture_id
    if target.exists():
        raise StorageError("SNAPSHOT_OVERWRITE_BLOCKED")

    raw_bytes = raw_payload if isinstance(raw_payload, bytes) else (raw_payload.encode("utf-8") if isinstance(raw_payload, str) else None)
    raw_hash = metadata.get("raw_payload_sha256")
    if raw_bytes is not None:
        computed = hashlib.sha256(raw_bytes).hexdigest()
        if raw_hash and raw_hash != computed:
            raise StorageError("RAW_PAYLOAD_HASH_MISMATCH")
        raw_hash = computed
    retain_raw = bool(raw_bytes is not None and raw_retention_permitted)
    records_bytes = _canonical_bytes(records)
    quality_bytes = _canonical_bytes(quality_report)
    errors = error_report if error_report is not None else {"status": "NO_ERROR_REPORTED", "errors": []}
    error_bytes = _canonical_bytes(errors)
    manifest = dict(metadata)
    manifest.update({
        "normalization_schema_version": SCHEMA_VERSION,
        "capture_id": capture_id,
        "snapshot_path_format": "date/symbol/capture-id",
        "raw_payload_sha256": raw_hash,
        "raw_payload_retained": retain_raw,
        "normalized_record_count": len(records),
        "normalized_records_sha256": hashlib.sha256(records_bytes).hexdigest(),
        "quality_report_sha256": hashlib.sha256(quality_bytes).hexdigest(),
        "error_report_sha256": hashlib.sha256(error_bytes).hexdigest(),
        "evidence_kind": metadata.get("evidence_kind", "NASDAQ_RESPONSE_NOT_INDEPENDENTLY_VERIFIED"),
    })
    temp = Path(tempfile.mkdtemp(prefix=".pending-", dir=str(parent)))
    try:
        _atomic_file(temp / "normalized_records.json", records_bytes)
        _atomic_file(temp / "quality_report.json", quality_bytes)
        _atomic_file(temp / "error_report.json", error_bytes)
        _atomic_file(temp / "manifest.json", _canonical_bytes(manifest))
        if retain_raw:
            _atomic_file(temp / "raw_payload.json", raw_bytes)
        _verify_snapshot(temp)
        os.replace(temp, target)
        _verify_snapshot(target)
    except Exception:
        raise
    return target


def validate_collection_output(snapshot_dir, require_production_evidence=False):
    directory = Path(snapshot_dir)
    if not directory.is_dir():
        raise StorageError("MISSING_OUTPUT_DIRECTORY")
    manifest = _verify_snapshot(directory)
    records = json.loads((directory / "normalized_records.json").read_text(encoding="utf-8"))
    quality = json.loads((directory / "quality_report.json").read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise StorageError("MISSING_OR_EMPTY_COLLECTION_OUTPUT")
    if manifest.get("parser_status") != "VALID":
        raise StorageError("PARSER_STATUS_NOT_VALID")
    if quality.get("overall_status") == "BLOCKED":
        raise StorageError("QUALITY_STATUS_BLOCKED")
    if require_production_evidence and manifest.get("evidence_kind") != "LIVE_NASDAQ_RESPONSE":
        raise StorageError("NON_LIVE_EVIDENCE_CANNOT_PASS_PRODUCTION_GATE")
    if require_production_evidence and (manifest.get("http_status") != 200 or (manifest.get("freshness") or {}).get("status") != "CURRENT_VERIFIED"):
        raise StorageError("HTTP_OR_FRESHNESS_GATE_FAILED")
    return {"manifest": manifest, "record_count": len(records), "quality_status": quality.get("overall_status")}

