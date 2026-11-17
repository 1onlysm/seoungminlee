"""One-shot Nasdaq batch collection followed by the existing provisional pipeline.

Live use is intentionally explicit and limited to the registered 14-symbol batch.
The client is the existing one-shot/no-redirect NasdaqClient; this module adds no
retry, alternate endpoint, or network path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .client import NasdaqClient
from .parser import parse_payload
from .provisional_pipeline import run_pipeline
from .quality import inspect_quality
from .registry import REGISTRY, get_symbol
from .snapshot import write_snapshot

SYMBOLS = tuple(REGISTRY)
ET = ZoneInfo("America/New_York")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_body(path: Path, body: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique_run_dir(root: Path, run_id: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / run_id
    run_dir.mkdir(exist_ok=False)
    return run_dir


def run_live_batch(output_root: str | Path, *, client_factory=NasdaqClient, symbols=SYMBOLS) -> dict:
    ordered = tuple(symbols)
    if ordered != SYMBOLS:
        raise ValueError("LIVE_BATCH_MUST_MATCH_REGISTERED_14_SYMBOL_ORDER")
    if len(ordered) > 14 or any(symbol not in REGISTRY for symbol in ordered):
        raise ValueError("LIVE_REQUEST_LIMIT_OR_REGISTRY_VIOLATION")

    run_started = _now_utc()
    run_id = f"naviopt04r-{run_started.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = _unique_run_dir(Path(output_root).expanduser().resolve(), run_id)
    manifest_path = run_dir / "execution_manifest.jsonl"
    snapshots_root = run_dir / "snapshots"
    response_dir = run_dir / "responses"
    results: list[dict] = []
    client = client_factory(timeout=30)
    request_count = 0

    for symbol in ordered:
        item = get_symbol(symbol)
        intent_time = _now_utc()
        _append_jsonl(manifest_path, {
            "run_id": run_id, "symbol": symbol, "assetclass": item.assetclass,
            "timestamp_utc": _stamp(intent_time), "request_status": "REQUEST_INTENT_RECORDED",
            "request_attempt_number": 1,
        })
        call_started = _now_utc()
        _append_jsonl(manifest_path, {
            "run_id": run_id, "symbol": symbol, "timestamp_utc": _stamp(call_started),
            "request_status": "CLIENT_CALL_STARTED",
            "meaning": "client invocation is starting; this does not prove server receipt",
        })
        request_count += 1
        try:
            result = client.fetch_once(symbol)
        except Exception as exc:  # one invocation only; preserve and continue
            call_finished = _now_utc()
            row = {
                "symbol": symbol, "assetclass": item.assetclass,
                "request_started_utc": _stamp(call_started), "request_finished_utc": _stamp(call_finished),
                "http_status": None, "api_rcode": None, "error_type": type(exc).__name__,
                "verdict": "NETWORK_ERROR", "analytics_status": "NOT_RUN",
                "contracts_count": None, "expiry_group_count": None,
            }
            results.append(row)
            _append_jsonl(manifest_path, {"run_id": run_id, **row, "request_status": "REQUEST_FAILED", "retry_count": 0})
            continue

        call_finished = _now_utc()
        body = result.body
        base_record = {
            "run_id": run_id, "symbol": symbol, "assetclass": item.assetclass,
            "request_started_utc": _stamp(call_started), "request_finished_utc": _stamp(call_finished),
            "http_status": result.http_status, "api_rcode": result.api_rcode,
            "response_bytes": len(body) if body is not None else None,
            "response_sha256": hashlib.sha256(body).hexdigest() if body is not None else None,
            "error_type": result.error_type, "error_detail": result.error_detail,
            "retry_count": 0, "redirect_count": 0,
        }
        if body is not None and result.http_status != 200:
            base_record["error_body_path"] = str(response_dir / f"{symbol}.response")
            try:
                _write_body(Path(base_record["error_body_path"]), body)
            except OSError as exc:
                base_record["storage_error"] = type(exc).__name__
        if result.http_status != 200:
            verdict = "HTTP_ACCESS_DENIED" if result.http_status == 403 else "HTTP_ERROR" if result.http_status is not None else "NETWORK_ERROR"
            if result.http_status is None and result.error_type:
                verdict = "NETWORK_ERROR"
            row = {**base_record, "verdict": verdict, "analytics_status": "NOT_RUN", "contracts_count": None, "expiry_group_count": None}
            results.append(row)
            _append_jsonl(manifest_path, {**row, "request_status": "HTTP_RESPONSE_RECEIVED" if body is not None else "REQUEST_FAILED"})
            continue
        if result.api_rcode != 200 or body is None:
            row = {**base_record, "verdict": "API_ERROR", "analytics_status": "NOT_RUN", "contracts_count": None, "expiry_group_count": None}
            results.append(row)
            _append_jsonl(manifest_path, {**row, "request_status": "HTTP_RESPONSE_RECEIVED"})
            continue

        try:
            parsed = parse_payload(body, item)
            if not parsed.schema_ok or not parsed.rows:
                raise ValueError("SCHEMA_MISMATCH:" + ",".join(parsed.issues))
            quality = inspect_quality(parsed, body, result.http_status, result.api_rcode, _stamp(call_finished))
            et_date = call_finished.astimezone(ET).date().isoformat()
            snapshot = write_snapshot(snapshots_root, symbol, et_date, body, parsed.rows, quality, _stamp(call_finished))
            raw_path = snapshot / "raw.json"
            saved_raw = raw_path.read_bytes()
            digest = hashlib.sha256(saved_raw).hexdigest()
            if saved_raw != body or digest != base_record["response_sha256"]:
                raise IOError("RAW_SNAPSHOT_READBACK_MISMATCH")
            row = {
                **base_record, "verdict": "LIVE_COLLECTION_SUCCESS", "analytics_status": "PENDING",
                "snapshot_path": str(snapshot), "raw_path": str(raw_path),
                "contracts_csv_path": str(snapshot / "contracts.csv"),
                "quality_path": str(snapshot / "quality.json"), "snapshot_manifest_path": str(snapshot / "manifest.json"),
                "totalRecord": parsed.total_record, "raw_row_count": parsed.raw_row_count,
                "contracts_count": len(parsed.rows), "expiry_group_count": parsed.expiry_groups,
                "call_volume_observed_sum": None, "put_volume_observed_sum": None,
                "call_oi_observed_sum": None, "put_oi_observed_sum": None,
                "observed_volume_pcr": None, "freshness": "EOD_UNVERIFIED",
            }
            results.append(row)
            _append_jsonl(manifest_path, {**row, "request_status": "RESULT_PERSISTED"})
        except Exception as exc:
            row = {**base_record, "verdict": "PARSER_ERROR" if isinstance(exc, ValueError) else "STORAGE_ERROR",
                   "error_type": type(exc).__name__, "error_detail": str(exc), "analytics_status": "NOT_RUN",
                   "contracts_count": None, "expiry_group_count": None}
            results.append(row)
            _append_jsonl(manifest_path, {**row, "request_status": "REQUEST_FAILED"})

    successful = [row["symbol"] for row in results if row["verdict"] == "LIVE_COLLECTION_SUCCESS"]
    pipeline_result = None
    pipeline_error = None
    if successful:
        try:
            pipeline_result = run_pipeline(snapshots_root, run_dir / "analytics", symbols=successful)
            by_symbol = {item["symbol"]: item for item in pipeline_result["results"]}
            for row in results:
                if row["symbol"] in by_symbol:
                    analytic = by_symbol[row["symbol"]]
                    row.update({
                        "analytics_status": "PROVISIONAL",
                        "contracts_count": analytic["contracts_count"],
                        "call_volume_observed_sum": analytic["call_volume_observed_sum"],
                        "put_volume_observed_sum": analytic["put_volume_observed_sum"],
                        "call_oi_observed_sum": analytic["call_oi_observed_sum"],
                        "put_oi_observed_sum": analytic["put_oi_observed_sum"],
                        "call_volume_coverage_pct": analytic["call_volume_coverage_pct"],
                        "put_volume_coverage_pct": analytic["put_volume_coverage_pct"],
                        "observed_volume_pcr": analytic["observed_volume_pcr"],
                        "limitations": analytic["limitations"],
                    })
                    _append_jsonl(manifest_path, {"run_id": run_id, "symbol": row["symbol"],
                        "timestamp_utc": _stamp(_now_utc()), "request_status": "ANALYTICS_PERSISTED",
                        "analytics_status": "PROVISIONAL", "contracts_count": analytic["contracts_count"]})
        except Exception as exc:
            pipeline_error = {"error_type": type(exc).__name__, "error_detail": str(exc)}
            for row in results:
                if row["verdict"] == "LIVE_COLLECTION_SUCCESS":
                    row["analytics_status"] = "ANALYTICS_ERROR"

    batch_finished = _now_utc()
    success_count = sum(row["verdict"] == "LIVE_COLLECTION_SUCCESS" for row in results)
    analytics_count = sum(row["analytics_status"] == "PROVISIONAL" for row in results)
    summary = {
        "run_id": run_id, "mode": "LIVE", "started_at_utc": _stamp(run_started),
        "finished_at_utc": _stamp(batch_finished), "symbols": list(ordered),
        "request_count": request_count, "maximum_requests": 14, "retry_count": 0,
        "redirect_count": 0, "success_count": success_count,
        "analytics_success_count": analytics_count,
        "failure_count": len(results) - success_count, "results": results,
        "analytics": ({"json_path": pipeline_result["json_path"], "csv_path": pipeline_result["csv_path"]} if pipeline_result else None),
        "analytics_error": pipeline_error, "manifest_path": str(manifest_path),
        "snapshot_root": str(snapshots_root), "freshness": "EOD_UNVERIFIED",
    }
    _write_json(run_dir / "batch_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="One authorized 14-symbol Nasdaq collection plus provisional analytics")
    parser.add_argument("--mode", choices=["live"], required=True)
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    if not args.confirm_live:
        parser.error("LIVE_MODE_REQUIRES_CONFIRM_LIVE")
    result = run_live_batch(args.output_root)
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
