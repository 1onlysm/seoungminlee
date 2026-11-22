"""Bounded, offline import adapters for explicitly documented options files.

No network access is performed. Input bytes are treated as user-supplied evidence,
not as verified provider coverage.
"""
import csv
import hashlib
import io
import json
import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from . import SCHEMA_VERSION
from .contract import PayloadError, parse_nasdaq_payload
from .freshness import classify_freshness
from .market_calendar import is_trading_day
from .quality import assess_quality
from .storage import StorageError, _verify_snapshot, write_snapshot

IMPORT_SCHEMA_VERSION = "navi-options-import/1.0.0"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_CONTRACTS = 100_000
MAX_JSON_DEPTH = 32
ET = ZoneInfo("America/New_York")
FIELDS = (
    "underlying_symbol", "expiration", "strike", "side", "option_symbol",
    "contract_identifier", "root", "volume", "open_interest", "bid", "ask",
    "last_price", "quote_timestamp", "source_asof_timestamp",
    "implied_volatility", "delta", "gamma", "theta", "vega", "rho",
    "contract_multiplier",
)
REQUIRED = ("underlying_symbol", "expiration", "strike", "side")
OPTIONAL_NUMERIC = (
    "volume", "open_interest", "bid", "ask", "last_price", "implied_volatility",
    "delta", "gamma", "theta", "vega", "rho", "contract_multiplier",
)
ALLOWED_JSON_KEYS = {"schema_version", "source", "source_asof_timestamp", "capture_timestamp_utc", "session_date", "contracts"}


class ImportError(ValueError):
    """Stable, user-displayable import failure."""


def _depth(value, level=0):
    if level > MAX_JSON_DEPTH:
        raise ImportError("JSON_DEPTH_LIMIT_EXCEEDED")
    if isinstance(value, dict):
        for child in value.values():
            _depth(child, level + 1)
    elif isinstance(value, list):
        for child in value:
            _depth(child, level + 1)


