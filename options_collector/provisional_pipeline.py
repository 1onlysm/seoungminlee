"""Offline connection from saved option snapshots to provisional analytics."""
from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .provisional_analytics import CSV_FIELDS, analyze_contracts, write_outputs
from .registry import REGISTRY

SYMBOLS = tuple(REGISTRY)
ANALYTIC_FIELDS = (
    "contracts_count",
    "call_volume_observed_sum", "put_volume_observed_sum",
    "call_oi_observed_sum", "put_oi_observed_sum",
    "call_volume_observed_count", "put_volume_observed_count",
    "call_oi_observed_count", "put_oi_observed_count",
    "call_volume_missing_count", "put_volume_missing_count",
    "call_oi_missing_count", "put_oi_missing_count",
    "call_volume_coverage_pct", "put_volume_coverage_pct",
    "observed_volume_pcr", "status", "limitations",
)


def _snapshot_index(snapshot_root: str | Path, symbols: Iterable[str]) -> dict[str, Path]:
    root = Path(snapshot_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"SNAPSHOT_ROOT_NOT_FOUND:{root}")
    wanted = set(symbols)
    found: dict[str, list[Path]] = {symbol: [] for symbol in wanted}
    for manifest_path in root.rglob("manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        symbol = manifest.get("symbol") if isinstance(manifest, dict) else None
        if symbol in wanted and (manifest_path.parent / "contracts.csv").is_file():
            found[symbol].append(manifest_path.parent)
    missing = sorted(symbol for symbol, paths in found.items() if not paths)
    duplicates = sorted(symbol for symbol, paths in found.items() if len(paths) > 1)
    if missing:
        raise FileNotFoundError("SNAPSHOT_UNAVAILABLE:" + ",".join(missing))
    if duplicates:
        raise ValueError("MULTIPLE_SNAPSHOTS_FOUND:" + ",".join(duplicates))
    return {symbol: paths[0] for symbol, paths in found.items()}


def _expected_map(path: str | Path | None) -> dict[str, dict] | None:
    if path is None:
        return None
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    rows = payload.get("symbols")
    if not isinstance(rows, list):
        raise ValueError("EXPECTED_ANALYTICS_SCHEMA_INVALID")
    return {row["symbol"]: row for row in rows if isinstance(row, dict) and "symbol" in row}


def _compare(result: dict, expected: dict | None) -> bool | None:
    if expected is None:
        return None
    reference = expected.get(result["symbol"])
    if reference is None:
        return False
    return all(result.get(field) == reference.get(field) for field in ANALYTIC_FIELDS)


def run_pipeline(
    snapshot_root: str | Path,
    output_dir: str | Path,
    *,
    expected_analytics: str | Path | None = None,
    symbols: Iterable[str] = SYMBOLS,
) -> dict:
    """Read saved normalized CSVs, call WORK 04-P analytics, and write outputs."""
    ordered_symbols = tuple(symbols)
    unknown = sorted(set(ordered_symbols) - set(REGISTRY))
    if unknown:
        raise ValueError("UNREGISTERED_SYMBOL:" + ",".join(unknown))
    if len(set(ordered_symbols)) != len(ordered_symbols):
        raise ValueError("DUPLICATE_SYMBOL_REQUEST")
    source_root = Path(snapshot_root).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    if destination == source_root or source_root in destination.parents:
        raise ValueError("OUTPUT_MUST_BE_OUTSIDE_SNAPSHOT_ROOT")
    json_path = destination / "provisional_analytics.json"
    csv_path = destination / "provisional_analytics.csv"
    if json_path.exists() or csv_path.exists():
        raise FileExistsError("PIPELINE_OUTPUT_ALREADY_EXISTS")

    snapshots = _snapshot_index(source_root, ordered_symbols)
    expected = _expected_map(expected_analytics)
    results = []
    for symbol in ordered_symbols:
        snapshot_dir = snapshots[symbol]
        manifest_path = snapshot_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("symbol") != symbol:
            raise ValueError(f"MANIFEST_SYMBOL_MISMATCH:{symbol}")
        with (snapshot_dir / "contracts.csv").open(newline="", encoding="utf-8") as handle:
            contracts = list(csv.DictReader(handle))
        result = analyze_contracts(symbol, contracts, manifest.get("collected_at_utc"))
        result["snapshot_path"] = str(snapshot_dir)
        result["manifest_path"] = str(manifest_path)
        result["snapshot_version"] = manifest.get("version") or snapshot_dir.name
        result["matches_existing_analytics"] = _compare(result, expected)
        results.append(result)

    destination.mkdir(parents=True, exist_ok=True)
    write_outputs(results, destination)
    generated_at = datetime.now(timezone.utc).isoformat()
    comparison = None
    if expected is not None:
        mismatches = [row["symbol"] for row in results if not row["matches_existing_analytics"]]
        comparison = {
            "expected_analytics_path": str(Path(expected_analytics).expanduser().resolve()),
            "matched_symbols": len(results) - len(mismatches),
            "mismatched_symbols": mismatches,
        }
    json_path = destination / "provisional_analytics.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["pipeline"] = {
        "mode": "OFFLINE_SNAPSHOT_REPLAY",
        "generated_at_utc": generated_at,
        "snapshot_root": str(source_root),
        "comparison": comparison,
    }
    _atomic_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write_csv_with_provenance(destination / "provisional_analytics.csv", results)
    return {
        "symbols_processed": len(results),
        "json_path": str(json_path),
        "csv_path": str(destination / "provisional_analytics.csv"),
        "generated_at_utc": generated_at,
        "comparison": comparison,
        "results": results,
    }


def _write_csv_with_provenance(path: Path, results: list[dict]) -> None:
    fields = CSV_FIELDS + ["snapshot_timestamp", "snapshot_path"]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow({
                "symbol": row.get("symbol"),
                "contracts": row.get("contracts_count"),
                "call_volume": row.get("call_volume_observed_sum"),
                "put_volume": row.get("put_volume_observed_sum"),
                "call_oi": row.get("call_oi_observed_sum"),
                "put_oi": row.get("put_oi_observed_sum"),
                "call_coverage_pct": row.get("call_volume_coverage_pct"),
                "put_coverage_pct": row.get("put_volume_coverage_pct"),
                "observed_pcr": row.get("observed_volume_pcr"),
                "status": row.get("status"),
                "snapshot_timestamp": row.get("snapshot_timestamp"),
                "snapshot_path": row.get("snapshot_path"),
            })
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _atomic_text(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline replay of saved Nasdaq option snapshots into provisional analytics")
    parser.add_argument("--snapshot-root", required=True, help="Existing WORK 04-N snapshots root (read-only)")
    parser.add_argument("--output-dir", required=True, help="New, separate directory for JSON and CSV results")
    parser.add_argument("--expected-analytics", help="Optional WORK 04-P JSON used for deterministic comparison")
    parser.add_argument("--symbols", nargs="+", choices=sorted(REGISTRY), default=list(SYMBOLS))
    args = parser.parse_args()
    result = run_pipeline(args.snapshot_root, args.output_dir, expected_analytics=args.expected_analytics, symbols=args.symbols)
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
