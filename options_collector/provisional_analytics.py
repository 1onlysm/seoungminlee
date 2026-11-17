"""Small offline-only aggregations for observed option-chain Volume and OI."""
from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Mapping

FIELDS = {
    "call_volume": "c_volume",
    "put_volume": "p_volume",
    "call_oi": "c_openinterest",
    "put_oi": "p_openinterest",
}
LIMITATIONS = [
    "EOD_UNVERIFIED",
    "MISSINGNESS_CAUSE_UNKNOWN",
    "FULL_VOLUME_COMPLETENESS_UNVERIFIED",
]
CSV_FIELDS = [
    "symbol", "contracts", "call_volume", "put_volume", "call_oi", "put_oi",
    "call_coverage_pct", "put_coverage_pct", "observed_pcr", "status",
]


def _count(value: object, *, symbol: str, field: str, row_index: int) -> int | None:
    """Return a nonnegative integer observation, or None for a missing token."""
    if value is None or value == "" or value == "--":
        return None
    if isinstance(value, bool):
        raise ValueError(f"NON_NUMERIC_VALUE:{symbol}:{field}:{row_index}")
    text = str(value).replace(",", "").strip()
    if text == "":
        return None
    try:
        number = int(text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"NON_INTEGER_COUNT:{symbol}:{field}:{row_index}") from exc
    if number < 0 or str(number) != text and not (text.startswith("+") and str(number) == text[1:]):
        raise ValueError(f"INVALID_COUNT:{symbol}:{field}:{row_index}")
    return number


def analyze_contracts(
    symbol: str,
    contracts: Iterable[Mapping[str, object]],
    snapshot_timestamp: str | None = None,
) -> dict:
    """Aggregate numeric observations without imputing missing Volume/OI values."""
    rows = list(contracts)
    result = {
        "symbol": symbol,
        "snapshot_timestamp": snapshot_timestamp,
        "contracts_count": len(rows),
        "status": "PROVISIONAL",
        "limitations": list(LIMITATIONS),
    }
    counts: dict[str, int] = {}
    sums: dict[str, int] = {}
    for name, input_field in FIELDS.items():
        observed_sum = observed_count = missing_count = 0
        for row_index, row in enumerate(rows):
            value = _count(row.get(input_field), symbol=symbol, field=input_field, row_index=row_index)
            if value is None:
                missing_count += 1
            else:
                observed_sum += value
                observed_count += 1
        counts[name] = observed_count
        sums[name] = observed_sum
        result[f"{name}_observed_sum"] = observed_sum
        result[f"{name}_observed_count"] = observed_count
        if name.endswith("volume"):
            result[f"{name}_missing_count"] = missing_count
        else:
            result[f"{name}_missing_count"] = missing_count

    denominator = len(rows)
    result["call_volume_coverage_pct"] = (counts["call_volume"] * 100 / denominator) if denominator else None
    result["put_volume_coverage_pct"] = (counts["put_volume"] * 100 / denominator) if denominator else None
    if counts["call_volume"] == 0:
        result["observed_volume_pcr"] = None
        result["pcr_unavailable_reason"] = "NO_NUMERIC_CALL_VOLUME"
    elif sums["call_volume"] == 0:
        result["observed_volume_pcr"] = None
        result["pcr_unavailable_reason"] = "CALL_VOLUME_SUM_ZERO"
    else:
        result["observed_volume_pcr"] = sums["put_volume"] / sums["call_volume"]
        result["pcr_unavailable_reason"] = None
    return result


def write_outputs(results: Iterable[Mapping[str, object]], output_dir: str | Path) -> tuple[Path, Path]:
    """Write a JSON detail file and the required one-row-per-symbol CSV."""
    rows = list(results)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "provisional_analytics.json"
    csv_path = directory / "provisional_analytics.csv"
    payload = {"status": "PROVISIONAL", "limitations": list(LIMITATIONS), "symbols": rows}
    _atomic_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=directory, delete=False) as handle:
        temp_csv = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
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
            })
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_csv, csv_path)
    return json_path, csv_path


def _atomic_text(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
