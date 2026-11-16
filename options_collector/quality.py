"""Quality and missingness analysis. No missing value is coerced to zero."""
import hashlib, re
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from .status import Status

FIELDS = ("c_Volume", "p_Volume", "c_Openinterest", "p_Openinterest")
VOLUME_FIELDS = ("c_Volume", "p_Volume")
OI_FIELDS = ("c_Openinterest", "p_Openinterest")
TAXONOMY = ("OBSERVED_POSITIVE", "EXPLICIT_ZERO", "DASH_PLACEHOLDER", "EMPTY_STRING", "JSON_NULL", "FIELD_ABSENT", "NON_NUMERIC_INVALID")


def classify_value(row: dict, field: str) -> tuple[str, str | None]:
    if field not in row:
        return "FIELD_ABSENT", None
    value = row[field]
    if value is None:
        return "JSON_NULL", None
    if isinstance(value, str) and value == "":
        return "EMPTY_STRING", value
    if isinstance(value, str) and value == "--":
        return "DASH_PLACEHOLDER", value
    if isinstance(value, bool):
        return "NON_NUMERIC_INVALID", str(value)
    try:
        numeric = Decimal(str(value).replace(",", "").strip())
        if not numeric.is_finite() or numeric < 0:
            return "NON_NUMERIC_INVALID", str(value)
        if numeric == 0:
            return "EXPLICIT_ZERO", str(value)
        return "OBSERVED_POSITIVE", str(value)
    except (InvalidOperation, ValueError, TypeError):
        return "NON_NUMERIC_INVALID", str(value)


