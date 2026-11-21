"""Normalize Nasdaq's paired strike rows without fabricating missing fields."""
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from . import SCHEMA_VERSION

SOURCE_FIELDS = {
    "CALL": {"option_symbol": "c_Option", "volume": "c_Volume", "open_interest": "c_Openinterest",
             "bid": "c_Bid", "ask": "c_Ask", "last_price": "c_Last", "quote_timestamp": "c_QuoteTime"},
    "PUT": {"option_symbol": "p_Option", "volume": "p_Volume", "open_interest": "p_Openinterest",
            "bid": "p_Bid", "ask": "p_Ask", "last_price": "p_Last", "quote_timestamp": "p_QuoteTime"},
}
NUMERIC_FIELDS = ("volume", "open_interest", "bid", "ask", "last_price", "strike")


class PayloadError(ValueError):
    pass


def _as_decimal(value):
    try:
        number = Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def classify_source_value(row, key):
    if key not in row:
        return "NOT_PROVIDED_BY_SOURCE", None, None
    value = row[key]
    if value is None:
        return "NULL", None, value
    if isinstance(value, str) and (value.strip() == "" or value.strip() == "--"):
        return "MISSING", None, value
    numeric = _as_decimal(value)
    if numeric is None:
        return "INVALID_VALUE", None, value
    if numeric < 0:
        return "INVALID_NEGATIVE", None, value
    normalized = str(numeric)
    if numeric == 0:
        return "EXPLICIT_ZERO", normalized, value
    return "VALID_POSITIVE", normalized, value


def _expiration(group, row):
    candidates = [group, row.get("expiryDate"), row.get("expirationDate")]
    formats = ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y")
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        for fmt in formats:
            try:
                return datetime.strptime(candidate.strip(), fmt).date().isoformat()
            except ValueError:
                pass
    return None


def _root(row, expected_symbol):
    explicit = row.get("root")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().upper()
    url = row.get("drillDownURL")
    if isinstance(url, str):
        slug = url.rstrip("/").split("/")[-1]
        # Nasdaq drill-down URLs may prefix the OSI root with a display path
        # segment (for example ``spy-b1spy--261120c00500000``).
        before_expiry = slug.split("--", 1)[0]
        if "-" in before_expiry:
            before_expiry = before_expiry.rsplit("-", 1)[-1]
        if re.fullmatch(r"[A-Za-z0-9.]+", before_expiry):
            return before_expiry.upper()
        match = re.fullmatch(r"([A-Za-z0-9.]+?)-+(\d{6}[cCpP]\d{8})", slug)
        if match:
            return match.group(1).upper()
    return None


def _root_class(root, expected):
    if not root:
        return "UNKNOWN"
    if root == expected:
        return "STANDARD"
    if root.startswith(expected) and re.fullmatch(r"[A-Z0-9]{1,2}", root[len(expected):]):
        return "ADJUSTED"
    if root.endswith(expected) and re.fullmatch(r"[A-Z0-9]{1,2}", root[:-len(expected)]):
        return "ADJUSTED"
    return "MISMATCH"


def _identifier_status(option_symbol, expiry, strike, side):
    if not option_symbol:
        return "NOT_PROVIDED_BY_SOURCE"
    compact = re.sub(r"\s+", "", option_symbol).upper()
    match = re.fullmatch(r"([A-Z0-9.]{1,6})(\d{6})([CP])(\d{8})", compact)
    if not match:
        return "INVALID"
    yy, mm, dd = int(match.group(2)[:2]), int(match.group(2)[2:4]), int(match.group(2)[4:6])
    try:
        identifier_expiry = datetime(2000 + yy, mm, dd).date().isoformat()
    except ValueError:
        return "INVALID"
    strike_value = _as_decimal(strike)
    if strike_value is None:
        return "INVALID"
    expected_strike = int(strike_value * 1000)
    if identifier_expiry != expiry or match.group(3) != ("C" if side == "CALL" else "P") or int(match.group(4)) != expected_strike:
        return "INVALID"
    return "VALID"


