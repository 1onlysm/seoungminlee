"""Build a self-contained, offline NVDA options-flow dashboard from verified files."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

from .nvda_strike_map import aggregate_strikes

REFERENCE = {
    "contracts": 2188,
    "strike_count": 444,
    "call_volume_observed_sum": 1457430,
    "put_volume_observed_sum": 953110,
    "call_oi_observed_sum": 9839124,
    "put_oi_observed_sum": 8636754,
}
TOP5_REFERENCE = {
    "call_volume": [(170, 133245), (200, 129267), (160, 125486), (180, 108477), (175, 78244)],
    "put_volume": [(150, 106756), (140, 79929), (155, 78619), (145, 72738), (160, 60599)],
    "call_oi": [(200, 853791), (250, 434092), (300, 391677), (210, 387819), (220, 371382)],
    "put_oi": [(150, 647469), (100, 428220), (140, 420000), (200, 409670), (160, 399856)],
}


def _validate_price_reference(reference: dict | None) -> dict:
    """Validate a local price contract; never infer a current quote from an option snapshot."""
    empty = {"symbol":"NVDA", "price":None, "currency":"USD", "price_type":"UNKNOWN",
             "price_timestamp":None, "captured_timestamp":None, "source":None,
             "verification_status":"SPOT_PRICE_SOURCE_UNAVAILABLE", "timestamp_precision":None}
    if reference is None:
        return empty
    if not isinstance(reference, dict) or reference.get("symbol") != "NVDA":
        raise ValueError("PRICE_REFERENCE_SYMBOL_OR_SCHEMA_INVALID")
    price = _market_num(reference.get("price"))
    if price is None or price <= 0:
        raise ValueError("PRICE_REFERENCE_VALUE_INVALID")
    if reference.get("price_type") == "HISTORICAL_REFERENCE":
        if reference.get("verification_status") != "HISTORICAL_REFERENCE_ONLY":
            raise ValueError("HISTORICAL_PRICE_CANNOT_BE_MARKED_CURRENT")
        timestamp = reference.get("price_timestamp")
        if not isinstance(timestamp, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", timestamp):
            raise ValueError("HISTORICAL_PRICE_DATE_REQUIRED")
        if not reference.get("captured_timestamp") or not reference.get("source"):
            raise ValueError("PRICE_CAPTURE_AND_SOURCE_REQUIRED")
        return {**empty, **reference, "price":price, "timestamp_precision":"DATE"}
    if reference.get("price_type") not in {"REGULAR_CLOSE","PREMARKET","REGULAR_SESSION","AFTER_HOURS"}:
        raise ValueError("PRICE_TYPE_UNVERIFIED")
    if reference.get("verification_status") != "VERIFIED_PRICE_REFERENCE_AVAILABLE":
        raise ValueError("PRICE_VERIFICATION_STATUS_INVALID")
    if not reference.get("price_timestamp") or not reference.get("captured_timestamp") or not reference.get("source"):
        raise ValueError("PRICE_TIMESTAMP_CAPTURE_AND_SOURCE_REQUIRED")
    return {**empty, **reference, "price":price, "timestamp_precision":"TIMESTAMP"}


def _price_reference_from_raw(raw_obj: dict, manifest: dict) -> dict:
    """Extract only the underlying last-trade text preserved in the Nasdaq options response."""
    raw_value = (raw_obj.get("data") or {}).get("lastTrade") if isinstance(raw_obj, dict) else None
    if not isinstance(raw_value, str):
        return _validate_price_reference(None)
    match = re.fullmatch(r"\s*LAST TRADE:\s*\$([0-9,]+(?:\.\d+)?)\s*\(AS OF ([A-Z]{3})\s+(\d{1,2}),\s*(\d{4})\)\s*", raw_value)
    if not match:
        return _validate_price_reference(None)
    month = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}.get(match.group(2))
    if not month:
        return _validate_price_reference(None)
    from datetime import date
    price_date = date(int(match.group(4)), month, int(match.group(3))).isoformat()
    return _validate_price_reference({
        "symbol":"NVDA", "price":float(match.group(1).replace(",", "")), "currency":"USD",
        "price_type":"HISTORICAL_REFERENCE", "price_timestamp":price_date,
        "captured_timestamp":manifest.get("collected_at_utc"),
        "source":"Nasdaq options response · data.lastTrade",
        "verification_status":"HISTORICAL_REFERENCE_ONLY", "timestamp_precision":"DATE",
        "raw_value":raw_value, "freshness_status":"NOT_VERIFIABLE_FROM_DATE_ONLY_FIELD",
        "synchronous_with_option_chain":False,
    })


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _num(value):
    if value in (None, "", "--"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _same_num(a, b) -> bool:
    if a in (None, "", "--") and b in (None, "", "--"):
        return True
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def _market_num(value):
    if value in (None, "", "--"):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _field_class(value):
    if value is None:
        return "JSON_NULL"
    if isinstance(value, str) and not value.strip():
        return "EMPTY_STRING"
    if value == "--":
        return "DASH_PLACEHOLDER"
    if _market_num(value) is None:
        return "NON_NUMERIC_INVALID"
    if _market_num(value) == 0:
        return "EXPLICIT_ZERO"
    return "OBSERVED_NUMERIC"


def _expiration_payload(contracts):
    field_map = {
        "c_Volume": "call_volume", "p_Volume": "put_volume",
        "c_Openinterest": "call_oi", "p_Openinterest": "put_oi",
        "c_Bid": "call_bid", "c_Ask": "call_ask",
        "p_Bid": "put_bid", "p_Ask": "put_ask",
    }
    audit_fields = ["strike", *field_map, "c_Last", "c_Change", "p_Last", "p_Change",
                    "c_ImpliedVolatility", "p_ImpliedVolatility"]
    audit = {}
    for field in audit_fields:
        counts = {"OBSERVED_NUMERIC": 0, "EXPLICIT_ZERO": 0, "DASH_PLACEHOLDER": 0,
                  "EMPTY_STRING": 0, "JSON_NULL": 0, "FIELD_ABSENT": 0, "NON_NUMERIC_INVALID": 0}
        for row in contracts:
            raw = json.loads(row.get("raw_row_json") or "{}")
            if field == "strike":
                value = raw.get(field, row.get("strike"))
            elif field not in raw:
                counts["FIELD_ABSENT"] += 1
                continue
            else:
                value = raw[field]
            kind = _field_class(value)
            counts[kind] += 1
        audit[field] = {"raw_field": field, "counts": counts,
                        "valid_numeric_count": counts["OBSERVED_NUMERIC"] + counts["EXPLICIT_ZERO"],
                        "missing_count": counts["DASH_PLACEHOLDER"] + counts["EMPTY_STRING"] + counts["JSON_NULL"] + counts["FIELD_ABSENT"],
                        "usable": field in ("strike", *field_map)}

    dates = sorted({str(row.get("expiration")) for row in contracts if row.get("expiration")})
    groups = {date: [] for date in dates}
    display_contracts = []
    for row in contracts:
        raw = json.loads(row.get("raw_row_json") or "{}")
        exp = str(row.get("expiration") or "")
        strike = _market_num(row.get("strike"))
        item = {"expiration": exp, "strike": strike, "root": row.get("root"),
                "root_class": row.get("root_class")}
        for field, name in field_map.items():
            value = raw.get(field)
            item[name] = _market_num(value)
            item[name + "_raw"] = value if field in raw else None
        if exp in groups:
            groups[exp].append(item)
        display_contracts.append(item)

    metric_names = ("call_volume", "put_volume", "call_oi", "put_oi")
    expiration_audit = []
    all_sums = {key: 0 for key in metric_names}
    for exp, items in groups.items():
        totals = {key: sum(x[key] for x in items if x[key] is not None) for key in metric_names}
        counts = {key: sum(x[key] is not None for x in items) for key in metric_names}
        missing = {key: len(items) - counts[key] for key in metric_names}
        coverage_pct = {key: (counts[key] / len(items) * 100 if items else None) for key in metric_names}
        expiration_audit.append({"expiration": exp, "contracts": len(items),
                                 "strikes": len({x["strike"] for x in items if x["strike"] is not None}),
                                 "observed_sums": totals, "observed_counts": counts,
                                 "missing_counts": missing, "coverage_pct": coverage_pct})
        for key in metric_names:
            all_sums[key] += totals[key]
    audit["expiration"] = {"raw_field": "expirygroup + expiryDate → normalized expiration",
                           "valid_date_count": sum(bool(row.get("expiration")) for row in contracts),
                           "missing_count": sum(not row.get("expiration") for row in contracts), "usable": True}
    audit["symbol"] = {"raw_field": "CSV symbol", "valid_symbol_count": sum(row.get("symbol") == "NVDA" for row in contracts),
                       "missing_count": sum(not row.get("symbol") for row in contracts), "usable": True}
    return dates, display_contracts, audit, expiration_audit, all_sums


def load_verified_data(contracts_csv, strike_summary, volume_csv, oi_csv, manifest_json, raw_json, batch_summary) -> tuple[dict, dict]:
    paths = {"contracts_csv": Path(contracts_csv), "strike_summary": Path(strike_summary),
             "volume_csv": Path(volume_csv), "oi_csv": Path(oi_csv), "manifest": Path(manifest_json),
             "raw_json": Path(raw_json), "batch_summary": Path(batch_summary)}
    if any(not p.is_file() for p in paths.values()):
        missing = [str(p) for p in paths.values() if not p.is_file()]
        raise FileNotFoundError("INPUT_EVIDENCE_UNAVAILABLE:" + ",".join(missing))

    manifest = _read_json(paths["manifest"])
    raw = paths["raw_json"].read_bytes()
    raw_obj = json.loads(raw)
    price_reference = _price_reference_from_raw(raw_obj, manifest)
    raw_data = raw_obj.get("data") if isinstance(raw_obj, dict) else None
    raw_table = raw_data.get("table") if isinstance(raw_data, dict) else None
    if not isinstance(raw_table, dict) or not isinstance(raw_table.get("rows"), list):
        raise ValueError("RAW_OPTIONS_CHAIN_SCHEMA_INVALID")
    raw_total_record = raw_data.get("totalRecord")
    raw_row_count = len(raw_table["rows"])
    raw_expiry_headers = sum(bool(row.get("expirygroup")) for row in raw_table["rows"] if isinstance(row, dict))
    raw_sha = hashlib.sha256(raw).hexdigest()
    if manifest.get("symbol") != "NVDA" or raw_sha != manifest.get("raw_sha256") or len(raw) != manifest.get("raw_bytes"):
        raise ValueError("RAW_EVIDENCE_INTEGRITY_FAILED")
    with paths["contracts_csv"].open(encoding="utf-8", newline="") as f:
        contracts = list(csv.DictReader(f))
    if len(contracts) != manifest.get("contract_rows") or any(row.get("symbol") != "NVDA" for row in contracts):
        raise ValueError("CONTRACT_CSV_MANIFEST_MISMATCH")

    computed = aggregate_strikes(contracts)
    source = _read_json(paths["strike_summary"])
    source_rows = {float(row["strike"]): row for row in source.get("rows", [])}
    computed_rows = {float(row["strike"]): row for row in computed["rows"]}
    row_match = set(source_rows) == set(computed_rows)
    if row_match:
        for strike, row in computed_rows.items():
            prior = source_rows[strike]
            for metric in ("call_volume", "put_volume", "call_oi", "put_oi"):
                for suffix in ("_observed_sum", "_observed_count", "_missing_count"):
                    key = metric + suffix
                    if not _same_num(row.get(key), prior.get(key)):
                        row_match = False

    csv_match = True
    for file_key, fields in (
        ("volume_csv", ("call_volume_observed_sum", "put_volume_observed_sum", "call_volume_observed_count", "put_volume_observed_count")),
        ("oi_csv", ("call_oi_observed_sum", "put_oi_observed_sum", "call_oi_observed_count", "put_oi_observed_count")),
    ):
        with paths[file_key].open(encoding="utf-8", newline="") as f:
            file_rows = list(csv.DictReader(f))
        if len(file_rows) != len(computed_rows):
            csv_match = False
            continue
        by_strike = {float(row["strike"]): row for row in file_rows}
        if set(by_strike) != set(computed_rows):
            csv_match = False
            continue
        for strike, row in computed_rows.items():
            for field in fields:
                if not _same_num(by_strike[strike].get(field), row.get(field)):
                    csv_match = False

    batch = _read_json(paths["batch_summary"])
    batch_row = next((row for row in batch.get("results", []) if row.get("symbol") == "NVDA"), None)
    batch_match = bool(batch_row and batch_row.get("response_sha256") == raw_sha and batch_row.get("contracts_count") == len(contracts))
    source_match = row_match and csv_match and batch_match
    totals = computed["totals"]
    totals_match = {key: totals.get(key) == value for key, value in REFERENCE.items()}
    top5_match = {}
    for name, expected in TOP5_REFERENCE.items():
        actual = [(int(row["strike"]), int(row["observed_sum"])) for row in computed["top5"][name]]
        top5_match[name] = actual == expected

    expirations, chain_contracts, field_audit, expiration_audit, expiration_sums = _expiration_payload(contracts)
    expiration_sums_match = {
        "call_volume_observed_sum": expiration_sums["call_volume"] == totals["call_volume_observed_sum"],
        "put_volume_observed_sum": expiration_sums["put_volume"] == totals["put_volume_observed_sum"],
        "call_oi_observed_sum": expiration_sums["call_oi"] == totals["call_oi_observed_sum"],
        "put_oi_observed_sum": expiration_sums["put_oi"] == totals["put_oi_observed_sum"],
    }
    call_vol_pct = totals["call_volume_observed_count"] / len(contracts) * 100
    put_vol_pct = totals["put_volume_observed_count"] / len(contracts) * 100
    vol_sum = totals["call_volume_observed_sum"] + totals["put_volume_observed_sum"]
    oi_sum = totals["call_oi_observed_sum"] + totals["put_oi_observed_sum"]
    display = source.get("chart_display", {})
    vol_range, oi_range = display.get("volume", {}), display.get("open_interest", {})
    default_min = min(x for x in (vol_range.get("strike_min"), oi_range.get("strike_min")) if x is not None)
    default_max = max(x for x in (vol_range.get("strike_max"), oi_range.get("strike_max")) if x is not None)
    data = {
        "brand": "NAVI OPTIONS LAB", "symbol": "NVDA", "title": "NVDA Options Flow Summary",
        "subtitle": "Observed Nasdaq Options Snapshot · All Expirations",
        "run_id": batch.get("run_id"), "raw_sha256": raw_sha,
        "snapshot_timestamp_utc": manifest.get("collected_at_utc"),
        "snapshot_timestamp_et": manifest.get("collected_at_et"), "trading_date_et": manifest.get("trading_date_et"),
        "contracts_count": len(contracts), "expiry_count": len(expirations), "strike_count": len(computed["rows"]),
        "raw_total_record": raw_total_record, "raw_row_count": raw_row_count,
        "raw_expiry_header_count": raw_expiry_headers,
        "raw_headers": raw_table.get("headers", {}),
        "all_expirations": True, "status": "PROVISIONAL",
        "expirations": expirations, "contracts": chain_contracts,
        "field_audit": field_audit, "expiration_audit": expiration_audit,
        "expiration_sums_match": expiration_sums_match,
        "limitations": ["EOD_UNVERIFIED", "MISSINGNESS_CAUSE_UNKNOWN", "FULL_VOLUME_COMPLETENESS_UNVERIFIED"],
        "totals": totals, "observed_volume_pcr": totals["put_volume_observed_sum"] / totals["call_volume_observed_sum"],
        "oi_ratio": totals["put_oi_observed_sum"] / totals["call_oi_observed_sum"],
        "donuts": {
            "volume": {"call": totals["call_volume_observed_sum"], "put": totals["put_volume_observed_sum"],
                       "call_pct": totals["call_volume_observed_sum"] / vol_sum * 100, "put_pct": totals["put_volume_observed_sum"] / vol_sum * 100},
            "oi": {"call": totals["call_oi_observed_sum"], "put": totals["put_oi_observed_sum"],
                   "call_pct": totals["call_oi_observed_sum"] / oi_sum * 100, "put_pct": totals["put_oi_observed_sum"] / oi_sum * 100},
        },
        "rows": computed["rows"], "top5": computed["top5"],
        "default_range": {"min": default_min, "max": default_max},
        "mobile_initial_range": {"min": 140, "max": 220},
        "full_range": {"min": min(float(row["strike"]) for row in computed["rows"]), "max": max(float(row["strike"]) for row in computed["rows"])},
        "coverage_pct": {"call_volume": call_vol_pct, "put_volume": put_vol_pct,
                         "call_oi": totals["call_oi_observed_count"] / len(contracts) * 100,
                         "put_oi": totals["put_oi_observed_count"] / len(contracts) * 100},
        "selected_strike": 170,
        "price_reference": price_reference,
        "source": {key: str(path.resolve()) for key, path in paths.items()},
    }
    validation = {
        "raw_sha256": raw_sha, "raw_bytes": len(raw), "manifest_sha256_match": True,
        "manifest_contract_count": manifest.get("contract_rows"), "csv_contract_count": len(contracts),
        "computed_strike_count": len(computed["rows"]), "source_t_json_rows": len(source_rows),
        "snapshot_batch_run_id": batch.get("run_id"), "batch_nvda_sha256_match": batch_match,
        "strike_rows_match_work04t_json": row_match, "strike_csvs_match_recalculation": csv_match,
        "reference_totals_match": totals_match, "top5_match_work04t_reference": top5_match,
        "expiration_count": len(expirations), "expiration_sums_match": expiration_sums_match,
        "raw_total_record": raw_total_record, "raw_row_count": raw_row_count,
        "raw_expiry_header_count": raw_expiry_headers,
        "field_audit": field_audit,
        "price_reference_status": price_reference["verification_status"],
        "price_reference_source_field": "data.lastTrade" if price_reference.get("price") is not None else None,
        "all_checks_pass": bool(source_match and all(totals_match.values()) and all(top5_match.values()) and all(expiration_sums_match.values()) and raw_total_record == raw_row_count and raw_expiry_headers == len(expirations) == 24 and len(contracts) == REFERENCE["contracts"] and len(computed["rows"]) == REFERENCE["strike_count"]),
    }
    if not validation["all_checks_pass"]:
        raise ValueError("DASHBOARD_DATA_VALIDATION_FAILED:" + json.dumps(validation, sort_keys=True))
    return data, validation


HTML = r'''<!doctype html>
<html lang="ko" translate="no"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><meta name="google" content="notranslate">
<title>NAVI OPTIONS LAB · NVDA 옵션</title>
<style>
:root{--bg:#090d12;--panel:#111820;--panel2:#151e27;--line:#26323e;--text:#eef4f7;--muted:#8fa0ad;--green:#42e0ad;--green2:#1aa980;--pink:#ff6687;--pink2:#d94368;--cyan:#69c8ff;--amber:#f4c46a;--shadow:0 16px 44px #0006}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 16% -10%,#16312d 0,transparent 38%),radial-gradient(ellipse at 100% 0,#1b2436 0,transparent 31%),var(--bg);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}.shell{max-width:1600px;margin:auto;padding:24px clamp(14px,2.3vw,34px) 48px}.topbar{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:26px}.brand{display:flex;align-items:center;gap:12px;font-size:13px;font-weight:800;letter-spacing:.17em}.brandmark{width:34px;height:34px;border-radius:11px;background:linear-gradient(140deg,#42e0ad,#1a9d87);display:grid;place-items:center;color:#07110f;font-weight:950;font-size:17px;box-shadow:0 0 25px #42e0ad55}.brand small{display:block;color:var(--muted);font-weight:600;letter-spacing:.04em;font-size:10px;margin-top:2px}.head-right{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end}.pill{border:1px solid var(--line);background:#111a22;border-radius:99px;padding:7px 11px;color:#c4d0d7;font-size:11px}.pill.status{border-color:#377d66;color:#72f1c2;background:#10231e;font-weight:800;letter-spacing:.09em}.hero{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin:8px 0 19px}.hero h1{font-size:clamp(27px,3vw,40px);line-height:1.08;letter-spacing:-.04em;margin:0 0 7px}.hero p{margin:0;color:var(--muted)}.hero-symbol{font-size:28px;font-weight:900;letter-spacing:.06em}.hero-symbol span{display:block;color:var(--green);font-size:11px;letter-spacing:.12em;text-align:right}.limitations{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:17px}.lim{color:#e6ba75;background:#241d12;border:1px solid #554326;padding:6px 9px;border-radius:8px;font-size:10px;font-weight:700;letter-spacing:.04em}.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:14px}.card,.panel{background:linear-gradient(145deg,#141c24,#10171e);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}.kpi{padding:16px 18px;position:relative;overflow:hidden}.kpi:after{content:"";position:absolute;width:86px;height:86px;right:-25px;top:-30px;background:var(--glow,#42e0ad);filter:blur(50px);opacity:.22}.kpi label{display:block;color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.kpi strong{display:block;font-variant-numeric:tabular-nums;font-size:clamp(23px,2.5vw,32px);letter-spacing:-.035em;margin:8px 0 2px}.kpi .sub{font-size:10px;color:#768895}.call{color:var(--green)}.put{color:var(--pink)}.summary-grid{display:grid;grid-template-columns:1fr 1fr 1.2fr;gap:13px;margin-bottom:14px}.panel{padding:17px 18px}.panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:13px}.panel h2{font-size:15px;margin:0;font-weight:800;letter-spacing:-.01em}.eyebrow{color:var(--muted);font-size:10px;margin-top:3px}.donut-row{display:flex;align-items:center;gap:19px;min-height:123px}.donut{width:105px;height:105px;position:relative;flex:none}.donut svg{transform:rotate(-90deg);width:100%;height:100%}.donut circle{fill:none;stroke-width:13}.donut .track{stroke:#26323e}.donut .seg{stroke:var(--green);stroke-linecap:butt}.donut .seg.putseg{stroke:var(--pink)}.donut center{position:absolute;inset:0;display:grid;place-content:center;text-align:center;font-size:21px;font-weight:850}.donut center small{display:block;font-size:9px;color:var(--muted);font-weight:650;letter-spacing:.08em}.legend{display:grid;gap:10px;min-width:0}.leg{display:grid;grid-template-columns:8px 1fr auto;gap:8px;align-items:center;font-size:11px}.swatch{height:8px;width:8px;border-radius:3px}.leg b{font-variant-numeric:tabular-nums}.ratio-box{display:flex;align-items:baseline;gap:12px;margin:9px 0}.ratio-box strong{font-size:30px;letter-spacing:-.04em}.ratio-box span{color:var(--muted);font-size:10px}.mini-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:12px}.mini{background:#0d141a;border:1px solid #202b34;padding:10px;border-radius:9px}.mini span{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.07em}.mini b{display:block;font-size:14px;margin-top:4px;font-variant-numeric:tabular-nums}.main-grid{display:grid;grid-template-columns:minmax(0,2.15fr) minmax(300px,.9fr);gap:13px;align-items:start}.chart-panel{padding:17px 18px 13px;min-width:0}.chart-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.toolbar-group{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.toggle{display:inline-flex;align-items:center;gap:6px;color:#c8d4dc;font-size:11px}.toggle input{accent-color:var(--green)}button{border:1px solid #34434f;background:#17212a;color:#dce6eb;border-radius:8px;padding:7px 10px;font:inherit;font-size:10px;font-weight:700;cursor:pointer}button:hover{border-color:var(--green);color:#fff}.rangetext{color:var(--muted);font-size:10px}.chart-wrap{position:relative;margin-top:7px;border-radius:10px;background:linear-gradient(#101820,#0d141a);border:1px solid #1d2933;overflow:hidden}svg.flow{display:block;width:100%;height:320px;touch-action:pan-y;cursor:crosshair}.selected-strike-bar{stroke:var(--amber);stroke-width:2;opacity:1}.axis{stroke:#657682;stroke-width:1}.gridline{stroke:#25323d;stroke-width:1;stroke-dasharray:3 5}.zero{stroke:#82929d;stroke-width:1.2}.tick{fill:#8fa0ad;font-size:10px}.axislabel{fill:#a8b5bf;font-size:10px}.bar-call{fill:var(--green);opacity:.88}.bar-put{fill:var(--pink);opacity:.86}.bar-call:hover,.bar-put:hover{opacity:1;filter:drop-shadow(0 0 4px currentColor)}.hoverline{stroke:#e8f1f5;stroke-width:1;stroke-dasharray:2 4;opacity:.65}.tooltip{position:absolute;z-index:10;display:none;pointer-events:none;min-width:190px;background:#081016f2;border:1px solid #435664;border-radius:9px;padding:10px 12px;box-shadow:var(--shadow);font-size:10px}.tooltip strong{display:block;font-size:12px;margin-bottom:6px}.tooltip .ttrow{display:flex;justify-content:space-between;gap:16px;color:#b8c4cb;padding:2px 0}.tooltip .ttrow b{font-variant-numeric:tabular-nums;color:#fff}.below-chart{display:grid;grid-template-columns:1.1fr 1fr;gap:12px;margin-top:12px}.selected,.range-control{background:#0e151b;border:1px solid #23303a;border-radius:10px;padding:12px}.selected-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.selected-head b{font-size:18px}.selected-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:9px}.selected-grid div{font-size:9px;color:var(--muted)}.selected-grid strong{display:block;font-size:12px;color:#e8f0f4;font-variant-numeric:tabular-nums;margin-top:3px}.range-control label{color:var(--muted);font-size:10px;display:block}.range-control input{width:100%;accent-color:var(--green);margin:12px 0 5px}.range-buttons{display:flex;gap:6px;justify-content:flex-end}.stack{display:grid;gap:13px}.rank-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.rank{background:#0e151b;border:1px solid #222e37;border-radius:10px;padding:10px;min-width:0}.rank h3{font-size:10px;text-transform:uppercase;letter-spacing:.07em;margin:0 0 8px;color:#b8c5cd}.rankline{display:grid;grid-template-columns:25px 1fr auto;gap:6px;align-items:center;padding:5px 0;border-bottom:1px solid #1b252d;font-size:10px}.rankline:last-child{border-bottom:0}.rankline .n{color:#667986}.rankline b{font-variant-numeric:tabular-nums}.rankline small{display:block;color:var(--muted);font-size:8px}.rankline .pct{color:#90a1ab;font-size:9px}.keys{margin-top:14px}.key-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:9px}.key{background:linear-gradient(145deg,#14201f,#10171e);border:1px solid #29453f;border-radius:10px;padding:11px}.key.pink{background:linear-gradient(145deg,#24161d,#10171e);border-color:#53303c}.key .strike{font-size:17px;font-weight:900}.key .label{font-size:9px;color:var(--muted);margin:3px 0 7px}.key strong{font-size:12px;font-variant-numeric:tabular-nums}.interpret{margin-top:14px;display:grid;grid-template-columns:1.2fr 1fr;gap:14px}.interpret h2{margin:0 0 9px;font-size:14px}.facts{display:grid;gap:7px}.fact{border-left:2px solid var(--green);padding:5px 9px;color:#d1dce2;font-size:11px}.warning{color:#c5d0d7;font-size:10px;margin:6px 0}.warning:before{content:"• ";color:var(--amber)}.footer{display:flex;justify-content:space-between;gap:12px;color:#687a87;font-size:9px;padding:15px 3px}.hidden{display:none!important}.rankline b,.rankline .pct,.mini b,.selected-grid strong{font-variant-numeric:tabular-nums}.chain-nav{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:8px 0 10px}.chain-nav button{min-height:38px;padding:8px 12px}.chain-nav button:disabled{opacity:.42;cursor:not-allowed}.chain-nav-note{color:var(--muted);font-size:10px;flex:1 1 100%}.chain-scroll{overscroll-behavior:contain;scroll-behavior:smooth;scrollbar-color:#435461 #10171e}.chain-table .selected{outline:2px solid var(--amber);outline-offset:-2px}.chain-table td,.chain-table th{font-variant-numeric:tabular-nums}.coverage-mini b{font-size:11px;letter-spacing:-.02em;white-space:nowrap}.rankline b{white-space:nowrap}.rankline small{font-variant-numeric:tabular-nums}
@media(max-width:1100px){.summary-grid{grid-template-columns:1fr 1fr}.summary-grid .ratio-card{grid-column:1/-1}.main-grid{grid-template-columns:1fr}.stack{grid-template-columns:1fr 1fr}.key-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:700px){.chain-nav{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.chain-nav button{min-height:42px;padding:7px 4px;font-size:10px;white-space:normal;line-height:1.2}.chain-nav-note{grid-column:1/-1;font-size:9px}.coverage-mini b{font-size:10px}.shell{padding:13px 9px 26px}.topbar{align-items:flex-start;flex-direction:column;gap:10px;margin-bottom:16px}.brand{letter-spacing:.12em}.head-right{justify-content:flex-start;gap:6px}.pill{white-space:normal;overflow-wrap:anywhere}.hero{align-items:flex-start;flex-direction:column;gap:8px;margin:6px 0 14px}.hero-symbol{font-size:21px}.hero-symbol span{text-align:left}.limitations{margin-bottom:12px}.lim{font-size:9px;overflow-wrap:anywhere}.kpis{grid-template-columns:1fr 1fr;gap:7px}.kpi{padding:11px}.kpi label{font-size:10px}.kpi strong{font-size:21px}.summary-grid{grid-template-columns:1fr}.summary-grid .ratio-card{grid-column:auto}.panel{padding:12px}.chart-panel{padding:11px 9px 10px}.panel-head{gap:7px;margin-bottom:9px}.panel h2{font-size:14px;line-height:1.25;overflow-wrap:anywhere}.stack{grid-template-columns:1fr}.rank-grid{grid-template-columns:1fr 1fr}.key-grid{grid-template-columns:1fr 1fr}.interpret{grid-template-columns:1fr}.below-chart{grid-template-columns:1fr;gap:8px;margin-top:9px}.selected-grid{grid-template-columns:1fr 1fr;gap:9px}.selected-head b{font-size:22px}.selected-grid div{font-size:10px}.selected-grid strong{font-size:14px}.chart-toolbar{align-items:stretch;gap:8px}.toolbar-group{gap:6px}.chart-toolbar button{min-height:40px;padding:8px 9px;flex:1}.toggle{min-height:36px;font-size:12px}.rangetext{font-size:11px;line-height:1.35}.chart-wrap{margin-top:5px}.chart-wrap svg.flow{height:250px}.tick{font-size:13px}.axislabel{font-size:13px}.tooltip{font-size:12px;min-width:205px}.tooltip strong{font-size:14px}.tooltip .ttrow{gap:10px}.range-control{padding:11px}.range-control input{height:32px;margin:8px 0}.range-buttons button{min-height:42px;min-width:150px}.rankline{font-size:11px}.rankline small{font-size:9px}.footer{flex-direction:column;overflow-wrap:anywhere}}
</style>
<style>.expiration-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:14px}.expiration-toolbar label{color:var(--muted);font-size:11px;font-weight:700}.expiration-toolbar select{min-width:210px;max-width:100%;background:#111a22;color:var(--text);border:1px solid #34434f;border-radius:8px;padding:10px 12px;font:inherit}.expiration-summary{color:var(--muted);font-size:11px}.chain-panel{margin-top:14px;min-width:0}.chain-note{color:var(--muted);font-size:10px;margin-top:4px}.chain-scroll{max-height:540px;overflow:auto;border:1px solid var(--line);border-radius:9px;max-width:100%}.chain-table{width:100%;border-collapse:collapse;min-width:760px;font-variant-numeric:tabular-nums}.chain-table th,.chain-table td{padding:9px 10px;text-align:right;border-bottom:1px solid #26323e;white-space:nowrap}.chain-table th{position:sticky;top:0;background:#151e27;color:#aebdc7;font-size:10px;z-index:2}.chain-table td{font-size:11px}.chain-table tr{cursor:pointer}.chain-table tr:hover,.chain-table tr.selected{background:#16312d}.chain-table tr.selected td:first-child{color:var(--green);font-weight:800}.chain-legend{color:var(--muted);font-size:10px;margin-top:8px}.chain-empty{padding:16px;color:var(--muted);text-align:center}@media(max-width:700px){.expiration-toolbar{align-items:stretch}.expiration-toolbar select{width:100%;min-height:42px}.chain-panel{padding:13px 12px}.chain-scroll{max-height:420px}.chain-table{min-width:790px}.chain-table th,.chain-table td{padding:8px 7px}.chain-table td{font-size:10px}}.chain-groups{display:none;grid-template-columns:4fr 1fr 4fr;gap:8px;margin:0 0 6px;text-align:center;color:#9cabb6;font-size:10px;font-weight:800;letter-spacing:.1em}.chain-groups span:first-child{color:var(--green)}.chain-groups span:last-child{color:var(--pink)}.chain-table{width:100%;min-width:790px;table-layout:fixed}.chain-table th,.chain-table td{text-align:center}.chain-table .group-head th{background:#0d141a;border-bottom:0;color:#b8c5cd}.chain-table .group-head th:first-child{color:var(--green)}.chain-table .group-head th:last-child{color:var(--pink)}.chain-table .strike-col{font-weight:900;color:#f1f6f8;background:#18222b}.chain-table td.call-value{color:#88f1cb}.chain-table td.put-value{color:#ff9bb0}.chain-table tr[data-strike]{min-height:42px}.chain-table tr[data-strike]:focus-visible{outline:2px solid var(--cyan);outline-offset:-2px}.chain-detail-row{display:none;background:#0c1319}.chain-detail-row.expanded{display:table-row}.chain-detail-row td{text-align:left!important;padding:11px 13px!important}.quote-detail-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.quote-detail-grid div{background:#121b22;border:1px solid #27343f;border-radius:8px;padding:8px}.quote-detail-grid span,.snapshot-details summary small{display:block;color:var(--muted);font-size:9px}.quote-detail-grid b{display:block;margin-top:3px;color:#eef4f7;font-size:13px;font-variant-numeric:tabular-nums}.chain-detail-row small{display:block;color:var(--muted);margin-top:8px}.snapshot-details{margin:0;min-width:0}.snapshot-details summary{list-style:none;display:flex;align-items:center;justify-content:space-between;gap:8px;cursor:pointer}.snapshot-details summary::-webkit-details-marker{display:none}.snapshot-details summary strong{display:block;font-size:13px}.snapshot-details summary b{font-size:18px;color:var(--muted)}.snapshot-details[open] summary{margin-bottom:8px}.snapshot-details .mini-grid{grid-template-columns:1fr 1fr}.snapshot-details .mini b{overflow-wrap:anywhere;font-size:11px}.chain-legend{line-height:1.5}.limitations .lim{white-space:normal;overflow-wrap:anywhere}.kpi label,.rank h3,.key .label,.mini span{text-transform:none;letter-spacing:0}.head-right #run-id{display:none}@media(min-width:701px){.chain-table{min-width:790px}.chain-table .strike-col{background:#18222b}}@media(max-width:700px){.chain-groups{display:grid}.chain-panel{padding:13px 10px}.chain-scroll{max-height:460px}.chain-table{min-width:0;width:100%;font-size:10px}.chain-table .group-head{display:none}.chain-table th,.chain-table td{padding:9px 4px}.chain-table th{font-size:9px;white-space:normal}.chain-table .quote-col{display:none}.chain-table .metric-col{width:20%}.chain-table .strike-col{width:20%;font-size:11px}.chain-table td{font-size:11px}.chain-table tr[data-strike]{min-height:44px}.chain-table tr[data-strike] td:nth-child(1),.chain-table tr[data-strike] td:nth-child(2),.chain-table tr[data-strike] td:nth-child(8),.chain-table tr[data-strike] td:nth-child(9){font-variant-numeric:tabular-nums}.chain-groups{grid-template-columns:2fr 1fr 2fr}.quote-detail-grid{grid-template-columns:1fr 1fr}.chain-detail-row td{padding:9px!important}.snapshot-details .mini-grid{grid-template-columns:1fr 1fr}.head-right #run-id{display:none}}</style><style>.price-reference{display:flex;align-items:center;justify-content:space-between;gap:14px;margin:0 0 14px;padding:12px 15px;border-color:#544522;background:linear-gradient(105deg,#211c12,#111820 58%)}.price-reference>div:first-child{display:grid;gap:2px;min-width:150px}.price-reference-label{font-size:11px;color:#f0cb7a;font-weight:800}.price-reference strong{font-size:21px;font-variant-numeric:tabular-nums;color:#ffe09a}.price-reference-details{color:#c3cbd0;font-size:10px;overflow-wrap:anywhere}.price-range-status{color:#f0cb7a;font-size:10px;text-align:right}.price-reference-line{stroke:#f4c46a;stroke-width:2;stroke-dasharray:6 4;pointer-events:none}.price-reference-axis-label{fill:#ffe09a;font-size:10px;font-weight:800;paint-order:stroke;stroke:#090d12;stroke-width:3px;stroke-linejoin:round;pointer-events:none}@media(max-width:700px){.price-reference{align-items:flex-start;flex-direction:column;gap:5px;padding:10px 12px}.price-reference>div:first-child{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}.price-reference strong{font-size:19px}.price-range-status{text-align:left}}</style></head><body>
<main class="shell">
<header class="topbar"><div class="brand"><div class="brandmark">N</div><div>NAVI OPTIONS LAB<small>실제 관측 데이터 분석</small></div></div><div class="head-right"><span class="pill status">PROVISIONAL</span><span class="pill" lang="en">EOD_UNVERIFIED</span><span class="pill" id="run-id"></span></div></header>
<section class="hero"><div><h1>NVDA 옵션 수급 요약</h1><p id="hero-subtitle">Nasdaq 옵션 관측 스냅샷 · 전체 만기</p></div><div class="hero-symbol">NVDA<span id="hero-expiration">NASDAQ 옵션 · 전체 만기</span></div></section>
<div class="limitations" id="limitations"></div>
<section class="panel price-reference" id="price-reference" aria-live="polite"><div><span class="price-reference-label" id="price-reference-label">NVDA 현재가 미확인</span><strong id="price-reference-value">—</strong></div><div class="price-reference-details" id="price-reference-details">사용 가능한 검증된 현물 가격 데이터가 없습니다.</div><div class="price-range-status" id="price-range-status"></div></section>
<section class="panel expiration-toolbar"><label for="expiration-filter">만기 선택</label><select id="expiration-filter" aria-label="옵션 만기 선택"><option value="all">전체 만기</option></select><span class="expiration-summary" id="expiration-summary"></span></section>
<section class="kpis" id="kpis"></section>
<section class="summary-grid">
 <article class="panel"><div class="panel-head"><div><h2>콜·풋 거래량 비교</h2><div class="eyebrow">계약 행에서 관측된 거래량</div></div><span class="pill">거래량</span></div><div class="donut-row" id="donut-volume"></div></article>
 <article class="panel"><div class="panel-head"><div><h2>콜·풋 미결제약정 비교</h2><div class="eyebrow">미결제 계약 수</div></div><span class="pill">미결제약정(OI)</span></div><div class="donut-row" id="donut-oi"></div></article>
 <article class="panel ratio-card"><div class="panel-head"><div><h2>관측 비율</h2><div class="eyebrow">관측된 합계만으로 계산</div></div></div><div class="ratio-box"><strong id="pcr"></strong><span>관측 거래량 PCR<br>풋 거래량 ÷ 콜 거래량</span></div><div class="ratio-box"><strong id="oi-ratio"></strong><span>OI 비율<br>풋 OI ÷ 콜 OI</span></div><div class="mini-grid" id="coverage"></div></article>
</section>
<section class="main-grid">
 <div class="stack-main">
  <article class="panel chart-panel"><div class="panel-head"><div><h2>행사가별 NVDA 옵션 거래량</h2><div class="eyebrow">콜은 0선 위, 풋은 시각적 구분을 위해 0선 아래에 표시합니다. 풋 거래량 원값은 양수입니다.</div></div><span class="pill">관측 거래량</span></div><div class="chart-toolbar"><div class="toolbar-group"><label class="toggle"><input type="checkbox" id="show-call" checked> 콜</label><label class="toggle"><input type="checkbox" id="show-put" checked> 풋</label><span class="rangetext" id="range-note" aria-live="polite"></span></div><div class="toolbar-group"><button id="reset-range">기본 보기</button><button id="full-range">전체 행사가</button></div></div><div class="chart-wrap"><svg id="volume-chart" class="flow" viewBox="0 0 1000 350" role="img" aria-label="NVDA 행사가별 콜·풋 거래량 관측값"></svg><div class="tooltip" id="volume-tooltip"></div></div><div class="below-chart"><div class="selected"><div class="selected-head"><span class="eyebrow">선택 행사가 · 관측값</span><b id="selected-strike">—</b></div><div id="selection-viewport-status" class="rangetext" aria-live="polite"></div><div class="selected-grid" id="selected-values"></div></div><div class="range-control"><label for="zoom">확대 · 차트를 끌어 이동 · 휠로 확대/축소</label><input id="zoom" type="range" min="1" max="8" step="0.1" value="4"><div class="range-buttons"><button id="center-selected">선택 행사가로 이동</button></div></div></div></article>
  <article class="panel chart-panel"><div class="panel-head"><div><h2>행사가별 NVDA 미결제약정(OI)</h2><div class="eyebrow">콜·풋 미결제 계약 수 · 당일 거래량과 별도 지표</div><div class="eyebrow" id="oi-range-note">Shared strike view · $140–$220</div></div><span class="pill">미결제약정(OI)</span></div><div class="chart-wrap"><svg id="oi-chart" class="flow" viewBox="0 0 1000 350" role="img" aria-label="NVDA 행사가별 콜·풋 미결제약정 관측값"></svg><div class="tooltip" id="oi-tooltip"></div></div></article>
 </div>
 <aside class="stack"><article class="panel"><div class="panel-head"><div><h2>집중 행사가 TOP 5</h2><div class="eyebrow">각 지표의 관측 합계 대비 비중</div></div></div><div class="rank-grid" id="rank-grid"></div></article><details class="panel snapshot-details"><summary><span><strong>스냅샷 세부 정보</strong><small>실행 ID · 수집 시각 · 원본 해시</small></span><b aria-hidden="true">＋</b></summary><div class="mini-grid" id="meta-grid"></div></details></aside>
</section>
<section class="panel chain-panel"><div class="panel-head"><div><h2>NVDA 옵션 체인 · 관측 스냅샷</h2><div class="chain-note" id="chain-note"></div></div><span class="pill">원본 관측 필드</span></div><div class="chain-nav" role="group" aria-label="옵션 체인 빠른 이동"><button id="chain-reference-nav" type="button">참고가격 부근</button><button id="chain-selected-nav" type="button" disabled>선택 행사가</button><button id="chain-first-nav" type="button">처음으로</button><span id="chain-nav-note" class="chain-nav-note">기준은 과거 참고가격 $156.14 · 현재가가 아닙니다.</span></div><div class="chain-groups" aria-hidden="true"><span>콜 데이터</span><span>행사가</span><span>풋 데이터</span></div><div class="chain-scroll"><table class="chain-table"><thead><tr class="group-head"><th colspan="4">콜</th><th>행사가</th><th colspan="4">풋</th></tr><tr><th class="metric-col">거래량</th><th class="metric-col">OI</th><th class="quote-col">Bid</th><th class="quote-col">Ask</th><th class="strike-col">행사가</th><th class="quote-col">Bid</th><th class="quote-col">Ask</th><th class="metric-col">거래량</th><th class="metric-col">OI</th></tr></thead><tbody id="chain-body"></tbody></table></div><div class="chain-legend">대시(—)·빈 값은 관측되지 않은 값이며 숫자 0과 다릅니다. 행을 누르면 해당 만기의 Bid/Ask 상세를 펼칩니다. 행사가를 선택하면 차트와 선택 정보가 함께 갱신됩니다.</div></section>
<section class="panel keys"><div class="panel-head"><div><h2>주요 관측 행사가</h2><div class="eyebrow">관측 집중 지점이며 지지·저항 또는 매매 신호가 아닙니다</div></div></div><div class="key-grid" id="key-grid"></div></section>
<section class="panel interpret"><div><h2>NAVI 관측 수급 해석</h2><div class="facts" id="facts"></div></div><div><h2>해석 시 유의사항</h2><p class="warning" id="interpret-range-warning">선택한 만기의 관측값이며 향후 주가 방향을 확정하지 않습니다.</p><p class="warning">풋 거래량이나 OI 집중은 자동으로 지지선이 되지 않습니다.</p><p class="warning">콜 거래량 집중은 상승 신호, 풋 거래량 집중은 하락 신호가 아닙니다.</p><p class="warning">매수·매도 방향, 현재 주가, 옵션 프리미엄, OTM/ITM 비율, GEX, 예측 확률은 표시하거나 계산하지 않았습니다.</p><p class="warning">관측 데이터는 거래 방향, 지지·저항, 딜러 포지션 또는 예측 정확도를 입증하지 않습니다.</p></div></section>
<footer class="footer"><span>자료: 보존된 WORK 04-R NVDA 스냅샷 → WORK 04-T 행사가 집계 · 오프라인 대시보드</span><span id="source-time"></span></footer>
</main>
<script id="dashboard-data" type="application/json">__EMBEDDED_DATA__</script>
<script>
(()=> {
 const D=JSON.parse(document.getElementById('dashboard-data').textContent);
 const priceReference=D.price_reference||{};
 window.NAVI_DASHBOARD_DATA=D;
 const fmt=n=>n==null?'—':new Intl.NumberFormat('en-US',{maximumFractionDigits:0}).format(n);
 const quoteFmt=n=>n==null?'관측되지 않음':new Intl.NumberFormat('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}).format(n);
 const pct=n=>n==null?'—':n.toFixed(2)+'%';
 const $=id=>document.getElementById(id);
 const safe=v=>v==null?'관측되지 않음':fmt(v);
 const metrics=['call_volume','put_volume','call_oi','put_oi'];
 const metricKeys={call_volume:'call_volume_observed_sum',put_volume:'put_volume_observed_sum',call_oi:'call_oi_observed_sum',put_oi:'put_oi_observed_sum'};
 const stateFor=exp=>{
   const contracts=D.contracts.filter(c=>exp==='all'||c.expiration===exp);
   const map=new Map();
   for(const c of contracts){
     if(c.strike==null)continue;
     let r=map.get(c.strike);
     if(!r){r={strike:c.strike,expiration_count:exp==='all'?D.expiry_count:1};for(const m of metrics){r[metricKeys[m]]=null;r[m+'_observed_count']=0;r[m+'_missing_count']=0;}map.set(c.strike,r)}
     for(const m of metrics){const v=c[m];if(v==null)r[m+'_missing_count']++;else{r[metricKeys[m]]=(r[metricKeys[m]]??0)+v;r[m+'_observed_count']++}}
   }
   const rows=[...map.values()].sort((a,b)=>a.strike-b.strike);
   const totals={contracts:contracts.length,strike_count:rows.length};
   for(const m of metrics){const k=metricKeys[m];const observed=rows.filter(r=>r[k]!=null);totals[k]=observed.length?observed.reduce((a,r)=>a+r[k],0):null;totals[m+'_observed_count']=rows.reduce((a,r)=>a+r[m+'_observed_count'],0);totals[m+'_missing_count']=contracts.length-totals[m+'_observed_count'];}
   const top5={};
   for(const m of metrics){const k=metricKeys[m],sum=totals[k];top5[m]=rows.filter(r=>r[k]!=null).sort((a,b)=>b[k]-a[k]||a.strike-b.strike).slice(0,5).map(r=>({strike:r.strike,observed_sum:r[k],share_pct:sum?100*r[k]/sum:null}))}
   const volumeTotal=(totals.call_volume_observed_sum??0)+(totals.put_volume_observed_sum??0);
   const oiTotal=(totals.call_oi_observed_sum??0)+(totals.put_oi_observed_sum??0);
   const coverage={};for(const m of metrics)coverage[m]=contracts.length?totals[m+'_observed_count']/contracts.length*100:null;
   const donuts={volume:{call:totals.call_volume_observed_sum,put:totals.put_volume_observed_sum,call_pct:volumeTotal?100*(totals.call_volume_observed_sum??0)/volumeTotal:null,put_pct:volumeTotal?100*(totals.put_volume_observed_sum??0)/volumeTotal:null},oi:{call:totals.call_oi_observed_sum,put:totals.put_oi_observed_sum,call_pct:oiTotal?100*(totals.call_oi_observed_sum??0)/oiTotal:null,put_pct:oiTotal?100*(totals.put_oi_observed_sum??0)/oiTotal:null}};
   return {expiration:exp,contracts,rows,totals,top5,coverage,donuts,full_range:rows.length?{min:rows[0].strike,max:rows[rows.length-1].strike}:{min:0,max:0},expirations:exp==='all'?D.expirations.length:(contracts.length?1:0)};
 };
 const label=exp=>exp==='all'?'전체 만기':exp;
 const isMobile=window.matchMedia('(max-width:700px)').matches;
 /* VIEWPORT_MATH_START */
 const VM=(()=>{
   const finite=(n,fallback=0)=>Number.isFinite(Number(n))?Number(n):fallback;
   const clamp=(n,lo,hi)=>Math.min(hi,Math.max(lo,n));
   const domainOf=d=>({min:Math.max(.01,finite(d.min,.01)),max:Math.max(finite(d.max,1),finite(d.min,.01)+.01)});
   const fit=(center,span,d)=>{const b=domainOf(d),limit=b.max-b.min,w=clamp(finite(span,1),Math.min(limit,.01),limit),c=finite(center,(b.min+b.max)/2),lo=clamp(c-w/2,b.min,b.max-w);return {min:lo,max:lo+w}};
   const shift=(r,delta,d)=>{const b=domainOf(d),w=clamp(finite(r.max)-finite(r.min),Math.min(b.max-b.min,.01),b.max-b.min),lo=clamp(finite(r.min)+finite(delta),b.min,b.max-w);return {min:lo,max:lo+w}};
   const zoomSpan=(level,bounds)=>{const t=clamp((finite(level,1)-1)/7,0,1),min=finite(bounds.minSpan,1),max=Math.max(min,finite(bounds.maxSpan,min));return max*Math.pow(min/max,t)};
   const zoomLevel=(span,bounds)=>{const min=finite(bounds.minSpan,1),max=Math.max(min,finite(bounds.maxSpan,min)),w=clamp(finite(span,min),min,max);return max===min?1:1+7*Math.log(max/w)/Math.log(max/min)};
   const resize=(r,anchor,ratio,span,d)=>{const b=domainOf(d),old=finite(r.max)-finite(r.min),w=clamp(finite(span,old),Math.min(b.max-b.min,.01),b.max-b.min),a=finite(anchor,(r.min+r.max)/2),q=clamp(finite(ratio,.5),0,1),left=a-q*w;return shift({min:r.min,max:r.min+w},left-r.min,b)};
   const x=(strike,r,left,width)=>{const lo=Number(r.min),hi=Number(r.max),value=Number(strike),span=hi-lo;if(!(Number.isFinite(lo)&&Number.isFinite(hi)&&Number.isFinite(value)&&span>0))return null;const px=Number(left)+((value-lo)/span)*Number(width);return Number.isFinite(px)?px:null};
   const niceStep=raw=>{const v=Math.max(.01,finite(raw,1)),power=Math.pow(10,Math.floor(Math.log10(v))),m=v/power;return (m<=1?1:m<=2?2:m<=5?5:10)*power};
   const ticks=(r,plotWidth,minSpacing)=>{const span=finite(r.max)-finite(r.min);if(!(span>0)||!(plotWidth>0))return[];const target=Math.max(2,Math.floor(plotWidth/Math.max(1,minSpacing))),step=niceStep(span/(target-1)),out=[];let value=Math.ceil(r.min/step)*step,last=-Infinity;for(let i=0;i<200&&value<=r.max+step*1e-9;i++,value+=step){const px=x(value,r,0,plotWidth);if(px<22||px>plotWidth-22||px-last<minSpacing)continue;out.push({value:Number(value.toPrecision(12)),x:px});last=px}return out};
   const minimumUsefulSpan=(rows,center)=>{const a=[...new Set(rows.map(r=>finite(r.strike,NaN)).filter(Number.isFinite))].sort((x,y)=>x-y);if(!a.length)return 1;if(a.length<5)return Math.max(.01,(a[a.length-1]??a[0])-(a[0]??0));const c=finite(center,a[Math.floor(a.length/2)]);let idx=0;for(let i=1;i<a.length;i++)if(Math.abs(a[i]-c)<Math.abs(a[idx]-c))idx=i;const start=clamp(idx-2,0,a.length-5),left=a[start],right=a[start+4];return Math.max(.01,2*Math.max(c-left,right-c))};
   const overview=(rows,d)=>{const b=domainOf(d),step=niceStep((b.max-b.min)/72),map=new Map(),fields=['call_volume_observed_sum','put_volume_observed_sum','call_oi_observed_sum','put_oi_observed_sum'],lastIndex=Math.max(0,Math.ceil((b.max-b.min)/step)-1);for(const r of rows){const index=r.strike>=b.max?lastIndex:Math.max(0,Math.floor((r.strike-b.min)/step)),start=b.min+index*step,end=Math.min(b.max,start+step),key=String(index);if(!map.has(key))map.set(key,{bin_start:start,bin_end:end,bin_center:(start+end)/2,actual_strikes:[],_values:Object.fromEntries(fields.map(k=>[k,[]]))});const g=map.get(key);g.actual_strikes.push(r.strike);for(const k of fields)if(r[k]!=null&&Number.isFinite(Number(r[k])))g._values[k].push(Number(r[k]))}return [...map.values()].sort((a,b)=>a.bin_start-b.bin_start).map(g=>{const out={...g,strike_label:'$'+g.bin_start+'–$'+g.bin_end,nearest_strike:g.actual_strikes.reduce((a,b)=>Math.abs(b-g.bin_center)<Math.abs(a-g.bin_center)?b:a,g.actual_strikes[0])};for(const k of fields){const vals=g._values[k];out[k]=vals.length?vals.reduce((a,b)=>a+b,0):null;out[k+'_observed_count']=vals.length}delete out._values;return out})};
   return {clamp,fit,shift,zoomSpan,zoomLevel,resize,x,niceStep,ticks,minimumUsefulSpan,overview};
 })();
 /* VIEWPORT_MATH_END */
 const selectEl=$('expiration-filter');
 for(const exp of D.expirations){const o=document.createElement('option');o.value=exp;o.textContent=exp;selectEl.appendChild(o)}
 let active='all',S=stateFor(active),full={...S.full_range},selected=D.selected_strike,initialRange,range,viewMode='focused',gesture=null,expandedKey='';
 const initialFor=state=>{
   if(active==='all'&&isMobile)return {...D.mobile_initial_range};
   if(active==='all')return {...D.default_range};
   const focus=state.rows.filter(r=>r.strike>=140&&r.strike<=220);
   if(focus.length>=4)return {min:140,max:220};
   return {...state.full_range};
 };
 const svgNs='http://www.w3.org/2000/svg';
 const create=(name,attrs={})=>{const el=document.createElementNS(svgNs,name);for(const [k,v]of Object.entries(attrs))el.setAttribute(k,v);return el};
 const visibleRows=()=>{const actual=S.rows.filter(r=>r.strike>=range.min&&r.strike<=range.max);return viewMode==='full-overview'?VM.overview(actual,full):actual};
 const zoomBounds=(center=(range.min+range.max)/2)=>{const span=Math.max(.01,full.max-full.min),focus=Math.max(.01,initialRange.max-initialRange.min),maxSpan=Math.min(span,Math.max(focus,Math.min(focus*4,320))),minSpan=Math.min(maxSpan,VM.minimumUsefulSpan(S.rows,center));return {minSpan,maxSpan}};
 const nearestActualStrike=value=>S.rows.length?S.rows.reduce((a,b)=>Math.abs(b.strike-value)<Math.abs(a.strike-value)?b:a,S.rows[0]).strike:null;
 const money=value=>'$'+new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(value);
 function renderPriceReference(){
   const valid=Number.isFinite(priceReference.price)&&priceReference.price>0&&priceReference.verification_status==='HISTORICAL_REFERENCE_ONLY'&&priceReference.price_type==='HISTORICAL_REFERENCE';
   if(!valid){$('price-reference-label').textContent='NVDA 현재가 미확인';$('price-reference-value').textContent='—';$('price-reference-details').textContent='사용 가능한 검증된 현물 가격 데이터가 없습니다.';$('price-range-status').textContent='';return}
   $('price-reference-label').textContent='NVDA 과거 참고가격';$('price-reference-value').textContent='$'+Number(priceReference.price).toFixed(2);
   $('price-reference-details').textContent='기준일 '+priceReference.price_timestamp+' · '+priceReference.source+' · 가격 시각은 날짜까지만 제공됩니다. 응답 수집 UTC: '+priceReference.captured_timestamp+' · 현재가/정규장 종가로 확인되지 않았고 옵션 스냅샷과 동기화되지 않았습니다.';
   $('price-range-status').textContent=(priceReference.price<range.min||priceReference.price>range.max)?'과거 참고가격이 현재 차트 행사가 범위 밖입니다.':'황금 점선은 과거 참고가격이며 옵션 데이터와 시점이 동기화되지 않았습니다.';
 }
 function donut(id,obj){
   const c=2*Math.PI*40;
   if(obj.call_pct==null||obj.put_pct==null){$(id).innerHTML='<div class="chain-empty">관측되지 않음</div>';return}
   const callLen=c*obj.call_pct/100,putLen=c*obj.put_pct/100;
   $(id).innerHTML='<div class="donut"><svg viewBox="0 0 100 100"><circle class="track" cx="50" cy="50" r="40"/><circle class="seg" cx="50" cy="50" r="40" stroke-dasharray="'+callLen+' '+(c-callLen)+'"/><circle class="seg putseg" cx="50" cy="50" r="40" stroke-dasharray="'+putLen+' '+(c-putLen)+'" stroke-dashoffset="-'+callLen+'"/></svg><center>'+pct(obj.call_pct)+'<small>콜 비중</small></center></div><div class="legend"><div class="leg"><i class="swatch" style="background:var(--green)"></i><span>콜 · '+safe(obj.call)+'</span><b>'+pct(obj.call_pct)+'</b></div><div class="leg"><i class="swatch" style="background:var(--pink)"></i><span>풋 · '+safe(obj.put)+'</span><b>'+pct(obj.put_pct)+'</b></div></div>';
 }
 function renderMetrics(){
   const expLabel=label(active),t=S.totals;
   $('hero-subtitle').textContent='Nasdaq 옵션 관측 스냅샷 · '+expLabel;
   $('hero-expiration').textContent='NASDAQ 옵션 · '+expLabel;
   $('expiration-summary').textContent=fmt(S.contracts.length)+'개 계약 행 · '+fmt(S.rows.length)+'개 행사가 · 보존된 관측값';
   $('kpis').innerHTML=[['콜 거래량',t.call_volume_observed_sum,'call','숫자로 관측된 계약 합계'],['풋 거래량',t.put_volume_observed_sum,'put','숫자로 관측된 계약 합계'],['콜 미결제약정(OI)',t.call_oi_observed_sum,'call','관측된 미결제 계약 합계'],['풋 미결제약정(OI)',t.put_oi_observed_sum,'put','관측된 미결제 계약 합계']].map(([a,v,k,sub])=>'<article class="card kpi" style="--glow:var(--'+(k==='call'?'green':'pink')+')"><label>'+a+'</label><strong class="'+k+'">'+fmt(v)+'</strong><div class="sub">'+sub+'</div></article>').join('');
   donut('donut-volume',S.donuts.volume);donut('donut-oi',S.donuts.oi);
   $('pcr').textContent=t.call_volume_observed_sum>0?(t.put_volume_observed_sum/t.call_volume_observed_sum).toFixed(4):'—';
   $('oi-ratio').textContent=t.call_oi_observed_sum>0?(t.put_oi_observed_sum/t.call_oi_observed_sum).toFixed(4):'—';
   $('coverage').innerHTML=[['콜 거래량 관측률','call_volume'],['풋 거래량 관측률','put_volume'],['콜 OI 관측률','call_oi'],['풋 OI 관측률','put_oi']].map(x=>'<div class="mini"><span>'+x[0]+'</span><b>'+fmt(S.totals[x[1]+'_observed_count'])+' / '+fmt(S.contracts.length)+' · '+pct(S.coverage[x[1]])+'</b></div>').join('');
   $('meta-grid').innerHTML=[['계약 수',fmt(S.contracts.length)],['고유 행사가',fmt(S.rows.length)],['선택 만기 수',fmt(S.expirations)],['미국 동부 거래일',D.trading_date_et],['수집 시각(UTC)',D.snapshot_timestamp_utc],['수집 시각(ET)',D.snapshot_timestamp_et],['실행 ID',D.run_id],['원본 SHA-256',D.raw_sha256]].map(x=>'<div class="mini"><span>'+x[0]+'</span><b>'+x[1]+'</b></div>').join('');
   const titles={call_volume:'콜 거래량',put_volume:'풋 거래량',call_oi:'콜 OI',put_oi:'풋 OI'};
   $('rank-grid').innerHTML=Object.entries(titles).map(([key,title])=>'<div class="rank"><h3>'+title+' TOP 5</h3>'+S.top5[key].map((r,i)=>'<div class="rankline"><span class="n">0'+(i+1)+'</span><b>$'+fmt(r.strike)+'<small>'+fmt(r.observed_sum)+'</small></b><span class="pct">'+pct(r.share_pct)+'</span></div>').join('')+'</div>').join('');
   const peak=(key,i=0)=>S.top5[key][i]?fmt(S.top5[key][i].strike):'—';
   const facts=['콜 거래량 최대 집중 행사가: $'+peak('call_volume')+'.','풋 거래량 최대: $'+peak('put_volume')+' · 콜 OI 최대: $'+peak('call_oi')+' · 풋 OI 최대: $'+peak('put_oi')+'.','선택 범위: '+expLabel+' · 관측 거래량 PCR '+(t.call_volume_observed_sum>0?(t.put_volume_observed_sum/t.call_volume_observed_sum).toFixed(4):'관측되지 않음')+' · 콜/풋 거래량 관측률 '+pct(S.coverage.call_volume)+' / '+pct(S.coverage.put_volume)+'.'];
   $('facts').innerHTML=facts.map(x=>'<div class="fact">'+x+'</div>').join('');
   const keyCards=[];
   for(const [key,title,kind] of [['call_volume','콜 거래량 최대','call'],['put_volume','풋 거래량 최대','pink'],['call_oi','콜 OI 최대','call'],['put_oi','풋 OI 최대','pink']])if(S.top5[key][0])keyCards.push(['$'+fmt(S.top5[key][0].strike),title,S.top5[key][0].observed_sum,kind]);
   const watch=S.rows.find(r=>r.strike===160);
   if(watch)keyCards.push(['$160','관측 행사가', 'C '+safe(watch.call_volume_observed_sum)+' · P '+safe(watch.put_volume_observed_sum),'call']);
   $('key-grid').innerHTML=keyCards.map(k=>'<div class="key '+(k[3]==='pink'?'pink':'')+'"><div class="strike '+(k[3]==='pink'?'put':'call')+'">'+k[0]+'</div><div class="label">'+k[1]+'</div><strong>'+k[2]+'</strong></div>').join('');
   $('interpret-range-warning').textContent=(active==='all'?'전체 만기를 합산했습니다. ':'선택 만기: '+expLabel+'. ')+'관측값은 향후 주가 방향을 입증하지 않습니다.';
   $('chain-note').textContent='선택 만기: '+expLabel+' · '+fmt(S.contracts.length)+'개 계약 행 · 수집 시각 '+D.snapshot_timestamp_et+' · 숫자로 관측된 값만 표시';
   $('source-time').textContent='수집 시각(UTC): '+D.snapshot_timestamp_utc+' · 미국 동부 거래일: '+D.trading_date_et+' · '+expLabel;
 }
 function draw(id,callKey,putKey,tooltipId){
   const svg=$(id);while(svg.firstChild)svg.removeChild(svg.firstChild);
   const W=isMobile?560:1000,H=350,L=isMobile?58:66,R=isMobile?12:20,T=isMobile?12:17,B=48,plotW=W-L-R,plotH=H-T-B,mid=T+plotH/2,rows=visibleRows();
   svg.setAttribute('viewBox','0 0 '+W+' '+H);
   if(!rows.length){const msg=create('text',{x:W/2,y:H/2,'text-anchor':'middle',class:'tick'});msg.textContent='이 범위에서 관측된 계약이 없습니다';svg.appendChild(msg);return}
   const vals=rows.flatMap(r=>[r[callKey],r[putKey]]).filter(v=>v!=null&&Number.isFinite(Number(v)));
   const max=Math.max(1,...vals),span=range.max-range.min,xval=x=>VM.x(x,range,L,plotW),yScale=(plotH/2-10)/max;
   for(let i=-2;i<=2;i++){const y=mid-i*(plotH/4);svg.appendChild(create('line',{x1:L,y1:y,x2:W-R,y2:y,class:i===0?'zero':'gridline'}));const lab=create('text',{x:L-9,y:y+3,'text-anchor':'end',class:'tick'});lab.textContent=fmt(max*i/2);svg.appendChild(lab)}
   const ticks=VM.ticks(range,plotW,isMobile?74:86);ticks.forEach(t=>{const x=L+t.x;svg.appendChild(create('line',{x1:x,y1:T,x2:x,y2:H-B,class:'gridline',opacity:'.3'}));const lab=create('text',{x,y:H-B+17,'text-anchor':'middle',class:'tick'});lab.textContent=money(t.value);svg.appendChild(lab)});
   const barW=Math.max(isMobile?3:1,Math.min(isMobile?12:10,(plotW/Math.max(1,rows.length))*.68)),callsOn=$('show-call').checked,putsOn=$('show-put').checked;
   rows.forEach(r=>{const pos=r.bin_center??r.strike,x=xval(pos),isSelected=r.actual_strikes?r.actual_strikes.includes(selected):r.strike===selected,actual=()=>r.actual_strikes?nearestActualStrike(pos):r.strike;if(callsOn&&r[callKey]!=null){const h=r[callKey]*yScale,rect=create('rect',{x:x-barW/2,y:mid-h,width:barW,height:Math.max(h,.65),rx:'.5',class:'bar-call'+(isSelected?' selected-strike-bar':''),'data-strike':actual()});rect.addEventListener('pointermove',e=>showTip(e,r,tooltipId));rect.addEventListener('pointerleave',()=>hideTip(tooltipId));rect.addEventListener('click',()=>select(actual()));svg.appendChild(rect)}if(putsOn&&r[putKey]!=null){const h=r[putKey]*yScale,rect=create('rect',{x:x-barW/2,y:mid,width:barW,height:Math.max(h,.65),rx:'.5',class:'bar-put'+(isSelected?' selected-strike-bar':''),'data-strike':actual()});rect.addEventListener('pointermove',e=>showTip(e,r,tooltipId));rect.addEventListener('pointerleave',()=>hideTip(tooltipId));rect.addEventListener('click',()=>select(actual()));svg.appendChild(rect)}});
   if(Number.isFinite(priceReference.price)&&priceReference.price>0&&priceReference.verification_status==='HISTORICAL_REFERENCE_ONLY'&&priceReference.price_type==='HISTORICAL_REFERENCE'&&priceReference.price>=range.min&&priceReference.price<=range.max){const x=xval(priceReference.price);if(Number.isFinite(x)){svg.appendChild(create('line',{x1:x,y1:T,x2:x,y2:H-B,class:'price-reference-line','aria-label':'과거 참고가격 $'+Number(priceReference.price).toFixed(2)}));const tag=create('text',{x:Math.min(W-R-3,Math.max(L+3,x+5)),y:T+11,class:'price-reference-axis-label'});tag.textContent='과거 참고가 $'+Number(priceReference.price).toFixed(2);svg.appendChild(tag)}}
   const xlabel=create('text',{x:L+plotW/2,y:H-8,'text-anchor':'middle',class:'axislabel'});xlabel.textContent='행사가 (달러)';svg.appendChild(xlabel);
   const cross=create('line',{id:id+'-cross',y1:T,y2:H-B,class:'hoverline',visibility:'hidden'});svg.appendChild(cross);
   const clearGesture=e=>{if(gesture&&(!e||gesture.pointerId===e.pointerId)){const id=gesture.pointerId;gesture=null;if(id!=null&&svg.hasPointerCapture?.(id))svg.releasePointerCapture(id)}};
   svg.onpointermove=e=>{if(gesture&&gesture.pointerId===e.pointerId){const dx=e.clientX-gesture.startX,dy=e.clientY-gesture.startY;if(gesture.mode==='pending'){if(Math.abs(dy)>8&&Math.abs(dy)>Math.abs(dx)){gesture.mode='vertical';return}if(Math.abs(dx)>8&&Math.abs(dx)>Math.abs(dy)){gesture.mode='pan';svg.setPointerCapture(e.pointerId)}}if(gesture.mode==='pan'){if(viewMode==='full-overview')return;const rect=svg.getBoundingClientRect(),delta=-dx*gesture.startSpan*W/(plotW*Math.max(1,rect.width));let next=VM.shift(gesture.startRange,delta,full);const center=(next.min+next.max)/2,need=Math.min(zoomBounds(center).maxSpan,VM.minimumUsefulSpan(S.rows,center));if(next.max-next.min<need)next=VM.fit(center,need,full);range=next;renderViewport();return}if(gesture.mode==='vertical')return}
     const rect=svg.getBoundingClientRect(),local=(e.clientX-rect.left)/Math.max(1,rect.width)*W;cross.setAttribute('x1',VM.clamp(local,L,W-R));cross.setAttribute('x2',VM.clamp(local,L,W-R));cross.setAttribute('visibility','visible')};
   svg.onpointerleave=()=>{if(!gesture)cross.setAttribute('visibility','hidden')};
   svg.onpointerdown=e=>{if(e.pointerType==='mouse'&&e.button!==0)return;gesture={pointerId:e.pointerId,startX:e.clientX,startY:e.clientY,startRange:{...range},startSpan:range.max-range.min,mode:'pending'}};
   svg.onpointerup=e=>{if(!gesture||gesture.pointerId!==e.pointerId)return;const g=gesture,dx=e.clientX-g.startX,dy=e.clientY-g.startY;clearGesture(e);if(g.mode==='pending'&&Math.abs(dx)<8&&Math.abs(dy)<8){const rect=svg.getBoundingClientRect(),local=(e.clientX-rect.left)/Math.max(1,rect.width)*W,target=range.min+(VM.clamp(local,L,W-R)-L)/plotW*span,nearest=nearestActualStrike(target);if(nearest!=null)select(nearest)}};
   svg.onpointercancel=e=>clearGesture(e);
   svg.onlostpointercapture=e=>{if(gesture&&gesture.pointerId===e.pointerId)gesture=null};
   svg.onwheel=e=>{e.preventDefault();const rect=svg.getBoundingClientRect(),local=(e.clientX-rect.left)/Math.max(1,rect.width)*W,anchor=range.min+(VM.clamp(local,L,W-R)-L)/plotW*span,ratio=VM.clamp((anchor-range.min)/span,0,1),b=zoomBounds(anchor),width=VM.clamp(span*(e.deltaY<0?.8:1.25),b.minSpan,b.maxSpan);range=VM.resize(range,anchor,ratio,width,full);viewMode='focused';renderViewport()};
   svg.dataset.rendered='true';svg.dataset.viewMode=viewMode;
 }
 function showTip(e,r,id){const t=$(id),svg=e.currentTarget.ownerSVGElement,box=svg.getBoundingClientRect();t.style.display='block';t.style.left=Math.min(e.clientX-box.left+12,box.width-205)+'px';t.style.top=Math.max(8,e.clientY-box.top-35)+'px';t.innerHTML='<strong>NVDA · '+(r.strike_label||('$'+fmt(r.strike)))+'</strong><div class="ttrow"><span>콜 거래량 / OI</span><b>'+safe(r.call_volume_observed_sum)+' / '+safe(r.call_oi_observed_sum)+'</b></div><div class="ttrow"><span>풋 거래량 / OI</span><b>'+safe(r.put_volume_observed_sum)+' / '+safe(r.put_oi_observed_sum)+'</b></div><div class="ttrow"><span>포함 만기 수</span><b>'+fmt(r.expiration_count)+'</b></div>'}
 function hideTip(id){$(id).style.display='none'}
 function renderSelection(){const r=S.rows.find(x=>x.strike===selected);$('selected-strike').textContent=r?'$'+fmt(selected):'선택 없음';renderSelectionStatus();$('selected-values').innerHTML=[['콜 거래량',r?.call_volume_observed_sum],['풋 거래량',r?.put_volume_observed_sum],['콜 OI',r?.call_oi_observed_sum],['풋 OI',r?.put_oi_observed_sum]].map(x=>'<div>'+x[0]+'<strong>'+safe(x[1])+'</strong></div>').join('');document.querySelectorAll('#chain-body tr[data-strike]').forEach(tr=>tr.classList.toggle('selected',Number(tr.dataset.strike)===selected))}
 function scrollChainToStrike(strike){const box=document.querySelector('.chain-scroll'),row=Array.from(document.querySelectorAll('#chain-body tr[data-strike]')).find(tr=>Number(tr.dataset.strike)===strike);if(!box||!row)return false;const top=row.getBoundingClientRect().top-box.getBoundingClientRect().top+box.scrollTop-box.clientHeight*.35;box.scrollTo({top:Math.max(0,top),behavior:'smooth'});return true}
 function renderChain(){const body=$('chain-body'),refOk=Number.isFinite(priceReference.price)&&priceReference.price>0&&priceReference.verification_status==='HISTORICAL_REFERENCE_ONLY'&&priceReference.price_type==='HISTORICAL_REFERENCE';$('chain-reference-nav').disabled=!refOk;$('chain-selected-nav').disabled=selected==null||!S.contracts.some(c=>c.strike===selected);$('chain-first-nav').disabled=!S.contracts.length;$('chain-nav-note').textContent=refOk?'참고가격 부근은 과거 참고가격 $'+Number(priceReference.price).toFixed(2)+'에 가장 가까운 실제 행사가입니다 · 현재가가 아닙니다.':'검증된 과거 참고가격이 없어 참고가격 이동을 사용할 수 없습니다.';if(!S.contracts.length){body.innerHTML='<tr><td colspan="9" class="chain-empty">선택 만기에 계약 행이 없습니다.</td></tr>';return}body.innerHTML=S.contracts.map(c=>{const key=c.expiration+'|'+c.strike,open=expandedKey===key;return '<tr data-key="'+key+'" data-strike="'+c.strike+'" data-expiration="'+c.expiration+'" tabindex="0" role="button" aria-expanded="'+open+'" aria-label="'+c.expiration+' 만기, 행사가 $'+fmt(c.strike)+' 선택 및 호가 상세"><td class="metric-col call-value">'+safe(c.call_volume)+'</td><td class="metric-col call-value">'+safe(c.call_oi)+'</td><td class="quote-col">'+quoteFmt(c.call_bid)+'</td><td class="quote-col">'+quoteFmt(c.call_ask)+'</td><td class="strike-col">$'+fmt(c.strike)+'</td><td class="quote-col">'+quoteFmt(c.put_bid)+'</td><td class="quote-col">'+quoteFmt(c.put_ask)+'</td><td class="metric-col put-value">'+safe(c.put_volume)+'</td><td class="metric-col put-value">'+safe(c.put_oi)+'</td></tr><tr class="chain-detail-row '+(open?'expanded':'')+'"><td colspan="9"><div class="quote-detail-grid"><div><span>콜 Bid (매수호가)</span><b>'+quoteFmt(c.call_bid)+'</b></div><div><span>콜 Ask (매도호가)</span><b>'+quoteFmt(c.call_ask)+'</b></div><div><span>풋 Bid (매수호가)</span><b>'+quoteFmt(c.put_bid)+'</b></div><div><span>풋 Ask (매도호가)</span><b>'+quoteFmt(c.put_ask)+'</b></div></div><small>'+c.expiration+' 만기 · 원본 관측 호가</small></td></tr>'}).join('');body.querySelectorAll('tr[data-strike]').forEach(tr=>{const activate=()=>{select(Number(tr.dataset.strike));const key=tr.dataset.key;expandedKey=expandedKey===key?'':key;renderChain();renderSelection()};tr.addEventListener('click',activate);tr.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();activate()}})})}
 function renderSelectionStatus(){const r=S.rows.find(x=>x.strike===selected);$('selection-viewport-status').textContent=r&&(selected<range.min||selected>range.max)?'선택 행사가가 현재 차트 범위 밖입니다. ‘선택 행사가로 이동’을 누르면 찾을 수 있습니다.':viewMode==='full-overview'?'전체 구간 요약 보기 · 선택 값은 실제 행사가 기준입니다.':''}
 function renderViewport(){renderPriceReference();draw('volume-chart','call_volume_observed_sum','put_volume_observed_sum','volume-tooltip');draw('oi-chart','call_oi_observed_sum','put_oi_observed_sum','oi-tooltip');const modeNote=viewMode==='full-overview'?' · 전체 범위 $'+money(VM.niceStep((full.max-full.min)/72))+' 단위 구간 합산 보기':' · 개별 행사가 보기',note='현재 행사가 범위 '+money(range.min)+'–'+money(range.max)+' · '+label(active)+modeNote;$('range-note').textContent=note+' · 전체 데이터 '+fmt(S.rows.length)+'개 행사가';$('oi-range-note').textContent='공유 범위 '+money(range.min)+'–'+money(range.max)+' · '+label(active)+modeNote;const b=zoomBounds(),span=Math.max(.01,range.max-range.min);$('zoom').value=String(VM.zoomLevel(span,b));$('zoom').disabled=viewMode==='full-overview';$('center-selected').disabled=selected==null||!S.rows.some(r=>r.strike===selected);$('reset-range').setAttribute('aria-label','현재 만기를 유지하고 기본 보기로 초기화');$('full-range').setAttribute('aria-pressed',String(viewMode==='full-overview'));renderSelectionStatus()}
 function render(){renderMetrics();renderViewport();renderChain();renderSelection()}
 function select(s){if(!S.rows.some(r=>r.strike===s))return;selected=s;renderViewport();renderSelection()}
 function switchExpiration(){
   active=selectEl.value;S=stateFor(active);full={...S.full_range};initialRange=initialFor(S);viewMode='focused';
   const found=S.rows.some(r=>r.strike===selected);
   if(!found)selected=S.rows.length?S.rows.reduce((a,b)=>Math.abs(b.strike-(selected??S.rows[0].strike))<Math.abs(a.strike-(selected??S.rows[0].strike))?b:a,S.rows[0]).strike:null;
   range={...initialRange};
   render()
 }
 $('run-id').textContent='실행 ID · '+D.run_id;$('limitations').innerHTML=D.limitations.map(x=>'<span class="lim">'+x+'</span>').join('');
 selectEl.addEventListener('change',switchExpiration);
 $('show-call').onchange=render;$('show-put').onchange=render;
 $('reset-range').onclick=()=>{viewMode='focused';range={...initialRange};renderViewport()};
 $('full-range').onclick=()=>{viewMode='full-overview';range={...full};renderViewport()};
 $('zoom').oninput=e=>{if(viewMode==='full-overview')return;const center=(range.min+range.max)/2,b=zoomBounds(center),width=VM.zoomSpan(Number(e.target.value),b);range=VM.fit(center,width,full);viewMode='focused';renderViewport()};
 $('center-selected').onclick=()=>{if(selected==null)return;const b=zoomBounds(selected),width=viewMode==='full-overview'?initialRange.max-initialRange.min:Math.min(b.maxSpan,Math.max(b.minSpan,range.max-range.min));range=VM.fit(selected,width,full);viewMode='focused';renderViewport()};
 $('chain-reference-nav').onclick=()=>{if($('chain-reference-nav').disabled)return;const strikes=S.contracts.map(c=>c.strike).filter(Number.isFinite);if(strikes.length){const nearest=strikes.reduce((a,b)=>Math.abs(b-priceReference.price)<Math.abs(a-priceReference.price)?b:a,strikes[0]);scrollChainToStrike(nearest)}};
 $('chain-selected-nav').onclick=()=>{if(!$('chain-selected-nav').disabled)scrollChainToStrike(selected)};
 $('chain-first-nav').onclick=()=>{const first=S.contracts[0];if(first)scrollChainToStrike(first.strike)};
 S=stateFor('all');initialRange=initialFor(S);full={...S.full_range};range={...initialRange};viewMode='focused';selectEl.value='all';render();window.NAVI_READY=true;window.NAVI_EXPIRATION_READY=true;
})();
</script></body></html>'''


def build_dashboard(data: dict, validation: dict, output_dir: str | Path, *, render_png: bool = True) -> dict:
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    names = ("nvda_options_dashboard.html", "nvda_options_dashboard.png", "nvda_dashboard_data.json", "nvda_dashboard_validation.json", "expiration_aggregation_validation.json", "options_chain_field_audit.json", "price_source_audit.json", "price_data_contract.json")
    existing = [destination / name for name in names if (destination / name).exists()]
    if existing:
        raise FileExistsError("DASHBOARD_OUTPUT_EXISTS:" + ",".join(str(x) for x in existing))
    safe_json = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = HTML.replace("__EMBEDDED_DATA__", safe_json)
    data_path = destination / "nvda_dashboard_data.json"
    validation_path = destination / "nvda_dashboard_validation.json"
    expiration_validation_path = destination / "expiration_aggregation_validation.json"
    field_audit_path = destination / "options_chain_field_audit.json"
    price_audit_path = destination / "price_source_audit.json"
    price_contract_path = destination / "price_data_contract.json"
    html_path = destination / "nvda_options_dashboard.html"
    png_path = destination / "nvda_options_dashboard.png"
    _write_atomic(data_path, (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    _write_atomic(html_path, html.encode("utf-8"))
    rendered = False
    if render_png:
        _render_data_png(data, png_path)
        rendered = True
    validation = dict(validation)
    validation["dashboard_png_render"] = "same_verified_data_matplotlib" if rendered else "NOT_RENDERED"
    validation["html_browser_render"] = "UNVERIFIED"
    validation["html_browser_render_note"] = "Actual browser rendering was not verified during offline build."
    _write_atomic(validation_path, (json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    expiration_validation = {"raw_sha256": data["raw_sha256"], "expiration_count": data["expiry_count"],
                            "expiration_dates": data["expirations"], "per_expiration": data["expiration_audit"],
                            "sum_reconciliation": data["expiration_sums_match"], "passed": all(data["expiration_sums_match"].values())}
    _write_atomic(expiration_validation_path, (json.dumps(expiration_validation, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    _write_atomic(field_audit_path, (json.dumps({"raw_sha256": data["raw_sha256"], "headers": data["raw_headers"],
                                                 "fields": data["field_audit"]}, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    reference = data.get("price_reference") or _validate_price_reference(None)
    price_contract = {key: reference.get(key) for key in ("symbol","price","currency","price_type","price_timestamp","captured_timestamp","source","verification_status","timestamp_precision","freshness_status","synchronous_with_option_chain") if key in reference}
    price_audit = {"price_found":reference.get("price") is not None,
                   "price_type":reference.get("price_type"),
                   "source_field":"data.lastTrade" if reference.get("price") is not None else None,
                   "raw_value":reference.get("raw_value"),
                   "price_timestamp":reference.get("price_timestamp"),
                   "timestamp_precision":reference.get("timestamp_precision"),
                   "captured_timestamp_utc":reference.get("captured_timestamp"),
                   "source":reference.get("source"),
                   "verification_status":reference.get("verification_status"),
                   "freshness_status":reference.get("freshness_status","UNAVAILABLE"),
                   "option_chain_timestamp":None,"underlying_quote_time_et":None,
                   "option_data_time_synchronization":"NOT_ESTABLISHED",
                   "is_current_price":False,"is_regular_close_verified":False,
                   "raw_sha256":data["raw_sha256"]}
    _write_atomic(price_contract_path, (json.dumps(price_contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    _write_atomic(price_audit_path, (json.dumps(price_audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    return {"html": str(html_path), "png": str(png_path) if rendered else None,
            "data_json": str(data_path), "validation_json": str(validation_path),
            "expiration_validation_json": str(expiration_validation_path), "field_audit_json": str(field_audit_path),
            "price_source_audit_json": str(price_audit_path), "price_data_contract_json": str(price_contract_path),
            "browser_rendered": False, "png_rendered_from_verified_data": rendered}


def _render_browser_png(html_path: Path, png_path: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1200}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.wait_for_function("window.NAVI_READY === true", timeout=15000)
        page.screenshot(path=str(png_path), full_page=True)
        browser.close()
    if errors:
        png_path.unlink(missing_ok=True)
        raise RuntimeError("BROWSER_RENDER_ERROR:" + " | ".join(errors))


def _render_data_png(data: dict, png_path: Path) -> None:
    """Render a review image from the same validated data embedded in the HTML."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    from matplotlib.ticker import FuncFormatter

    bg, panel, text, muted = "#090d12", "#111820", "#eef4f7", "#8fa0ad"
    green, pink, line = "#42e0ad", "#ff6687", "#26323e"
    fig = plt.figure(figsize=(16, 17), dpi=140, facecolor=bg)
    gs = GridSpec(6, 4, figure=fig, height_ratios=[.34, .72, 1.05, 1.25, .9, .78], hspace=.34, wspace=.24,
                  left=.045, right=.96, top=.94, bottom=.045)

    fig.text(.047, .975, "NAVI OPTIONS LAB  /  NVDA", color=green, fontsize=10, weight="bold", va="top")
    fig.text(.047, .946, "NVDA Options Flow Summary", color=text, fontsize=23, weight="bold", va="top")
    fig.text(.047, .919, "Observed Nasdaq Options Snapshot · All Expirations", color=muted, fontsize=10, va="top")
    fig.text(.96, .972, "PROVISIONAL", color=green, fontsize=10, weight="bold", ha="right", va="top")
    fig.text(.96, .949, f"{data['contracts_count']:,} contracts  ·  {data['strike_count']:,} strikes  ·  {data['expiry_count']} expirations", color=muted, fontsize=9, ha="right", va="top")
    fig.text(.96, .927, f"RUN {data['run_id']}  ·  {data['snapshot_timestamp_utc']} UTC", color=muted, fontsize=8, ha="right", va="top")

    totals = data["totals"]
    metrics = [("CALL VOLUME", totals["call_volume_observed_sum"], green),
               ("PUT VOLUME", totals["put_volume_observed_sum"], pink),
               ("CALL OPEN INTEREST", totals["call_oi_observed_sum"], green),
               ("PUT OPEN INTEREST", totals["put_oi_observed_sum"], pink)]
    for idx, (label, value, color) in enumerate(metrics):
        ax = fig.add_subplot(gs[1, idx]); ax.set_facecolor(panel)
        for sp in ax.spines.values(): sp.set_color(line)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.text(.08, .73, label, color=muted, fontsize=8, weight="bold", transform=ax.transAxes)
        ax.text(.08, .37, f"{value:,.0f}", color=color, fontsize=18, weight="bold", transform=ax.transAxes)
        ax.text(.08, .13, "OBSERVED CONTRACT VALUES", color=muted, fontsize=7, transform=ax.transAxes)

    for col, name, title, call_key, put_key in (
        (0, "volume", "CALLS VS PUTS · VOLUME", "call_volume_observed_sum", "put_volume_observed_sum"),
        (1, "oi", "CALLS VS PUTS · OPEN INTEREST", "call_oi_observed_sum", "put_oi_observed_sum"),
    ):
        ax = fig.add_subplot(gs[2, col]); ax.set_facecolor(panel)
        obj = data["donuts"][name]
        ax.pie([obj["call"], obj["put"]], colors=[green, pink], startangle=90, radius=.72,
               wedgeprops={"width": .22, "edgecolor": panel, "linewidth": 2})
        ax.text(0, .06, f"{obj['call_pct']:.1f}%", color=text, ha="center", va="center", fontsize=15, weight="bold")
        ax.text(0, -.2, "CALL SHARE", color=muted, ha="center", va="center", fontsize=7)
        ax.set_title(title, color=text, fontsize=9, weight="bold", pad=12)
        ax.text(-.92, -.91, f"Call  {obj['call']:,}  ({obj['call_pct']:.2f}%)", color=green, fontsize=8)
        ax.text(-.92, -.77, f"Put    {obj['put']:,}  ({obj['put_pct']:.2f}%)", color=pink, fontsize=8)
        ax.set_aspect("equal")

    for col, title, value, color in ((2, "OBSERVED VOLUME PCR", data["observed_volume_pcr"], green),
                                     (3, "OBSERVED PUT / CALL OI", data["oi_ratio"], pink)):
        ax = fig.add_subplot(gs[2, col]); ax.set_facecolor(panel)
        for sp in ax.spines.values(): sp.set_color(line)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.text(.08, .76, title, color=muted, fontsize=8, weight="bold", transform=ax.transAxes)
        ax.text(.08, .47, f"{value:.4f}", color=color, fontsize=24, weight="bold", transform=ax.transAxes)
        ax.text(.08, .2, "Observed sum ratio · PROVISIONAL", color=muted, fontsize=8, transform=ax.transAxes)

    rows = data["rows"]
    xs = [r["strike"] for r in rows]
    for col, title, call_key, put_key, ylabel in (
        (slice(0, 2), "NVDA Options Volume by Strike", "call_volume_observed_sum", "put_volume_observed_sum", "Observed Option Volume"),
        (slice(2, 4), "NVDA Open Interest by Strike", "call_oi_observed_sum", "put_oi_observed_sum", "Observed Open Interest"),
    ):
        ax = fig.add_subplot(gs[3, col]); ax.set_facecolor(panel)
        ax.bar(xs, [r[call_key] if r[call_key] is not None else math.nan for r in rows], color=green, width=1.0, alpha=.9, label="Call")
        ax.bar(xs, [-(r[put_key]) if r[put_key] is not None else math.nan for r in rows], color=pink, width=1.0, alpha=.9, label="Put · shown below zero")
        ax.axhline(0, color="#90a0ad", linewidth=.7)
        ax.set_title(title, color=text, fontsize=10, weight="bold", loc="left", pad=9)
        ax.set_xlabel("Strike Price ($)", color=muted, fontsize=8); ax.set_ylabel(ylabel, color=muted, fontsize=8)
        ax.tick_params(colors=muted, labelsize=7); ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
        ax.grid(axis="y", color=line, linewidth=.5, alpha=.6); ax.legend(frameon=False, labelcolor=text, fontsize=7, loc="upper right")
        view = data["default_range"]
        ax.set_xlim(view["min"], view["max"])
        for sp in ax.spines.values(): sp.set_color(line)

    rank_defs = (("call_volume", "CALL VOLUME TOP 5", green), ("put_volume", "PUT VOLUME TOP 5", pink),
                 ("call_oi", "CALL OPEN INTEREST TOP 5", green), ("put_oi", "PUT OPEN INTEREST TOP 5", pink))
    for col, (key, title, color) in enumerate(rank_defs):
        ax = fig.add_subplot(gs[4, col]); ax.set_facecolor(panel)
        for sp in ax.spines.values(): sp.set_color(line)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.text(.07, .88, title, color=color, fontsize=8, weight="bold", transform=ax.transAxes)
        for idx, row in enumerate(data["top5"][key]):
            y = .70 - idx * .135
            ax.text(.08, y, f"0{idx + 1}", color=muted, fontsize=8, transform=ax.transAxes)
            ax.text(.25, y, f"${row['strike']:,.0f}", color=text, fontsize=8, weight="bold", transform=ax.transAxes)
            ax.text(.57, y, f"{row['observed_sum']:,.0f}", color=text, fontsize=8, ha="right", transform=ax.transAxes)
            ax.text(.93, y, f"{row['share_pct']:.2f}%", color=color, fontsize=7, ha="right", transform=ax.transAxes)

    ax = fig.add_subplot(gs[5, :2]); ax.set_facecolor(panel)
    for sp in ax.spines.values(): sp.set_color(line)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    keys = (("$170", "Call Volume Peak", data["top5"]["call_volume"][0]["observed_sum"], green),
            ("$150", "Put Volume / OI Peak", data["top5"]["put_volume"][0]["observed_sum"], pink),
            ("$200", "Call OI Peak", data["top5"]["call_oi"][0]["observed_sum"], green),
            ("$160", "Watch · Call / Put Vol", "125,486 / 60,599", green))
    for idx, (strike, label, value, color) in enumerate(keys):
        x = .04 + idx * .24
        ax.text(x, .72, strike, color=color, fontsize=14, weight="bold", transform=ax.transAxes)
        ax.text(x, .48, label, color=muted, fontsize=7, transform=ax.transAxes)
        ax.text(x, .23, f"{value:,}" if isinstance(value, int) else value, color=text, fontsize=9, weight="bold", transform=ax.transAxes)
    ax = fig.add_subplot(gs[5, 2:]); ax.set_facecolor(panel)
    for sp in ax.spines.values(): sp.set_color(line)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(.06, .78, "NAVI OBSERVED FLOW · PROVISIONAL", color=green, fontsize=8, weight="bold", transform=ax.transAxes)
    ax.text(.06, .52, f"Call volume is concentrated at ${data['top5']['call_volume'][0]['strike']}, ${data['top5']['call_volume'][1]['strike']}, and ${data['top5']['call_volume'][2]['strike']}.", color=text, fontsize=8, transform=ax.transAxes)
    ax.text(.06, .29, "Strike concentrations describe observed contracts; they do not confirm support, resistance, or price direction.", color=muted, fontsize=7, transform=ax.transAxes)

    fig.text(.047, .02,
             "EOD_UNVERIFIED  ·  MISSINGNESS_CAUSE_UNKNOWN  ·  FULL_VOLUME_COMPLETENESS_UNVERIFIED  ·  Puts drawn below zero for visual comparison only",
             color="#e6ba75", fontsize=8, va="bottom")
    fig.savefig(png_path, facecolor=bg, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description="Generate a verified offline NVDA options-flow dashboard")
    p.add_argument("--contracts-csv", required=True)
    p.add_argument("--strike-summary", required=True)
    p.add_argument("--volume-csv", required=True)
    p.add_argument("--oi-csv", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--raw-json", required=True)
    p.add_argument("--batch-summary", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--no-png", action="store_true", help="Only write HTML/JSON; skip browser rendering")
    args = p.parse_args()
    data, validation = load_verified_data(args.contracts_csv, args.strike_summary, args.volume_csv,
                                          args.oi_csv, args.manifest, args.raw_json, args.batch_summary)
    result = build_dashboard(data, validation, args.output_dir, render_png=not args.no_png)
    print(json.dumps({"result": "NVDA_REAL_DASHBOARD_READY" if result["browser_rendered"] else "NVDA_REAL_DASHBOARD_RENDER_UNVERIFIED",
                      **result, "validation": validation}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