def inspect_quality(parsed, raw: bytes, response_status, api_rcode, collected_at_utc=None, snapshot_dir=None) -> dict:
    taxonomy = {field: Counter() for field in FIELDS}
    normalized_rows = []
    for row in parsed.rows:
        per_field = {}
        for field in FIELDS:
            category, normalized = classify_value(row, field)
            taxonomy[field][category] += 1
            per_field[field] = {"raw": row.get(field) if field in row else None,
                                "field_present": field in row,
                                "classification": category,
                                "normalized_numeric": normalized if category in ("OBSERVED_POSITIVE", "EXPLICIT_ZERO") else None}
        normalized_rows.append(per_field)
    field_metrics = {}
    n = len(parsed.rows)
    for field in FIELDS:
        counts = {name: taxonomy[field][name] for name in TAXONOMY}
        observed = counts["OBSERVED_POSITIVE"] + counts["EXPLICIT_ZERO"]
        field_metrics[field] = {"contract_count": n, "taxonomy_counts": counts,
                                "observation_count": observed,
                                "observation_rate": observed / n if n else None,
                                "missing_or_unobserved_count": n - observed,
                                "missing_or_unobserved_rate": (n-observed)/n if n else None,
                                "explicit_zero_count": counts["EXPLICIT_ZERO"],
                                "missing_types": {"field_absent": counts["FIELD_ABSENT"], "null": counts["JSON_NULL"], "empty_string": counts["EMPTY_STRING"], "dash": counts["DASH_PLACEHOLDER"], "non_numeric_invalid": counts["NON_NUMERIC_INVALID"]}}
    asof = _asof_date(collected_at_utc)
    expirations = _distribution(parsed.rows, lambda row: row.get("_expiration"), FIELDS)
    strikes = _distribution(parsed.rows, lambda row: _strike_key(row), FIELDS)
    horizons = _horizon_distribution(parsed.rows, asof)
    quote_valid = _quote_is_usable(parsed.underlying_quote_time_et, collected_at_utc)
    atm_band = None
    atm_metrics = "NOT_EVALUABLE"
    if quote_valid and parsed.underlying_price:
        try:
            spot = Decimal(parsed.underlying_price)
            atm_rows = [r for r in parsed.rows if r.get("_strike_value") is not None and abs(r["_strike_value"]-spot)/spot <= Decimal("0.05")]
            atm_band = {"definition": "absolute strike moneyness within 5% of Nasdaq lastTrade spot", "spot": str(spot), "quote_timestamp_et": parsed.underlying_quote_time_et, "contract_count": len(atm_rows)}
            atm_metrics = _paired_rates(atm_rows)
        except (InvalidOperation, ZeroDivisionError):
            atm_band = None
    moneyness = _moneyness_distribution(parsed.rows, Decimal(parsed.underlying_price) if quote_valid and parsed.underlying_price else None)
    asymmetry = {"call_volume_observation_rate": _rate(parsed.rows, "c_Volume"),
                 "put_volume_observation_rate": _rate(parsed.rows, "p_Volume"),
                 "call_oi_observation_rate": _rate(parsed.rows, "c_Openinterest"),
                 "put_oi_observation_rate": _rate(parsed.rows, "p_Openinterest")}
    roots = Counter(row.get("_root_class", "UNKNOWN") for row in parsed.rows)
    duplicate_keys = [_contract_key(row) for row in parsed.rows]
    response_sha = hashlib.sha256(raw).hexdigest()
    total_matches = (parsed.total_record == parsed.raw_row_count if parsed.total_record_scope == "raw_table_rows" else (parsed.total_record == len(parsed.rows) if parsed.total_record_scope == "contracts" else None))
    valid_strikes = sum(bool(r.get("_strike_valid")) for r in parsed.rows)
    valid_expirations = sum(bool(r.get("_expiration")) for r in parsed.rows)
    duplicate_count = len(duplicate_keys) - len(set(duplicate_keys))
    all_roots_classified = all(r.get("_root_class") in ("STANDARD", "ADJUSTED") for r in parsed.rows)
    parser_integrity = {"data_table_rows_count": parsed.raw_row_count,
                        "totalRecord": parsed.total_record,
                        "totalRecord_scope": parsed.total_record_scope,
                        "totalRecord_matches_expected_scope": total_matches,
                        "expiry_header_count": parsed.expiry_groups,
                        "parsed_contract_count": len(parsed.rows),
                        "contracts_with_valid_strike": valid_strikes,
                        "contracts_with_expiration": valid_expirations,
                        "all_roots_classified": all_roots_classified,
                        "duplicate_contract_keys": duplicate_count,
                        "issues": parsed.issues,
                        "ok": parsed.schema_ok and total_matches is True and valid_strikes == len(parsed.rows) and valid_expirations == len(parsed.rows) and all_roots_classified and duplicate_count == 0}
    snapshot_integrity = {"raw_sha256": response_sha, "raw_bytes": len(raw), "snapshot_readback_verified": None}
    if snapshot_dir is not None:
        snapshot_integrity["snapshot_readback_verified"] = _snapshot_readback(snapshot_dir, response_sha)
    api_state = "API_VERIFIED" if response_status == 200 and api_rcode == 200 else ("ACCESS_BLOCKED" if response_status in (403,429) else "FETCH_ERROR")
    data_state = "DATA_OBSERVED" if parsed.rows and parser_integrity["ok"] and all(v["missing_or_unobserved_count"] == 0 for v in field_metrics.values()) else ("QUALITY_LIMITED" if parsed.rows and parser_integrity["ok"] else "SCHEMA_MISMATCH")
    status = Status(api=api_state, data=data_state, freshness="EOD_UNVERIFIED")
    if any(any(c["missing_or_unobserved_count"] for c in [m]) for m in field_metrics.values()): status.reasons.append("VOLUME_OI_UNOBSERVED_VALUES")
    status.reasons.extend(parsed.issues)
    return {
        "symbol": parsed.symbol, "http_status": response_status, "api_rcode": api_rcode,
        "raw_sha256": response_sha, "raw_bytes": len(raw),
        "raw_table_row_count": parsed.raw_row_count, "contract_rows": len(parsed.rows),
        "totalRecord": parsed.total_record, "totalRecord_scope": parser_integrity["totalRecord_scope"], "totalRecord_matches_expected_scope": parser_integrity["totalRecord_matches_expected_scope"],
        "expiry_group_count": parsed.expiry_groups, "standard_adjusted_unknown_roots": dict(roots),
        "duplicate_contract_keys": len(duplicate_keys)-len(set(duplicate_keys)),
        "volume_oi": field_metrics, "per_contract_normalized_values": normalized_rows,
        "distributions": {"expiration": expirations, "strike": strikes, "horizon": horizons,
                          "moneyness": moneyness, "atm": atm_band, "atm_metrics": atm_metrics},
        "call_put_asymmetry": asymmetry,
        "overall_volume_observation_rate": _combined_rate(field_metrics, VOLUME_FIELDS),
        "overall_oi_observation_rate": _combined_rate(field_metrics, OI_FIELDS),
        "near_term_volume_observation_rate": horizons.get("near_term", {}).get("volume_observation_rate", "NOT_EVALUABLE"),
        "near_term_oi_observation_rate": horizons.get("near_term", {}).get("oi_observation_rate", "NOT_EVALUABLE"),
        "atm_volume_observation_rate": atm_metrics.get("volume_observation_rate", "NOT_EVALUABLE") if isinstance(atm_metrics, dict) else "NOT_EVALUABLE",
        "atm_oi_observation_rate": atm_metrics.get("oi_observation_rate", "NOT_EVALUABLE") if isinstance(atm_metrics, dict) else "NOT_EVALUABLE",
        "parser_integrity": parser_integrity, "snapshot_integrity": snapshot_integrity,
        "option_chain_timestamp": parsed.option_chain_timestamp,
        "eod_freshness": "EOD_UNVERIFIED",
        "status": {"api": status.api, "data": status.data, "freshness": status.freshness, "reasons": status.reasons},
        "collected_at_utc": collected_at_utc,
        "underlying_last_trade_raw": parsed.underlying_last_trade_raw,
        "underlying_quote_time_et": parsed.underlying_quote_time_et,
        "underlying_quote_used_for_atm": bool(quote_valid and parsed.underlying_price),
    }