def _contract_record(symbol, side, source, expiry, row_index, issues):
    field_map = SOURCE_FIELDS[side]
    root = _root(source, symbol)
    strike_status, strike, strike_raw = classify_source_value(source, "strike")
    if strike_status not in ("EXPLICIT_ZERO", "VALID_POSITIVE"):
        issues.append(f"INVALID_STRIKE:{row_index}:{side}:{strike_status}")
    option_key = field_map["option_symbol"]
    option_symbol = source.get(option_key) if isinstance(source.get(option_key), str) and source.get(option_key).strip() not in ("", "--") else None
    identifier_status = _identifier_status(option_symbol, expiry, strike, side)
    source_values = {}
    normalized = {}
    source_values["strike"] = {"source_key": "strike" if "strike" in source else "strikePrice", "availability": strike_status, "raw_value": strike_raw}
    source_values["expiration"] = {"source_key": "expirygroup/expiryDate/expirationDate", "availability": "PROVIDED" if expiry else "MISSING", "raw_value": source.get("expirygroup", source.get("expiryDate", source.get("expirationDate")))}
    source_values["root"] = {"source_key": "root/drillDownURL", "availability": "PROVIDED" if root else "MISSING", "raw_value": source.get("root", source.get("drillDownURL"))}
    source_values["side"] = {"source_key": "c_/p_ source field family", "availability": "INFERRED_FROM_SOURCE_FIELD_FAMILY", "raw_value": side}
    for name, key in field_map.items():
        if name in ("option_symbol", "quote_timestamp"):
            if key not in source:
                availability = "NOT_PROVIDED_BY_SOURCE"
            elif source[key] is None:
                availability = "NULL"
            elif isinstance(source[key], str) and not source[key].strip():
                availability = "MISSING"
            else:
                availability = "PROVIDED"
            source_values[name] = {
                "source_key": key,
                "availability": availability,
                "raw_value": source.get(key),
            }
            normalized[name] = source.get(key) if key in source else None
            continue
        state, value, raw_value = classify_source_value(source, key)
        source_values[name] = {"source_key": key, "availability": state, "raw_value": raw_value}
        normalized[name] = value if state in ("EXPLICIT_ZERO", "VALID_POSITIVE") else None
    return {
        "underlying_symbol": symbol,
        "original_option_symbol": option_symbol,
        "contract_identifier": option_symbol,
        "contract_identifier_status": identifier_status,
        "root": root,
        "root_class": _root_class(root, symbol),
        "expiration": expiry,
        "strike": strike if strike_status in ("EXPLICIT_ZERO", "VALID_POSITIVE") else None,
        "strike_source_status": strike_status,
        "side": side,
        "volume": normalized["volume"],
        "volume_source_status": source_values["volume"]["availability"],
        "open_interest": normalized["open_interest"],
        "open_interest_source_status": source_values["open_interest"]["availability"],
        "bid": normalized["bid"],
        "bid_source_status": source_values["bid"]["availability"],
        "ask": normalized["ask"],
        "ask_source_status": source_values["ask"]["availability"],
        "last_price": normalized["last_price"],
        "last_price_source_status": source_values["last_price"]["availability"],
        "quote_timestamp": normalized["quote_timestamp"],
        "source_field_availability": source_values,
        "source_row_index": row_index,
    }


def parse_nasdaq_payload(raw, symbol="SPY"):
    if isinstance(raw, bytes):
        raw_bytes = raw
        try:
            root = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PayloadError("MALFORMED_JSON") from exc
    elif isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
        try:
            root = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PayloadError("MALFORMED_JSON") from exc
    elif isinstance(raw, dict):
        root = raw
        raw_bytes = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    else:
        raise PayloadError("UNSUPPORTED_PAYLOAD_TYPE")
    if not isinstance(root, dict):
        raise PayloadError("ROOT_NOT_OBJECT")
    status_obj = root.get("status")
    api_status = status_obj.get("rCode") if isinstance(status_obj, dict) else None
    if api_status != 200:
        raise PayloadError(f"NASDAQ_API_RCODE:{api_status}")
    data = root.get("data")
    table = data.get("table") if isinstance(data, dict) else None
    if not isinstance(data, dict):
        raise PayloadError("MISSING_DATA_OBJECT")
    if not isinstance(table, dict):
        raise PayloadError("MISSING_TABLE_OBJECT")
    rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(rows, list) or not rows:
        raise PayloadError("EMPTY_OR_MISSING_ROWS")

    def first_available_timestamp(keys):
        for source in (table, data, root):
            for key in keys:
                if key in source:
                    return source[key], key
        return None, None

    volume_asof_raw, volume_asof_key = first_available_timestamp(("volumeAsOf", "volumeAsOfTimestamp", "volume_as_of"))
    oi_asof_raw, oi_asof_key = first_available_timestamp(("openInterestAsOf", "openInterestAsOfTimestamp", "open_interest_as_of"))

    issues = []
    contracts = []
    current_expiration = None
    expiry_headers = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append(f"NON_OBJECT_ROW:{index}")
            continue
        header = row.get("expirygroup")
        if isinstance(header, str) and header.strip():
            current_expiration = _expiration(header, row)
            expiry_headers += 1
            if current_expiration is None:
                issues.append(f"INVALID_EXPIRATION_HEADER:{index}")
            continue
        if not any(key in row for key in ("strike", "strikePrice")):
            issues.append(f"UNCLASSIFIED_ROW:{index}")
            continue
        if "strike" not in row and "strikePrice" in row:
            row = {**row, "strike": row["strikePrice"]}
        expiration = current_expiration or _expiration(None, row)
        if expiration is None:
            issues.append(f"MISSING_OR_INVALID_EXPIRATION:{index}")
        side_seen = set()
        for side, fields in SOURCE_FIELDS.items():
            if any(key in row for key in fields.values()):
                side_seen.add(side)
                contracts.append(_contract_record(symbol.upper(), side, row, expiration, index, issues))
        if "CALL" not in side_seen:
            issues.append(f"MISSING_CALL_SIDE:{index}")
        if "PUT" not in side_seen:
            issues.append(f"MISSING_PUT_SIDE:{index}")

    reported = data.get("totalRecord")
    total_matches = None
    if reported is not None:
        try:
            total_matches = int(str(reported).replace(",", "")) == len(rows)
        except (ValueError, TypeError):
            total_matches = False
        if total_matches is False:
            issues.append("TOTAL_RECORD_MISMATCH")

    seen = set()
    for record in contracts:
        key = (record["root"], record["expiration"], record["strike"], record["side"])
        if key in seen:
            issues.append(f"DUPLICATE_CONTRACT:{key}")
        seen.add(key)
    if not contracts:
        issues.append("NO_CONTRACT_RECORDS")
    schema_ok = not any(issue.startswith(("NON_OBJECT_ROW", "UNCLASSIFIED_ROW", "INVALID_EXPIRATION_HEADER", "MISSING_OR_INVALID_EXPIRATION", "INVALID_STRIKE", "TOTAL_RECORD_MISMATCH", "DUPLICATE_CONTRACT", "NO_CONTRACT_RECORDS")) for issue in issues)
    parser_status = "VALID" if schema_ok and not issues else "PARTIAL" if contracts else "FAILED"
    return {
        "provider": "NASDAQ",
        "endpoint_identifier": "nasdaq.com/api/quote/{symbol}/option-chain?assetclass={assetclass}&limit=20000&fromdate=all",
        "requested_symbol": symbol.upper(),
        "http_status": None,
        "source_schema_version": root.get("schemaVersion") or (data.get("schemaVersion") if isinstance(data, dict) else None) or "UNDECLARED",
        "normalization_schema_version": SCHEMA_VERSION,
        "raw_payload_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "api_rcode": api_status,
        "provider_asof_raw": table.get("asOf") if isinstance(table, dict) else None,
        "volume_asof_raw": volume_asof_raw,
        "volume_asof_source_field": volume_asof_key,
        "open_interest_asof_raw": oi_asof_raw,
        "open_interest_asof_source_field": oi_asof_key,
        "underlying_last_trade_raw": data.get("lastTrade") if isinstance(data, dict) else None,
        "underlying_price_raw": data.get("lastTrade") if isinstance(data, dict) and "lastTrade" in data else None,
        "underlying_price_source_field": "lastTrade" if isinstance(data, dict) and "lastTrade" in data else None,
        "reported_row_count": reported,
        "source_row_count": len(rows),
        "expiry_header_count": expiry_headers,
        "parser_status": parser_status,
        "parser_issues": sorted(set(issues)),
        "records": contracts,
        "raw_retained": False,
    }


