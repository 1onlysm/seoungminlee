"""Offline NVDA strike-level volume and open-interest aggregation and charts."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = {
    "call_volume": "c_volume",
    "put_volume": "p_volume",
    "call_oi": "c_openinterest",
    "put_oi": "p_openinterest",
}
LIMITATIONS = ["EOD_UNVERIFIED", "MISSINGNESS_CAUSE_UNKNOWN", "FULL_VOLUME_COMPLETENESS_UNVERIFIED"]
WORK04R_REFERENCE = {
    "contracts": 2188,
    "call_volume_observed_sum": 1457430,
    "put_volume_observed_sum": 953110,
    "call_oi_observed_sum": 9839124,
    "put_oi_observed_sum": 8636754,
    "status": "PROVISIONAL",
}


def _number(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if text in ("", "--"):
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _output_number(value: Decimal | None):
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def aggregate_strikes(contracts: list[dict]) -> dict:
    """Group normalized contracts across all expirations without imputing missing data."""
    groups: dict[Decimal, dict] = {}
    for index, contract in enumerate(contracts):
        if contract.get("symbol") != "NVDA":
            raise ValueError(f"UNEXPECTED_SYMBOL_AT_ROW:{index}")
        strike = _number(contract.get("strike"))
        if strike is None or strike <= 0:
            raise ValueError(f"INVALID_STRIKE_AT_ROW:{index}")
        group = groups.setdefault(strike, {
            "strike_value": strike,
            "expirations": set(),
            "contract_count": 0,
            **{field: Decimal(0) for field in FIELDS},
            **{f"{field}_observed_count": 0 for field in FIELDS},
            **{f"{field}_missing_count": 0 for field in FIELDS},
        })
        group["contract_count"] += 1
        if contract.get("expiration"):
            group["expirations"].add(str(contract["expiration"]))
        for output_field, source_field in FIELDS.items():
            value = _number(contract.get(source_field))
            if value is None:
                group[f"{output_field}_missing_count"] += 1
            else:
                group[output_field] += value
                group[f"{output_field}_observed_count"] += 1

    rows = []
    for strike in sorted(groups):
        item = groups[strike]
        row = {
            "strike": _output_number(strike),
            "expiration_count": len(item["expirations"]),
            "contract_count": item["contract_count"],
        }
        for field in FIELDS:
            count = item[f"{field}_observed_count"]
            row[f"{field}_observed_sum"] = _output_number(item[field]) if count else None
            row[f"{field}_observed_count"] = count
            row[f"{field}_missing_count"] = item[f"{field}_missing_count"]
        rows.append(row)

    totals = {"contracts": len(contracts), "strike_count": len(rows)}
    for field in FIELDS:
        count = sum(row[f"{field}_observed_count"] for row in rows)
        total = sum((_number(row[f"{field}_observed_sum"]) or Decimal(0)) for row in rows)
        totals[f"{field}_observed_sum"] = _output_number(total) if count else None
        totals[f"{field}_observed_count"] = count
        totals[f"{field}_missing_count"] = len(contracts) - count

    top5 = {}
    for field in FIELDS:
        total = totals[f"{field}_observed_sum"]
        candidates = [r for r in rows if r[f"{field}_observed_count"] and r[f"{field}_observed_sum"] is not None]
        candidates.sort(key=lambda r: (-Decimal(str(r[f"{field}_observed_sum"])), Decimal(str(r["strike"]))))
        top5[field] = [
            {"strike": row["strike"], "observed_sum": row[f"{field}_observed_sum"],
             "share_pct": (row[f"{field}_observed_sum"] / total * 100) if total else None}
            for row in candidates[:5]
        ]
    return {"rows": rows, "totals": totals, "top5": top5, "status": "PROVISIONAL", "limitations": LIMITATIONS.copy()}


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def write_outputs(contracts_csv: str | Path, manifest_path: str | Path, output_dir: str | Path) -> dict:
    source = Path(contracts_csv).expanduser().resolve()
    manifest_file = Path(manifest_path).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    if not source.is_file() or not manifest_file.is_file():
        raise FileNotFoundError("NVDA_STRIKE_DATA_UNAVAILABLE")
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("OUTPUT_DIRECTORY_NOT_EMPTY")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("symbol") != "NVDA":
        raise ValueError("MANIFEST_SYMBOL_MISMATCH")
    with source.open(encoding="utf-8", newline="") as handle:
        contracts = list(csv.DictReader(handle))
    result = aggregate_strikes(contracts)
    result.update({
        "symbol": "NVDA", "snapshot_timestamp_utc": manifest.get("collected_at_utc"),
        "snapshot_timestamp_et": manifest.get("collected_at_et"),
        "snapshot_trading_date_et": manifest.get("trading_date_et"),
        "source_contracts_csv": str(source), "source_manifest": str(manifest_file),
        "work04r_reference": WORK04R_REFERENCE,
        "reference_matches": {
            key: result["totals"].get(key) == value
            for key, value in WORK04R_REFERENCE.items() if key in result["totals"]
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "interpretation": [
            "Strike concentration describes observed contract values only.",
            "Call volume concentration is not a bullish signal; put volume concentration is not a bearish signal.",
            "Open interest concentration is not a confirmed support or resistance level.",
            "Dealer positioning and GEX were not calculated.",
        ],
    })
    result["chart_display"] = {
        "volume": _display_window(result["rows"], "call_volume_observed_sum", "put_volume_observed_sum"),
        "open_interest": _display_window(result["rows"], "call_oi_observed_sum", "put_oi_observed_sum"),
        "note": "Charts show a contiguous strike window covering at least 99% of observed totals; complete strike data remains in CSV and JSON.",
    }
    destination.mkdir(parents=True, exist_ok=True)
    volume_rows = [{"strike": r["strike"], "call_volume_observed_sum": r["call_volume_observed_sum"],
                    "put_volume_observed_sum": r["put_volume_observed_sum"],
                    "call_volume_observed_count": r["call_volume_observed_count"],
                    "put_volume_observed_count": r["put_volume_observed_count"],
                    "call_volume_missing_count": r["call_volume_missing_count"],
                    "put_volume_missing_count": r["put_volume_missing_count"]} for r in result["rows"]]
    oi_rows = [{"strike": r["strike"], "call_oi_observed_sum": r["call_oi_observed_sum"],
                "put_oi_observed_sum": r["put_oi_observed_sum"],
                "call_oi_observed_count": r["call_oi_observed_count"],
                "put_oi_observed_count": r["put_oi_observed_count"],
                "call_oi_missing_count": r["call_oi_missing_count"],
                "put_oi_missing_count": r["put_oi_missing_count"]} for r in result["rows"]]
    _write_csv(destination / "nvda_strike_volume.csv", volume_rows)
    _write_csv(destination / "nvda_strike_oi.csv", oi_rows)
    _atomic_text(destination / "nvda_strike_summary.json", json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _plot_map(result["rows"], "call_volume_observed_sum", "put_volume_observed_sum", "NVDA — Call / Put Volume by Strike", "Observed Option Volume", destination / "nvda_volume_map.png", result["chart_display"]["volume"])
    _plot_map(result["rows"], "call_oi_observed_sum", "put_oi_observed_sum", "NVDA — Call / Put Open Interest by Strike", "Observed Open Interest", destination / "nvda_oi_map.png", result["chart_display"]["open_interest"])
    return {"summary": result, "output_dir": str(destination), "files": [str(destination / name) for name in (
        "nvda_strike_volume.csv", "nvda_strike_oi.csv", "nvda_strike_summary.json", "nvda_volume_map.png", "nvda_oi_map.png")],
        "reference_matches": result["reference_matches"]}


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(rows[0]) if rows else ["strike"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _display_window(rows: list[dict], call_field: str, put_field: str) -> dict:
    points = []
    for row in rows:
        call = _number(row[call_field]) or Decimal(0)
        put = _number(row[put_field]) or Decimal(0)
        points.append((float(row["strike"]), float(call + put)))
    total = sum(weight for _, weight in points)
    if not points or total <= 0:
        return {"strike_min": points[0][0] if points else None, "strike_max": points[-1][0] if points else None,
                "observed_total": total, "displayed_observed_total_share_pct": None}
    target = total * 0.99
    best = None
    right = 0
    running = 0.0
    for left in range(len(points)):
        while right < len(points) and running < target:
            running += points[right][1]
            right += 1
        if running >= target:
            hi = right - 1
            candidate = (points[hi][0] - points[left][0], left, hi)
            if best is None or candidate < best:
                best = candidate
        if right > left:
            running -= points[left][1]
        else:
            right = left + 1
    if best is None:
        lo, hi = 0, len(points) - 1
    else:
        _, lo, hi = best
    shown = sum(weight for _, weight in points[lo:hi + 1])
    return {"strike_min": points[lo][0], "strike_max": points[hi][0], "observed_total": total,
            "displayed_observed_total_share_pct": shown / total * 100}


def _plot_map(rows: list[dict], call_field: str, put_field: str, title: str, ylabel: str, path: Path, display: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = [float(row["strike"]) for row in rows]
    width = min(1.0, (min((x[i + 1] - x[i] for i in range(len(x) - 1)), default=1.0) * 0.38))
    call = [float(row[call_field]) if row[call_field] is not None else math.nan for row in rows]
    put = [float(row[put_field]) if row[put_field] is not None else math.nan for row in rows]
    fig, ax = plt.subplots(figsize=(16, 7), layout="constrained")
    ax.bar([v - width / 2 for v in x], call, width=width, label="Call", color="#2563eb")
    ax.bar([v + width / 2 for v in x], put, width=width, label="Put", color="#f97316")
    lo, hi = display.get("strike_min"), display.get("strike_max")
    if lo is not None and hi is not None:
        visible = [value for value in x if lo <= value <= hi]
        stride = max(1, len(visible) // 28)
        ticks = visible[::stride]
        ax.set_xticks(ticks, [f"{v:g}" for v in ticks], rotation=55, ha="right")
        pad = max(width * 2, (hi - lo) * 0.015)
        ax.set_xlim(lo - pad, hi + pad)
    share = display.get("displayed_observed_total_share_pct")
    share_note = f"window contains {share:.2f}% of observed sum" if share is not None else "observed sum unavailable"
    ax.set_title(title + " — PROVISIONAL\nEOD_UNVERIFIED · " + share_note + " · full strike data in CSV/JSON")
    ax.set_xlabel("Strike ($)")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline NVDA strike-level option volume and OI maps")
    parser.add_argument("--contracts-csv", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    result = write_outputs(args.contracts_csv, args.manifest, args.output_dir)
    print(json.dumps({"output_dir": result["output_dir"], "files": result["files"],
                      "contracts": result["summary"]["totals"]["contracts"],
                      "strike_count": result["summary"]["totals"]["strike_count"],
                      "reference_matches": result["reference_matches"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
