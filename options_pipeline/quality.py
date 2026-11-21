"""Field-level quality and metric gates. Missing values never become zero."""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from . import QUALITY_SCHEMA_VERSION

VALUE_STATES = ("MISSING", "NULL", "EXPLICIT_ZERO", "VALID_POSITIVE", "INVALID_NEGATIVE", "INVALID_VALUE", "NOT_PROVIDED_BY_SOURCE")
DEFAULT_COVERAGE_THRESHOLD = 0.95


def _state(record, field):
    status_field = f"{field}_source_status"
    state = record.get(status_field)
    if state in VALUE_STATES:
        return state
    if field not in record:
        return "NOT_PROVIDED_BY_SOURCE"
    value = record[field]
    if value is None:
        return "NULL"
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return "INVALID_VALUE"
    if number < 0:
        return "INVALID_NEGATIVE"
    if number == 0:
        return "EXPLICIT_ZERO"
    return "VALID_POSITIVE"


def _number(record, field):
    if _state(record, field) not in ("EXPLICIT_ZERO", "VALID_POSITIVE"):
        return None
    try:
        return Decimal(str(record.get(field)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _field_stats(records, field):
    counts = Counter(_state(row, field) for row in records)
    eligible = len(records)
    valid_count = counts["EXPLICIT_ZERO"] + counts["VALID_POSITIVE"]
    values = [_number(row, field) for row in records]
    aggregate = sum((value for value in values if value is not None), Decimal("0"))
    return {
        "eligible_records": eligible,
        "counts": {state: counts[state] for state in VALUE_STATES},
        "missing_count": counts["MISSING"] + counts["NOT_PROVIDED_BY_SOURCE"],
        "null_count": counts["NULL"],
        "zero_count": counts["EXPLICIT_ZERO"],
        "positive_count": counts["VALID_POSITIVE"],
        "invalid_count": counts["INVALID_NEGATIVE"] + counts["INVALID_VALUE"],
        "valid_value_count": valid_count,
        "coverage_percentage": round(100 * valid_count / eligible, 4) if eligible else 0.0,
        "valid_value_aggregate": str(aggregate),
        "aggregate_scope": "VALID_VALUES_ONLY; missing values are not zero",
    }


def _quote_stats(records):
    fields = {}
    for field in ("bid", "ask"):
        values = [_number(row, field) for row in records]
        states = [_state(row, field) for row in records]
        fields[field] = {
            "eligible_records": len(records),
            "missing_count": sum(s in ("MISSING", "NOT_PROVIDED_BY_SOURCE") for s in states),
            "null_count": states.count("NULL"),
            "zero_count": states.count("EXPLICIT_ZERO"),
            "negative_count": states.count("INVALID_NEGATIVE"),
            "invalid_count": sum(s in ("INVALID_NEGATIVE", "INVALID_VALUE") for s in states),
            "missing_percentage": round(100 * sum(s in ("MISSING", "NOT_PROVIDED_BY_SOURCE", "NULL") for s in states) / len(records), 4) if records else 0.0,
            "zero_percentage": round(100 * states.count("EXPLICIT_ZERO") / len(records), 4) if records else 0.0,
        }
    spreads = []
    crossed = locked = 0
    for row in records:
        bid, ask = _number(row, "bid"), _number(row, "ask")
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            continue
        if bid > ask:
            crossed += 1
        elif bid == ask:
            locked += 1
        else:
            spreads.append(ask - bid)
    spreads.sort()
    median = None
    if spreads:
        mid = len(spreads) // 2
        median = str(spreads[mid] if len(spreads) % 2 else (spreads[mid - 1] + spreads[mid]) / 2)
    quote_times = [r.get("quote_timestamp") for r in records]
    return {
        "bid_ask": fields,
        "crossed_quote_count": crossed,
        "locked_quote_count": locked,
        "valid_spread_count": len(spreads),
        "spread_min": str(spreads[0]) if spreads else None,
        "spread_median": median,
        "spread_max": str(spreads[-1]) if spreads else None,
        "quote_timestamp_available_count": sum(bool(value) for value in quote_times),
        "quote_timestamp_missing_count": sum(not bool(value) for value in quote_times),
    }


def _duplicates(records):
    keys = []
    for row in records:
        keys.append((row.get("contract_identifier") or row.get("root"), row.get("expiration"), row.get("strike"), row.get("side")))
    return len(keys) - len(set(keys))


def _metric_gate(records, side_stats, freshness_status, field_freshness_status, parser_status, structural_issues, field, threshold, require_complete=False):
    coverage = {}
    for side in ("CALL", "PUT"):
        coverage[side] = side_stats[side][field]["valid_value_count"] / max(1, side_stats[side][field]["eligible_records"])
    if parser_status != "VALID" or structural_issues:
        return {"status": "BLOCKED", "value": None, "reason": "STRUCTURAL_VALIDATION_FAILED", "input_coverage": coverage}
    if freshness_status != "CURRENT_VERIFIED":
        return {"status": "BLOCKED", "value": None, "reason": f"FRESHNESS_{freshness_status}", "input_coverage": coverage}
    if field_freshness_status != "CURRENT_VERIFIED":
        return {"status": "BLOCKED", "value": None, "reason": f"{field.upper()}_ASOF_{field_freshness_status}", "input_coverage": coverage}
    if any(not side_stats[side][field]["eligible_records"] for side in ("CALL", "PUT")):
        return {"status": "BLOCKED", "value": None, "reason": "CALL_OR_PUT_SIDE_MISSING", "input_coverage": coverage}
    if require_complete and any(coverage[s] < 1.0 for s in coverage):
        return {"status": "BLOCKED", "value": None, "reason": "COMPLETE_INPUT_REQUIRED", "input_coverage": coverage}
    if any(coverage[s] < threshold for s in coverage):
        return {"status": "BLOCKED", "value": None, "reason": "INPUT_COVERAGE_BELOW_THRESHOLD", "input_coverage": coverage}
    status = "APPROVED" if all(coverage[s] == 1.0 for s in coverage) else "RESTRICTED"
    sums = {}
    for side in ("CALL", "PUT"):
        sums[side] = sum((_number(r, field) for r in records if r.get("side") == side and _number(r, field) is not None), Decimal("0"))
    return {"status": status, "value": None, "observed_only_value": None, "reason": "COMPLETE_INPUTS" if status == "APPROVED" else "OBSERVED_VALUES_ONLY_WITH_EXPLICIT_COVERAGE", "input_coverage": coverage, "observed_aggregates": {k: str(v) for k, v in sums.items()}, "eligible_record_counts": {s: side_stats[s][field]["eligible_records"] for s in coverage}}


def assess_quality(snapshot_metadata, records, coverage_threshold=DEFAULT_COVERAGE_THRESHOLD):
    by_side = {side: [r for r in records if r.get("side") == side] for side in ("CALL", "PUT")}
    side_stats = {side: {field: _field_stats(by_side[side], field) for field in ("volume", "open_interest", "bid", "ask", "last_price")} for side in by_side}
    issues = list(snapshot_metadata.get("parser_issues") or [])
    duplicate_count = _duplicates(records)
    if duplicate_count:
        issues.append("DUPLICATE_CONTRACT_KEYS")
    root_mismatches = sum(row.get("root_class") == "MISMATCH" for row in records)
    invalid_strikes = sum(row.get("strike") is None or row.get("strike_source_status") in ("INVALID_NEGATIVE", "INVALID_VALUE", "MISSING", "NULL", "NOT_PROVIDED_BY_SOURCE") for row in records)
    invalid_expirations = sum(not row.get("expiration") for row in records)
    expired_contracts = sum(bool(row.get("expiration") and snapshot_metadata.get("us_trading_session_date") and row["expiration"] < snapshot_metadata["us_trading_session_date"]) for row in records)
    missing_contract_identifiers = sum(not row.get("contract_identifier") for row in records)
    invalid_contract_identifiers = sum(row.get("contract_identifier_status") == "INVALID" for row in records)
    side_inconsistencies = sum(row.get("side") not in ("CALL", "PUT") for row in records)
    quote_stats = {side: _quote_stats(by_side[side]) for side in by_side}
    issues = sorted(set(issues))
    freshness_status = (snapshot_metadata.get("freshness") or {}).get("status", "UNVERIFIED")
    volume_freshness_status = (snapshot_metadata.get("volume_freshness") or {}).get("status", "SOURCE_TIME_UNAVAILABLE")
    oi_freshness_status = (snapshot_metadata.get("open_interest_freshness") or {}).get("status", "SOURCE_TIME_UNAVAILABLE")
    parser_status = snapshot_metadata.get("parser_status", "FAILED")
    structural_issues = bool(issues or duplicate_count or root_mismatches or invalid_strikes or invalid_expirations or expired_contracts or invalid_contract_identifiers or side_inconsistencies)
    metrics = {
        "PUT_CALL_VOLUME_RATIO": _metric_gate(records, side_stats, freshness_status, volume_freshness_status, parser_status, structural_issues, "volume", coverage_threshold),
        "PUT_CALL_OI_RATIO": _metric_gate(records, side_stats, freshness_status, oi_freshness_status, parser_status, structural_issues, "open_interest", coverage_threshold),
        "STRIKE_CONCENTRATION": _metric_gate(records, side_stats, freshness_status, oi_freshness_status, parser_status, structural_issues, "open_interest", coverage_threshold),
        "OI_WALL": _metric_gate(records, side_stats, freshness_status, oi_freshness_status, parser_status, structural_issues, "open_interest", coverage_threshold),
        "MAX_PAIN": _metric_gate(records, side_stats, freshness_status, oi_freshness_status, parser_status, structural_issues, "open_interest", coverage_threshold, require_complete=True),
    }
    for name, result in metrics.items():
        if result["status"] != "BLOCKED":
            result["status"] = "RESTRICTED" if result["status"] == "APPROVED" else result["status"]
            result["reason"] = "INPUT_GATE_PASSED; FORMULA_IMPLEMENTATION_NOT_APPROVED_IN_WORK10B"
            result["value"] = None
            result.pop("observed_only_value", None)
    if parser_status == "FAILED" or duplicate_count or root_mismatches or invalid_strikes or invalid_expirations or expired_contracts or invalid_contract_identifiers or side_inconsistencies:
        overall = "BLOCKED"
    elif freshness_status != "CURRENT_VERIFIED":
        overall = "BLOCKED"
    elif any(value["status"] == "BLOCKED" for value in metrics.values()):
        overall = "RESTRICTED"
    else:
        overall = "PENDING_METRIC_FORMULA_REVIEW"
    return {
        "quality_schema_version": QUALITY_SCHEMA_VERSION,
        "overall_status": overall,
        "coverage_threshold": coverage_threshold,
        "side_counts": {side: len(rows) for side, rows in by_side.items()},
        "field_quality_by_side": side_stats,
        "duplicate_contract_count": duplicate_count,
        "root_mismatch_count": root_mismatches,
        "invalid_strike_count": invalid_strikes,
        "invalid_expiration_count": invalid_expirations,
        "expired_contract_count": expired_contracts,
        "missing_contract_identifier_count": missing_contract_identifiers,
        "invalid_contract_identifier_count": invalid_contract_identifiers,
        "invalid_side_count": side_inconsistencies,
        "quote_integrity_by_side": quote_stats,
        "structural_issues": issues,
        "freshness_status": freshness_status,
        "derived_metrics": metrics,
        "iv_status": "NOT_PROVIDED_OR_NOT_VERIFIED",
    }

