"""Explicit user-invoked command for the existing live/provisional batch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .live_provisional import run_live_batch


def render_completion(summary: dict) -> dict:
    results = summary.get("results", [])
    successful = [row["symbol"] for row in results if row.get("verdict") == "LIVE_COLLECTION_SUCCESS"]
    failed = [
        {"symbol": row.get("symbol"), "verdict": row.get("verdict"), "analytics_status": row.get("analytics_status")}
        for row in results
        if row.get("verdict") != "LIVE_COLLECTION_SUCCESS" or row.get("analytics_status") != "PROVISIONAL"
    ]
    run_path = str(Path(summary["manifest_path"]).parent)
    complete = len(successful) == 14 and not failed and summary.get("analytics_success_count") == 14
    return {
        "run_id": summary.get("run_id"),
        "status": "COMPLETE" if complete else "PARTIAL_OR_FAILED",
        "target_symbol_count": len(summary.get("symbols", [])),
        "request_count": summary.get("request_count"),
        "retry_count": summary.get("retry_count"),
        "collection_success_count": summary.get("success_count"),
        "analytics_success_count": summary.get("analytics_success_count"),
        "successful_symbols": successful,
        "failed_symbols": failed,
        "run_path": run_path,
        "raw_snapshot_path": summary.get("snapshot_root"),
        "manifest_path": summary.get("manifest_path"),
        "analytics_json_path": (summary.get("analytics") or {}).get("json_path"),
        "analytics_csv_path": (summary.get("analytics") or {}).get("csv_path"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manually refresh 14 Nasdaq option snapshots and provisional analytics")
    parser.add_argument("--mode", choices=["live"], required=True, help="This explicit command performs a live collection")
    parser.add_argument("--confirm-live", action="store_true", help="Required confirmation; without it no collection starts")
    parser.add_argument("--output-root", required=True, help="New or existing parent directory for unique run folders")
    args = parser.parse_args(argv)
    if not args.confirm_live:
        parser.error("LIVE_REFRESH_REQUIRES_CONFIRM_LIVE")
    summary = run_live_batch(args.output_root)
    completion = render_completion(summary)
    print(json.dumps(completion, ensure_ascii=False, indent=2))
    return 0 if completion["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