def _distribution(rows, key_fn, fields):
    groups = defaultdict(list)
    for row in rows:
        key = key_fn(row)
        groups[str(key) if key is not None else "UNKNOWN"].append(row)
    result = {}
    for key, group in sorted(groups.items(), key=lambda x: _sort_key(x[0])):
        result[key] = {"contract_count": len(group), "fields": {field: _field_rates(group, field) for field in fields}}
    return result


def _horizon_distribution(rows, asof):
    buckets = {"near_term": [], "mid_term": [], "far_term": [], "unclassified": []}
    for row in rows:
        exp = _date(row.get("_expiration"))
        if exp is None or asof is None:
            buckets["unclassified"].append(row); continue
        days = (exp - asof).days
        if days < 0: buckets["unclassified"].append(row)
        elif days <= 30: buckets["near_term"].append(row)
        elif days <= 90: buckets["mid_term"].append(row)
        else: buckets["far_term"].append(row)
    result = {"definition": {"near_term_days": "0-30", "mid_term_days": "31-90", "far_term_days": ">90", "as_of_date": asof.isoformat() if asof else None}, "buckets": {}}
    for name, group in buckets.items():
        rates = _paired_rates(group)
        result["buckets"][name] = {"contract_count": len(group), **rates}
    # Flat keys keep the requested quality-gate interface easy to consume.
    result.update({name: result["buckets"][name] for name in buckets})
    return result


def _paired_rates(rows):
    if not rows: return {"volume_observation_rate": None, "oi_observation_rate": None, "field_rates": {field: None for field in FIELDS}}
    field_rates = {f: _rate(rows, f) for f in FIELDS}
    return {"volume_observation_rate": _mean([field_rates[f] for f in VOLUME_FIELDS]),
            "oi_observation_rate": _mean([field_rates[f] for f in OI_FIELDS]), "field_rates": field_rates}


def _moneyness_distribution(rows, spot):
    if spot is None or spot <= 0:
        return "NOT_EVALUABLE"
    buckets={"near_atm_0_5pct":[], "mid_distance_5_15pct":[], "far_distance_over_15pct":[], "unclassified":[]}
    for row in rows:
        strike=row.get("_strike_value")
        if strike is None:
            buckets["unclassified"].append(row); continue
        distance=abs(strike-spot)/spot
        if distance<=Decimal("0.05"): buckets["near_atm_0_5pct"].append(row)
        elif distance<=Decimal("0.15"): buckets["mid_distance_5_15pct"].append(row)
        else: buckets["far_distance_over_15pct"].append(row)
    return {"definition":"absolute strike distance from timestamp-validated underlying lastTrade; <=5%, >5%-15%, >15%", "spot":str(spot), **{name:{"contract_count":len(group),**_paired_rates(group)} for name,group in buckets.items()}}

def _field_rates(rows, field):
    counts = Counter(classify_value(r, field)[0] for r in rows)
    observed = counts["OBSERVED_POSITIVE"] + counts["EXPLICIT_ZERO"]
    n = len(rows)
    return {"observation_rate": observed/n if n else None,
            "dash_placeholder_rate": counts["DASH_PLACEHOLDER"]/n if n else None,
            "taxonomy_counts": {name: counts[name] for name in TAXONOMY}}


def _rate(rows, field):
    if not rows: return None
    return sum(classify_value(r, field)[0] in ("OBSERVED_POSITIVE", "EXPLICIT_ZERO") for r in rows)/len(rows)


def _combined_rate(metrics, names):
    count = sum(metrics[f]["contract_count"] for f in names)
    observed = sum(metrics[f]["observation_count"] for f in names)
    denom = 2 * metrics[names[0]]["contract_count"] if metrics[names[0]]["contract_count"] == metrics[names[1]]["contract_count"] else count
    return observed/denom if denom else None


def _asof_date(collected_at_utc):
    if not collected_at_utc: return None
    try: return datetime.fromisoformat(collected_at_utc.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date()
    except (ValueError, TypeError): return None


def _quote_is_usable(quote_time_et, collected_at_utc):
    if not quote_time_et or not collected_at_utc: return False
    try:
        q = datetime.fromisoformat(quote_time_et)
        captured = datetime.fromisoformat(collected_at_utc.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
        return abs((captured-q).total_seconds()) <= 300
    except (ValueError, TypeError): return False


def _date(value):
    try: return date.fromisoformat(value) if value else None
    except (ValueError, TypeError): return None

def _strike_key(row):
    value = row.get("_strike_value")
    return format(value.normalize(), "f") if value is not None else None

def _contract_key(row):
    return (row.get("_expiration"), _strike_key(row), row.get("_root"))

def _sort_key(value):
    try: return (0, float(value))
    except (ValueError, TypeError): return (1, value)

def _mean(values):
    usable=[v for v in values if v is not None]
    return sum(usable)/len(usable) if usable else None

def _snapshot_readback(directory, expected_sha):
    import json
    from pathlib import Path
    p=Path(directory)
    try:
        raw=(p/"raw.json").read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected_sha: return False
        json.loads((p/"quality.json").read_text(encoding="utf-8"))
        json.loads((p/"manifest.json").read_text(encoding="utf-8"))
        return (p/"contracts.csv").is_file()
    except (OSError, ValueError): return False