def apply_capture_metadata(parsed, http_status, captured_at_utc, session_date_et=None):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from .market_calendar import is_trading_day, session_close
    from .freshness import classify_freshness

    capture = datetime.fromisoformat(captured_at_utc.replace("Z", "+00:00"))
    if capture.tzinfo is None or capture.utcoffset() is None:
        raise ValueError("CAPTURE_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    capture_et = capture.astimezone(ZoneInfo("America/New_York"))
    trading_day = is_trading_day(capture_et.date())
    if trading_day is None:
        market_context = "CALENDAR_UNAVAILABLE"
    elif not trading_day:
        market_context = "MARKET_CLOSED_NON_SESSION"
    elif capture_et.time() < datetime.strptime("09:30", "%H:%M").time():
        market_context = "PRE_MARKET"
    elif capture_et.time() < session_close(capture_et.date()):
        market_context = "REGULAR_SESSION"
    else:
        market_context = "POST_MARKET"
    session = session_date_et or (capture_et.date().isoformat() if is_trading_day(capture_et.date()) is True else None)
    freshness = classify_freshness(http_status, captured_at_utc, session, parsed.get("provider_asof_raw"))
    volume_freshness = classify_freshness(http_status, captured_at_utc, session, parsed.get("volume_asof_raw"))
    oi_freshness = classify_freshness(http_status, captured_at_utc, session, parsed.get("open_interest_asof_raw"))
    metadata = {key: value for key, value in parsed.items() if key != "records"}
    metadata.update({
        "http_status": http_status,
        "request_method": "GET",
        "request_symbol": parsed.get("requested_symbol"),
        "scheduled_start_timestamp_utc": None,
        "actual_capture_timestamp_utc": capture.astimezone(ZoneInfo("UTC")).isoformat(),
        "capture_timestamp_utc": capture.astimezone(ZoneInfo("UTC")).isoformat(),
        "capture_timestamp_et": capture_et.isoformat(),
        "us_trading_session_date": session,
        "market_context": market_context,
        "market_calendar_year_coverage": [2026],
        "source_asof_timestamp_raw": parsed.get("provider_asof_raw"),
        "underlying_last_trade_timestamp_raw": parsed.get("underlying_last_trade_raw"),
        "parser_status": parsed.get("parser_status", "FAILED"),
        "freshness": freshness,
        "volume_freshness": volume_freshness,
        "open_interest_freshness": oi_freshness,
        "underlying_last_trade_freshness": "NOT_USED_AS_OPTION_CHAIN_FRESHNESS_PROOF",
        "data_quality_status": "STRUCTURE_ONLY" if parsed.get("parser_status") != "VALID" else "PENDING_QUALITY_EVALUATION",
    })
    return metadata