def _aware(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _date(value):
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _availability(row, field):
    if field not in row:
        return "NOT_PROVIDED_BY_SOURCE"
    value = row[field]
    if value is None:
        return "NULL"
    if isinstance(value, str) and value.strip() in ("", "--", "N/A", "null", "NULL"):
        return "MISSING"
    if field in OPTIONAL_NUMERIC or field == "strike":
        number = _decimal(value)
        if number is None:
            return "INVALID_VALUE"
        if number < 0:
            return "INVALID_NEGATIVE"
        return "EXPLICIT_ZERO" if number == 0 else "VALID_POSITIVE"
    return "PROVIDED"


def _normalize_record(row, index):
    absent = [name for name in REQUIRED if name not in row or row[name] is None or str(row[name]).strip() == ""]
    if absent:
        raise ImportError(f"REQUIRED_FIELD_MISSING:{index}:{','.join(absent)}")
    symbol = str(row["underlying_symbol"]).strip().upper()
    if not re.fullmatch(r"[A-Z0-9.]{1,15}", symbol):
        raise ImportError(f"INVALID_UNDERLYING_SYMBOL:{index}")
    expiration = _date(row["expiration"])
    if expiration is None:
        raise ImportError(f"INVALID_EXPIRATION:{index}")
    side_raw = str(row["side"]).strip().upper()
    side = {"C": "CALL", "CALL": "CALL", "P": "PUT", "PUT": "PUT"}.get(side_raw)
    if side is None:
        raise ImportError(f"INVALID_CALL_PUT_SIDE:{index}")
    strike_number = _decimal(row["strike"])
    if strike_number is None or strike_number <= 0:
        raise ImportError(f"INVALID_STRIKE:{index}")

    source = {}
    normalized = {}
    for field in FIELDS:
        availability = _availability(row, field)
        source[field] = {"source_key": field, "availability": availability, "raw_value": row.get(field)}
        if field in OPTIONAL_NUMERIC or field == "strike":
            number = _decimal(row.get(field))
            normalized[field] = str(number) if number is not None and number >= 0 else None
        else:
            normalized[field] = row.get(field) if field in row else None
    option_symbol = normalized["option_symbol"]
    contract_id = normalized["contract_identifier"] or option_symbol
    if contract_id is not None:
        contract_id = str(contract_id).strip() or None
    root = normalized["root"]
    if root is not None:
        root = str(root).strip().upper() or None
    return {
        "underlying_symbol": symbol,
        "original_option_symbol": option_symbol,
        "contract_identifier": contract_id,
        "contract_identifier_status": "PROVIDED" if contract_id else "NOT_PROVIDED_BY_SOURCE",
        "root": root,
        "root_class": "STANDARD" if root == symbol else "UNKNOWN" if not root else "ADJUSTED_OR_UNVERIFIED",
        "expiration": expiration,
        "strike": str(strike_number),
        "side": side,
        **{field: normalized[field] for field in OPTIONAL_NUMERIC},
        "volume_source_status": source["volume"]["availability"],
        "open_interest_source_status": source["open_interest"]["availability"],
        "bid_source_status": source["bid"]["availability"],
        "ask_source_status": source["ask"]["availability"],
        "last_price_source_status": source["last_price"]["availability"],
        "quote_timestamp": normalized["quote_timestamp"],
        "source_asof_timestamp": normalized["source_asof_timestamp"],
        "source_field_availability": source,
        "source_row_index": index,
    }


def _check_duplicates(records):
    seen = set()
    for record in records:
        key = (record["underlying_symbol"], record["root"] or "", record["expiration"], record["strike"], record["side"])
        if key in seen:
            raise ImportError("DUPLICATE_CONTRACT_KEY")
        seen.add(key)


def _parse_csv(text):
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = reader.fieldnames or []
    if len(headers) != len(set(headers)):
        raise ImportError("DUPLICATE_CSV_HEADER")
    allowed = set(FIELDS) | {"schema_version"}
    unknown = set(headers) - allowed
    missing = set(REQUIRED) - set(headers)
    if unknown:
        raise ImportError(f"UNSUPPORTED_CSV_COLUMNS:{','.join(sorted(unknown))}")
    if missing:
        raise ImportError(f"REQUIRED_COLUMNS_MISSING:{','.join(sorted(missing))}")
    if "schema_version" not in headers:
        raise ImportError("SCHEMA_VERSION_COLUMN_REQUIRED")
    rows = []
    for index, row in enumerate(reader, start=2):
        if None in row:
            raise ImportError(f"CSV_ROW_WIDTH_MISMATCH:{index}")
        if not any(value not in (None, "") for value in row.values()):
            continue
        if row.get("schema_version") != IMPORT_SCHEMA_VERSION:
            raise ImportError(f"UNSUPPORTED_SCHEMA_VERSION:{index}")
        rows.append({key: value for key, value in row.items() if key != "schema_version" and value is not None})
        if len(rows) > MAX_CONTRACTS:
            raise ImportError("CONTRACT_LIMIT_EXCEEDED")
    if not rows:
        raise ImportError("EMPTY_FILE")
    return rows, {"source": "USER_SUPPLIED_CSV", "source_asof_timestamp": None, "session_date": None}, "CSV"


def _parse_json(text):
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportError("MALFORMED_JSON") from exc
    _depth(envelope)
    if not isinstance(envelope, dict):
        raise ImportError("JSON_ROOT_NOT_OBJECT")
    # Explicit adapter for a saved Nasdaq option-chain payload. This parses bytes
    # offline and does not imply that capture, use, or retention is authorized.
    if isinstance(envelope.get("status"), dict) and "data" in envelope:
        data = envelope.get("data") or {}
        nasdaq_symbol = data.get("symbol") if isinstance(data, dict) else None
        if not nasdaq_symbol and isinstance(data, dict):
            table = data.get("table") or {}
            rows = table.get("rows") if isinstance(table, dict) else None
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    option = row.get("c_Option") or row.get("p_Option")
                    if isinstance(option, str):
                        match = re.match(r"\s*([A-Za-z0-9.]{1,15})\s+\d{6}[CPcp]\d{8}", option)
                        if match:
                            nasdaq_symbol = match.group(1)
                            break
        if not isinstance(nasdaq_symbol, str) or not re.fullmatch(r"[A-Za-z0-9.]{1,15}", nasdaq_symbol):
            raise ImportError("NASDAQ_SYMBOL_NOT_IDENTIFIABLE_FROM_FILE")
        try:
            parsed = parse_nasdaq_payload(envelope, nasdaq_symbol)
        except PayloadError as exc:
            raise ImportError(f"NASDAQ_SCHEMA_INVALID:{exc}") from exc
        rows = []
        for item in parsed["records"]:
            rows.append({
                "underlying_symbol": item["underlying_symbol"], "expiration": item["expiration"],
                "strike": item["strike"], "side": item["side"], "option_symbol": item["original_option_symbol"],
                "contract_identifier": item["contract_identifier"], "root": item["root"],
                "volume": item["volume"], "open_interest": item["open_interest"], "bid": item["bid"],
                "ask": item["ask"], "last_price": item["last_price"], "quote_timestamp": item["quote_timestamp"],
            })
        return rows, {"source": "USER_SUPPLIED_NASDAQ_JSON", "source_asof_timestamp": parsed.get("provider_asof_raw"), "session_date": None}, "NASDAQ_JSON"
    unknown = set(envelope) - ALLOWED_JSON_KEYS
    if unknown:
        raise ImportError(f"UNSUPPORTED_JSON_KEYS:{','.join(sorted(unknown))}")
    if envelope.get("schema_version") != IMPORT_SCHEMA_VERSION:
        raise ImportError("UNSUPPORTED_SCHEMA_VERSION")
    contracts = envelope.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        raise ImportError("EMPTY_OR_INVALID_CONTRACTS")
    if len(contracts) > MAX_CONTRACTS:
        raise ImportError("CONTRACT_LIMIT_EXCEEDED")
    if not all(isinstance(row, dict) for row in contracts):
        raise ImportError("CONTRACT_ROW_NOT_OBJECT")
    for index, row in enumerate(contracts):
        extra = set(row) - set(FIELDS)
        if extra:
            raise ImportError(f"UNSUPPORTED_CONTRACT_FIELDS:{index}:{','.join(sorted(extra))}")
    return contracts, envelope, "JSON"


def import_file(file_path, output_dir, *, import_time=None):
    """Validate and persist one CSV/JSON file. Returns a verified snapshot summary."""
    path = Path(file_path)
    if path.is_symlink() or not path.is_file():
        raise ImportError("INPUT_NOT_REGULAR_FILE")
    if path.stat().st_size <= 0:
        raise ImportError("EMPTY_FILE")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ImportError("FILE_SIZE_LIMIT_EXCEEDED")
    suffix = path.suffix.lower()
    if suffix not in (".csv", ".json"):
        raise ImportError("UNSUPPORTED_FILE_FORMAT")
    # Read at most one byte beyond the configured cap even if the file changes
    # between stat and read, keeping allocation bounded against TOCTOU growth.
    with path.open("rb") as handle:
        payload = handle.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        raise ImportError("FILE_SIZE_LIMIT_EXCEEDED")
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ImportError("INVALID_ENCODING_UTF8_REQUIRED") from exc
    if not text.strip():
        raise ImportError("EMPTY_FILE")
    rows, envelope, source_type = _parse_csv(text) if suffix == ".csv" else _parse_json(text)
    if len(rows) > MAX_CONTRACTS:
        raise ImportError("CONTRACT_LIMIT_EXCEEDED")
    records = [_normalize_record(row, index) for index, row in enumerate(rows)]
    symbols = {record["underlying_symbol"] for record in records}
    if len(symbols) != 1:
        raise ImportError("MIXED_UNDERLYING_SYMBOLS_UNSUPPORTED")
    _check_duplicates(records)
    expired = False

    imported = import_time or datetime.now(timezone.utc)
    if isinstance(imported, str):
        imported = _aware(imported)
    if imported is None or imported.tzinfo is None or imported.utcoffset() is None:
        raise ImportError("IMPORT_TIMESTAMP_MUST_BE_AWARE")
    imported = imported.astimezone(timezone.utc)
    imported_utc = imported.isoformat().replace("+00:00", "Z")
    imported_et = imported.astimezone(ET).isoformat()
    source_asof = envelope.get("source_asof_timestamp")
    if source_asof is None:
        provided = {record.get("source_asof_timestamp") for record in records if record.get("source_asof_timestamp")}
        if len(provided) > 1:
            raise ImportError("MULTIPLE_SOURCE_ASOF_TIMESTAMPS_UNSUPPORTED")
        source_asof = next(iter(provided), None)
    source_dt = _aware(source_asof)
    if source_asof not in (None, "") and source_dt is None:
        raise ImportError("INVALID_SOURCE_ASOF_TIMESTAMP")
    session = envelope.get("session_date")
    if session and _date(session) is None:
        raise ImportError("INVALID_SESSION_DATE")
    if session:
        session = _date(session)
    elif source_dt:
        session = source_dt.astimezone(ET).date().isoformat()
    calendar_ok = is_trading_day(date.fromisoformat(session)) is True if session else False
    if not calendar_ok:
        session = "unknown-session"
    elif any(record["expiration"] < session for record in records):
        expired = True
    source_capture = envelope.get("capture_timestamp_utc")
    source_capture_dt = _aware(source_capture)
    if source_capture not in (None, "") and source_capture_dt is None:
        raise ImportError("INVALID_SOURCE_CAPTURE_TIMESTAMP")
    timestamp_assessment = None
    if source_asof is None:
        freshness = {"status": "SOURCE_TIME_UNAVAILABLE", "reason": "SOURCE_ASOF_NOT_PROVIDED", "source_asof_et": None}
    elif source_capture_dt is None:
        freshness = {"status": "UNVERIFIED", "reason": "SOURCE_CAPTURE_TIME_UNAVAILABLE_IMPORT_TIME_IS_NOT_CAPTURE_TIME", "source_asof_et": None}
    else:
        timestamp_assessment = classify_freshness(200, source_capture_dt.isoformat(), session if session != "unknown-session" else None, source_asof)
        freshness = {"status": "UNVERIFIED", "reason": "USER_SUPPLIED_SOURCE_TIMESTAMPS_NOT_INDEPENDENTLY_VERIFIED",
                     "source_asof_et": timestamp_assessment.get("source_asof_et"),
                     "claimed_timestamp_assessment": timestamp_assessment}
    structural_issues = []
    if expired:
        structural_issues.append("EXPIRED_CONTRACT_PRESENT")
    optional_invalid = sum(1 for record in records for field in OPTIONAL_NUMERIC if record["source_field_availability"][field]["availability"] in ("INVALID_NEGATIVE", "INVALID_VALUE"))
    if optional_invalid:
        structural_issues.append("INVALID_OPTIONAL_NUMERIC_VALUES")
    by_side = {side: [record for record in records if record["side"] == side] for side in ("CALL", "PUT")}
    if not by_side["CALL"] or not by_side["PUT"]:
        structural_issues.append("CALL_OR_PUT_SIDE_MISSING")
    structural = "INVALID" if expired else "PARTIAL" if structural_issues else "VALID"
    missing_required_source = any(not record.get("contract_identifier") for record in records)
    field_coverage = {}
    for field in ("volume", "open_interest", "bid", "ask"):
        present = sum(record["source_field_availability"][field]["availability"] in ("EXPLICIT_ZERO", "VALID_POSITIVE") for record in records)
        coverage_pct = round(100 * present / len(records), 4)
        field_coverage[field] = {"valid_count": present, "eligible_count": len(records), "coverage_percentage": coverage_pct,
                                 "missing_percentage": round(100 - coverage_pct, 4)}
    quality_status = "BLOCKED" if structural == "INVALID" else "PROVISIONAL_AVAILABLE" if all(by_side.values()) else "LIMITED"
    if freshness["status"] in ("SOURCE_TIME_UNAVAILABLE", "UNVERIFIED", "STALE", "RECENT_NOT_CURRENT") or any(field_coverage[f]["coverage_percentage"] < 100 for f in ("volume", "open_interest")) or missing_required_source:
        quality_status = "LIMITED" if structural != "INVALID" else "BLOCKED"

    metadata = {
        "provider": str(envelope.get("source") or source_type),
        "endpoint_identifier": "USER_SUPPLIED_FILE" if source_type != "NASDAQ_JSON" else "NASDAQ_SAVED_OPTION_CHAIN_JSON",
        "requested_symbol": next(iter(symbols)),
        "capture_timestamp_utc": source_capture_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if source_capture_dt else None,
        "capture_timestamp_et": source_capture_dt.astimezone(ET).isoformat() if source_capture_dt else None,
        "import_timestamp_utc": imported_utc,
        "import_timestamp_et": imported_et,
        "us_trading_session_date": session,
        "provider_asof_timestamp": source_asof,
        "source_schema_version": IMPORT_SCHEMA_VERSION if source_type != "NASDAQ_JSON" else "NASDAQ_PAYLOAD_SCHEMA_UNDECLARED_OR_PROVIDER",
        "normalization_schema_version": SCHEMA_VERSION,
        "raw_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "http_status": None,
        "parser_status": "VALID" if structural != "INVALID" else "PARTIAL",
        "data_quality_status": quality_status,
        "freshness": freshness,
        "claimed_timestamp_assessment": timestamp_assessment,
        "volume_freshness": {"status": "SOURCE_TIME_UNAVAILABLE", "reason": "MANUAL_IMPORT_HAS_NO_VERIFIED_VOLUME_ASOF"},
        "open_interest_freshness": {"status": "SOURCE_TIME_UNAVAILABLE", "reason": "MANUAL_IMPORT_HAS_NO_VERIFIED_OI_ASOF"},
        "evidence_kind": "USER_SUPPLIED_FILE_NOT_INDEPENDENTLY_VERIFIED",
        "import_id": f"{imported.strftime('%Y%m%dT%H%M%S%fZ')}-{hashlib.sha256(payload).hexdigest()[:12]}",
        "source_filename": path.name[:255],
        "source_type": source_type,
        "file_sha256": hashlib.sha256(payload).hexdigest(),
        "structural_quality": structural,
        "research_usability": quality_status,
        "field_coverage": field_coverage,
        "structural_issues": structural_issues,
        "raw_file_retained": False,
        "imported_market_data_not_independently_verified": True,
    }
    # The pre-existing quality engine is retained as a detailed field audit; its
    # live freshness gates are intentionally not represented as passed here.
    quality = assess_quality({**metadata, "parser_status": "PARTIAL" if structural == "INVALID" else "VALID", "parser_issues": structural_issues}, records)
    quality.update({
        "structural_quality": structural,
        "freshness": freshness,
        "research_usability": quality_status,
        "import_field_coverage": field_coverage,
        "analytics_provenance": "USER_SUPPLIED_OFFLINE_FILE; NOT VERIFIED MARKET COVERAGE",
    })
    analytics = _analytics(records, field_coverage, structural, quality_status)
    quality["provisional_analytics"] = analytics
    try:
        directory = write_snapshot(output_dir, metadata, records, quality,
                                   error_report={"status": "IMPORTED_OFFLINE", "errors": structural_issues},
                                   raw_payload=None, raw_retention_permitted=False,
                                   capture_id=metadata["import_id"])
    except StorageError as exc:
        raise ImportError(str(exc)) from exc
    return {"snapshot_path": str(directory), "import_id": metadata["import_id"], "symbol": metadata["requested_symbol"],
            "record_count": len(records), "file_sha256": metadata["file_sha256"], "structural_quality": structural,
            "freshness": freshness, "research_usability": quality_status, "analytics": analytics}


def read_import_snapshot(snapshot_path):
    """Read an import snapshot after verifying all stored file hashes/schema."""
    directory = Path(snapshot_path)
    manifest = _verify_snapshot(directory)
    values = {}
    for filename, key in (("normalized_records.json", "records"), ("quality_report.json", "quality"), ("error_report.json", "errors")):
        values[key] = json.loads((directory / filename).read_text(encoding="utf-8"))
    return {"manifest": manifest, **values}


def _analytics(records, coverage, structural, usability):
    """Observed-only calculations. Missing values remain in denominators/warnings."""
    totals = {}
    for field in ("volume", "open_interest"):
        totals[field] = {}
        for side in ("CALL", "PUT"):
            eligible = [row for row in records if row["side"] == side]
            values = [Decimal(row[field]) for row in eligible if row.get(field) is not None and row["source_field_availability"][field]["availability"] in ("EXPLICIT_ZERO", "VALID_POSITIVE")]
            coverage_pct = round(100 * len(values) / len(eligible), 4) if eligible else 0.0
            totals[field][side] = {"observed_total": str(sum(values, Decimal(0))), "valid_count": len(values), "eligible_count": len(eligible),
                                   "coverage_percentage": coverage_pct, "missing_percentage": round(100 - coverage_pct, 4) if eligible else 100.0}
    ratios = {}
    for field, name in (("volume", "observed_volume_pcr"), ("open_interest", "observed_oi_pcr")):
        call = Decimal(totals[field]["CALL"]["observed_total"])
        put = Decimal(totals[field]["PUT"]["observed_total"])
        ratios[name] = {"value": str(put / call) if call > 0 else None,
                        "status": "PROVISIONAL" if call > 0 and totals[field]["CALL"]["eligible_count"] and totals[field]["PUT"]["eligible_count"] else "BLOCKED",
                        "reason": "OBSERVED_VALUES_ONLY" if call > 0 else "CALL_OBSERVED_TOTAL_ZERO_OR_SIDE_MISSING",
                        "coverage": {side: {"coverage_percentage": totals[field][side]["coverage_percentage"],
                                             "missing_percentage": totals[field][side]["missing_percentage"]} for side in ("CALL", "PUT")}}
    concentration = {}
    for field in ("volume", "open_interest"):
        by_strike, by_expiration = {}, {}
        for row in records:
            value = row.get(field)
            if value is None or row["source_field_availability"][field]["availability"] not in ("EXPLICIT_ZERO", "VALID_POSITIVE"):
                continue
            key = f"{row['side']}:{row['strike']}"
            exp_key = f"{row['side']}:{row['expiration']}"
            by_strike[key] = str(Decimal(by_strike.get(key, "0")) + Decimal(value))
            by_expiration[exp_key] = str(Decimal(by_expiration.get(exp_key, "0")) + Decimal(value))
        concentration[field] = {"by_side_and_strike": by_strike, "by_side_and_expiration": by_expiration,
                                "status": "PROVISIONAL_OBSERVED_CONCENTRATION", "coverage": coverage[field]}
    complete_oi = all(totals["open_interest"][side]["eligible_count"] > 0 and totals["open_interest"][side]["coverage_percentage"] == 100 for side in ("CALL", "PUT"))
    multipliers = {row.get("contract_multiplier") for row in records}
    max_pain = {"status": "BLOCKED", "value": None}
    if structural == "INVALID":
        max_pain["reason"] = "STRUCTURAL_QUALITY_INVALID"
    elif not complete_oi:
        max_pain["reason"] = "OPEN_INTEREST_INPUT_INCOMPLETE"
    elif any(value is None for value in multipliers) or len(multipliers) != 1:
        max_pain["reason"] = "CONTRACT_MULTIPLIER_UNAVAILABLE_OR_INCONSISTENT"
    else:
        candidates = sorted({Decimal(row["strike"]) for row in records})
        multiplier = Decimal(next(iter(multipliers)))
        payouts = {}
        for settlement in candidates:
            payout = Decimal(0)
            for row in records:
                strike, oi = Decimal(row["strike"]), Decimal(row["open_interest"])
                if row["side"] == "CALL" and settlement > strike:
                    payout += (settlement - strike) * oi * multiplier
                elif row["side"] == "PUT" and settlement < strike:
                    payout += (strike - settlement) * oi * multiplier
            payouts[str(settlement)] = str(payout)
        min_payout = min(Decimal(v) for v in payouts.values())
        max_pain = {"status": "PROVISIONAL", "value": str(min(Decimal(k) for k, v in payouts.items() if Decimal(v) == min_payout)),
                    "reason": "COMPLETE_OBSERVED_OI_AND_EXPLICIT_MULTIPLIER", "payout_by_settlement": payouts}
    return {"status": "PROVISIONAL_ONLY", "put_call_ratios": ratios, "observed_totals": totals,
            "concentration": concentration, "max_pain": max_pain,
            "iv_greeks": {"status": "SOURCE_VALUES_ONLY", "calculated": False,
                          "fields": {name: sum(row.get(name) is not None for row in records) for name in ("implied_volatility", "delta", "gamma", "theta", "vega", "rho")}},
            "warnings": ["USER_SUPPLIED_FILE_NOT_INDEPENDENTLY_VERIFIED", "NO_COMPLETE_MARKET_COVERAGE_CLAIM", f"RESEARCH_USABILITY_{usability}"]}

