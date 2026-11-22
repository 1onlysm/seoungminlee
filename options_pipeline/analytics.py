"""Observed-only SPY options analytics shared by offline import paths."""
from decimal import Decimal, InvalidOperation

VALID_STATES = {"EXPLICIT_ZERO", "VALID_POSITIVE"}
MISSING_STATES = {"MISSING", "NOT_PROVIDED_BY_SOURCE"}
INVALID_STATES = {"INVALID_NEGATIVE", "INVALID_VALUE"}


def _state(record, field):
    value = record.get("source_field_availability", {}).get(field, {})
    if isinstance(value, dict) and value.get("availability"):
        return value["availability"]
    return record.get(f"{field}_source_status", "NOT_PROVIDED_BY_SOURCE")


def _decimal(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _summary(records, field):
    eligible = list(records)
    counts = {"missing_count": 0, "null_count": 0, "zero_count": 0,
              "positive_count": 0, "invalid_count": 0}
    values = []
    for row in eligible:
        state = _state(row, field)
        value = _decimal(row.get(field))
        if state == "NULL":
            counts["null_count"] += 1
        elif state in MISSING_STATES:
            counts["missing_count"] += 1
        elif state == "EXPLICIT_ZERO" and value == 0:
            counts["zero_count"] += 1
            values.append(value)
        elif state == "VALID_POSITIVE" and value is not None and value > 0:
            counts["positive_count"] += 1
            values.append(value)
        else:
            counts["invalid_count"] += 1
    valid_count = len(values)
    coverage = round(valid_count * 100 / len(eligible), 4) if eligible else 0.0
    return {"observed_total": str(sum(values, Decimal(0))), "valid_count": valid_count,
            "eligible_count": len(eligible), **counts,
            "coverage_percentage": coverage,
            "missing_percentage": round(100 - coverage, 4) if eligible else 100.0}


def _side_summaries(records, field):
    return {side: _summary([row for row in records if row.get("side") == side], field)
            for side in ("CALL", "PUT")}


def _pcr(records, field, freshness_status, provenance_status, structural_quality):
    sides = _side_summaries(records, field)
    call, put = sides["CALL"], sides["PUT"]
    call_total, put_total = Decimal(call["observed_total"]), Decimal(put["observed_total"])
    if not call["eligible_count"] or not put["eligible_count"]:
        status, reason, value = "BLOCKED", "CALL_OR_PUT_SIDE_MISSING", None
    elif not call["valid_count"] or not put["valid_count"]:
        status, reason, value = "BLOCKED", "NO_VALID_OBSERVATIONS_ON_BOTH_SIDES", None
    elif call_total <= 0:
        status, reason, value = "BLOCKED", "CALL_OBSERVED_TOTAL_ZERO", None
    else:
        status, reason, value = "PROVISIONAL", "OBSERVED_VALUES_ONLY", str(put_total / call_total)
    if status == "BLOCKED":
        state = "INVALID_CONTRACT_DATA" if structural_quality == "INVALID" else "BLOCKED"
    elif any(sides[side]["coverage_percentage"] < 100 for side in ("CALL", "PUT")):
        state = "INSUFFICIENT_COVERAGE"
    elif freshness_status == "SOURCE_TIME_UNAVAILABLE":
        state = "SOURCE_TIME_UNAVAILABLE"
    elif provenance_status != "VERIFIED":
        state = "PROVISIONAL"
    elif structural_quality != "VALID":
        state = "INVALID_CONTRACT_DATA"
    elif freshness_status != "CURRENT_VERIFIED":
        state = "PROVISIONAL"
    else:
        state = "VERIFIED_INPUT"
    return {"value": value, "status": status, "quality_state": state, "reason": reason,
            "call_observed_total": call["observed_total"], "put_observed_total": put["observed_total"],
            "valid_observation_count": call["valid_count"] + put["valid_count"],
            "eligible_record_count": call["eligible_count"] + put["eligible_count"],
            "coverage": sides}


def _rank(records, field, side=None):
    grouped = {}
    for row in records:
        if side and row.get("side") != side:
            continue
        state, value = _state(row, field), _decimal(row.get(field))
        if state not in VALID_STATES or value is None or value < 0:
            continue
        key = (row["side"], row["strike"])
        grouped[key] = grouped.get(key, Decimal(0)) + value
    output = {}
    for current_side in ("CALL", "PUT"):
        side_total = sum((value for (s, _), value in grouped.items() if s == current_side), Decimal(0))
        ranked = sorted(((strike, value) for (s, strike), value in grouped.items() if s == current_side),
                        key=lambda pair: (-pair[1], Decimal(pair[0])))[:5]
        output[current_side] = [{"strike": strike, "observed_total": str(value),
                                 "concentration_share_percentage": round(float(value * 100 / side_total), 4) if side_total > 0 else None}
                                for strike, value in ranked]
    return output


def _max_pain(records, expiration, session_date, structural_quality):
    group = [row for row in records if row.get("expiration") == expiration]
    sides = {row.get("side") for row in group}
    strikes = sorted({row.get("strike") for row in group if _decimal(row.get("strike")) is not None}, key=Decimal)
    oi_complete = all(_state(row, "open_interest") in VALID_STATES and _decimal(row.get("open_interest")) is not None
                      and _decimal(row.get("open_interest")) >= 0 for row in group)
    multipliers = [_decimal(row.get("contract_multiplier")) for row in group]
    reason = None
    if structural_quality == "INVALID":
        reason = "STRUCTURAL_QUALITY_INVALID"
    elif session_date in (None, "", "unknown-session"):
        reason = "SESSION_DATE_UNAVAILABLE"
    elif expiration <= session_date:
        reason = "EXPIRATION_NOT_ELIGIBLE"
    elif sides != {"CALL", "PUT"}:
        reason = "CALL_OR_PUT_SIDE_MISSING_FOR_EXPIRATION"
    elif not oi_complete:
        reason = "OPEN_INTEREST_INPUT_INCOMPLETE_OR_INVALID"
    elif any(value is None or value <= 0 for value in multipliers) or len({str(value) for value in multipliers}) != 1:
        reason = "CONTRACT_MULTIPLIER_UNAVAILABLE_OR_INCONSISTENT"
    elif len(strikes) < 2:
        reason = "INSUFFICIENT_STRIKE_UNIVERSE"
    elif any(row.get("contract_identifier_status") in {"INVALID", "INVALID_OSI_MISMATCH"} for row in group):
        reason = "INVALID_CONTRACT_IDENTIFIER"
    if reason:
        return {"status": "BLOCKED", "value": None, "reason": reason,
                "eligible_contract_count": len(group), "strike_count": len(strikes)}
    multiplier = multipliers[0]
    payouts = {}
    for settlement in map(Decimal, strikes):
        payout = Decimal(0)
        for row in group:
            strike, oi = Decimal(row["strike"]), Decimal(row["open_interest"])
            if row["side"] == "CALL" and settlement > strike:
                payout += (settlement - strike) * oi * multiplier
            elif row["side"] == "PUT" and settlement < strike:
                payout += (strike - settlement) * oi * multiplier
        payouts[str(settlement)] = str(payout)
    minimum = min(map(Decimal, payouts.values()))
    value = min((key for key, amount in payouts.items() if Decimal(amount) == minimum), key=Decimal)
    return {"status": "PROVISIONAL", "value": value,
            "reason": "COMPLETE_OBSERVED_OI_EXPLICIT_MULTIPLIER_AND_ELIGIBLE_EXPIRATION",
            "eligible_contract_count": len(group), "strike_count": len(strikes),
            "payout_by_settlement": payouts}


def analyze_options(records, coverage, structural_quality, research_usability,
                    freshness_status, session_date=None, provenance_status="UNVERIFIED",
                    strike_range=None):
    """Calculate provisional research metrics without imputing absent observations."""
    totals = {field: _side_summaries(records, field) for field in ("volume", "open_interest")}
    ratios = {}
    for field, name in (("volume", "observed_volume_pcr"), ("open_interest", "observed_oi_pcr")):
        ratios[name] = _pcr(records, field, freshness_status, provenance_status, structural_quality)
    expirations = sorted({row["expiration"] for row in records})
    per_expiry = {}
    for expiry in expirations:
        group = [row for row in records if row["expiration"] == expiry]
        per_expiry[expiry] = {
            "contract_count": len(group),
            "observed_totals": {field: _side_summaries(group, field) for field in ("volume", "open_interest")},
            "put_call_ratios": {field: _pcr(group, field, freshness_status, provenance_status, structural_quality)
                                for field in ("volume", "open_interest")},
            "call_wall_candidates": _rank(group, "open_interest", "CALL")["CALL"],
            "put_wall_candidates": _rank(group, "open_interest", "PUT")["PUT"],
            "top_call_volume": _rank(group, "volume", "CALL")["CALL"],
            "top_put_volume": _rank(group, "volume", "PUT")["PUT"],
            "max_pain": _max_pain(group, expiry, session_date, structural_quality),
        }
    if strike_range is None:
        selected_range = {"status": "BLOCKED", "value": None,
                          "quality_state": "BLOCKED", "reason": "STRIKE_RANGE_NOT_SELECTED"}
    else:
        low, high = map(_decimal, strike_range)
        if low is None or high is None or low <= 0 or high < low:
            selected_range = {"status": "BLOCKED", "value": None,
                              "quality_state": "BLOCKED", "reason": "INVALID_STRIKE_RANGE"}
        else:
            selected = [row for row in records if low <= Decimal(row["strike"]) <= high]
            selected_range = _pcr(selected, "volume", freshness_status, provenance_status, structural_quality)
            selected_range["strike_range"] = {"min": str(low), "max": str(high)}
    max_pain_by_expiry = {expiry: values["max_pain"] for expiry, values in per_expiry.items()}
    max_pain_ready = bool(max_pain_by_expiry) and all(value["status"] == "PROVISIONAL" for value in max_pain_by_expiry.values())
    call_walls = _rank(records, "open_interest", "CALL")["CALL"]
    put_walls = _rank(records, "open_interest", "PUT")["PUT"]
    top_call_volume = _rank(records, "volume", "CALL")["CALL"]
    top_put_volume = _rank(records, "volume", "PUT")["PUT"]
    concentration = {}
    for field in ("volume", "open_interest"):
        ranked = _rank(records, field)
        by_strike, by_expiry = {}, {}
        for row in records:
            if _state(row, field) not in VALID_STATES or _decimal(row.get(field)) is None:
                continue
            value = Decimal(row[field])
            key, ekey = f"{row['side']}:{row['strike']}", f"{row['side']}:{row['expiration']}"
            by_strike[key] = str(Decimal(by_strike.get(key, "0")) + value)
            by_expiry[ekey] = str(Decimal(by_expiry.get(ekey, "0")) + value)
        concentration[field] = {"by_side_and_strike": by_strike, "by_side_and_expiration": by_expiry,
                                "highest_observed_strikes_by_side": ranked,
                                "status": "PROVISIONAL_OBSERVED_CONCENTRATION", "coverage": coverage.get(field, {})}
    return {
        "status": "PROVISIONAL_ONLY",
        "put_call_ratios": {**ratios, "by_expiration": {expiry: values["put_call_ratios"] for expiry, values in per_expiry.items()},
                            "selected_strike_range_volume_pcr": selected_range},
        "observed_totals": totals,
        "expiration_analytics": per_expiry,
        "concentration": concentration,
        "call_wall_candidates": {"label": "CALL_WALL_CANDIDATE", "status": "PROVISIONAL",
                                  "quality_state": "SOURCE_TIME_UNAVAILABLE" if freshness_status == "SOURCE_TIME_UNAVAILABLE" else "PROVISIONAL",
                                  "items": call_walls},
        "put_wall_candidates": {"label": "PUT_WALL_CANDIDATE", "status": "PROVISIONAL",
                                 "quality_state": "SOURCE_TIME_UNAVAILABLE" if freshness_status == "SOURCE_TIME_UNAVAILABLE" else "PROVISIONAL",
                                 "items": put_walls},
        "volume_concentration": {"top_call": top_call_volume, "top_put": top_put_volume,
                                  "interpretation": "OBSERVED_VOLUME_ONLY_NOT_DIRECTIONAL"},
        "max_pain": {"status": "PROVISIONAL" if max_pain_ready else "BLOCKED",
                     "value": {expiry: item.get("value") for expiry, item in max_pain_by_expiry.items()} if max_pain_ready else None,
                     "reason": "PER_EXPIRATION_RESULTS" if max_pain_ready else "ONE_OR_MORE_EXPIRATIONS_FAILED_INPUT_GATES",
                     "by_expiration": max_pain_by_expiry},
        "metric_quality": {"source_provenance": provenance_status, "freshness": freshness_status,
                           "structural_quality": structural_quality, "research_usability": research_usability,
                           "evidence_kind": "USER_SUPPLIED_FILE_NOT_INDEPENDENTLY_VERIFIED"},
        "iv_greeks": {"status": "SOURCE_VALUES_ONLY", "calculated": False,
                      "fields": {name: sum(row.get(name) is not None for row in records)
                                 for name in ("implied_volatility", "delta", "gamma", "theta", "vega", "rho")}},
        "warnings": ["USER_SUPPLIED_FILE_NOT_INDEPENDENTLY_VERIFIED", "NO_COMPLETE_MARKET_COVERAGE_CLAIM",
                     f"FRESHNESS_{freshness_status}", f"RESEARCH_USABILITY_{research_usability}",
                     "WALLS_ARE_OBSERVED_OI_CONCENTRATIONS_NOT_DEALER_POSITION_OR_SUPPORT_LEVEL"]
    }


def compare_snapshots(previous, current, *, retention_permitted=False):
    """Compare only compatible snapshots; callers must confirm retention rights."""
    pm, cm = previous.get("manifest", {}), current.get("manifest", {})
    reasons = []
    if not retention_permitted:
        reasons.append("RETENTION_PERMISSION_UNVERIFIED")
    for key in ("provider", "endpoint_identifier", "requested_symbol", "normalization_schema_version"):
        if pm.get(key) != cm.get(key):
            reasons.append(f"INCOMPATIBLE_{key.upper()}")
    pexp = {row.get("expiration") for row in previous.get("records", [])}
    cexp = {row.get("expiration") for row in current.get("records", [])}
    if pexp != cexp:
        reasons.append("EXPIRATION_UNIVERSE_MISMATCH")
    if not (pm.get("source_asof_timestamp") or pm.get("provider_asof_timestamp")) or not (cm.get("source_asof_timestamp") or cm.get("provider_asof_timestamp")):
        reasons.append("SOURCE_TIMESTAMP_UNAVAILABLE")
    if reasons:
        return {"status": "BLOCKED", "reason": reasons, "contracts": [], "oi_change": None,
                "volume_change": None, "pcr_change": None, "wall_movement": None}
    pmap = {(r.get("expiration"), r.get("strike"), r.get("side")): r for r in previous.get("records", [])}
    cmap = {(r.get("expiration"), r.get("strike"), r.get("side")): r for r in current.get("records", [])}
    if pmap.keys() != cmap.keys():
        return {"status": "BLOCKED", "reason": ["CONTRACT_UNIVERSE_MISMATCH"], "contracts": [],
                "oi_change": None, "volume_change": None, "pcr_change": None, "wall_movement": None}
    if any(_state(row, field) not in VALID_STATES or _decimal(row.get(field)) is None
           for row in list(pmap.values()) + list(cmap.values()) for field in ("volume", "open_interest")):
        return {"status": "BLOCKED", "reason": ["REQUIRED_VOLUME_OR_OI_INPUT_MISSING_OR_INVALID"], "contracts": [],
                "oi_change": None, "volume_change": None, "pcr_change": None, "wall_movement": None}
    changes = []
    for key in sorted(pmap):
        before, after = pmap[key], cmap[key]
        item = {"expiration": key[0], "strike": key[1], "side": key[2]}
        for field in ("volume", "open_interest"):
            if _state(before, field) not in VALID_STATES or _state(after, field) not in VALID_STATES:
                item[f"{field}_change"] = None
                item[f"{field}_status"] = "BLOCKED_MISSING_OR_INVALID_INPUT"
            else:
                item[f"{field}_change"] = str(Decimal(after[field]) - Decimal(before[field]))
                item[f"{field}_status"] = "PROVISIONAL_COMPARABLE_SOURCE_VALUES"
        changes.append(item)
    def observed_pcr(rows, field):
        calls = sum((Decimal(row[field]) for row in rows if row.get("side") == "CALL" and _state(row, field) in VALID_STATES and _decimal(row.get(field)) is not None), Decimal(0))
        puts = sum((Decimal(row[field]) for row in rows if row.get("side") == "PUT" and _state(row, field) in VALID_STATES and _decimal(row.get(field)) is not None), Decimal(0))
        return puts / calls if calls > 0 else None
    old_volume_pcr, new_volume_pcr = observed_pcr(previous["records"], "volume"), observed_pcr(current["records"], "volume")
    old_oi_pcr, new_oi_pcr = observed_pcr(previous["records"], "open_interest"), observed_pcr(current["records"], "open_interest")
    old_oi_rank, new_oi_rank = _rank(previous["records"], "open_interest"), _rank(current["records"], "open_interest")
    wall_movement = {}
    for side in ("CALL", "PUT"):
        old_wall = old_oi_rank[side][0]["strike"] if old_oi_rank[side] else None
        new_wall = new_oi_rank[side][0]["strike"] if new_oi_rank[side] else None
        wall_movement[side] = {"label": f"{side}_WALL_CANDIDATE", "previous_strike": old_wall,
                               "current_strike": new_wall, "status": "PROVISIONAL" if old_wall and new_wall else "BLOCKED"}
    return {"status": "PROVISIONAL", "reason": ["USER_SUPPLIED_SNAPSHOTS_NOT_INDEPENDENTLY_VERIFIED"],
            "contracts": changes, "oi_change": [x for x in changes if x["open_interest_change"] is not None],
            "volume_change": [x for x in changes if x["volume_change"] is not None],
            "pcr_change": {"observed_volume_pcr": str(new_volume_pcr - old_volume_pcr) if old_volume_pcr is not None and new_volume_pcr is not None else None,
                           "observed_oi_pcr": str(new_oi_pcr - old_oi_pcr) if old_oi_pcr is not None and new_oi_pcr is not None else None,
                           "status": "PROVISIONAL" if old_volume_pcr is not None and new_volume_pcr is not None and old_oi_pcr is not None and new_oi_pcr is not None else "BLOCKED"},
            "wall_movement": wall_movement}
