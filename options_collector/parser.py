"""Offline-compatible parser for Nasdaq option-chain JSON (including real table row shape)."""
import json, re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo
from .registry import Symbol

@dataclass
class ParsedChain:
    symbol: str
    rows: list[dict[str, Any]]
    total_record: int | None
    total_record_scope: str
    raw_row_count: int
    expiry_groups: int
    schema_ok: bool
    issues: list[str]
    underlying_last_trade_raw: str | None = None
    underlying_price: str | None = None
    underlying_quote_time_et: str | None = None
    option_chain_timestamp: str | None = None


def parse_payload(raw: bytes | str | dict, item: Symbol) -> ParsedChain:
    try:
        root = raw if isinstance(raw, dict) else json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("INVALID_JSON") from exc
    data = root.get("data") if isinstance(root, dict) else None
    if not isinstance(data, dict):
        return ParsedChain(item.symbol, [], None, "unknown", 0, 0, False, ["DATA_OBJECT_MISSING"])
    table = data.get("table") or {}
    src_rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(src_rows, list):
        return ParsedChain(item.symbol, [], _int_or_none(data.get("totalRecord")), "raw_table_rows", 0, 0, False, ["ROWS_MISSING"])

    contracts: list[dict[str, Any]] = []
    expiry_groups = 0
    current_expiry = None
    issues: list[str] = []
    for index, source in enumerate(src_rows):
        if not isinstance(source, dict):
            issues.append(f"NON_OBJECT_ROW:{index}")
            continue
        expiry_header = source.get("expirygroup")
        if isinstance(expiry_header, str) and expiry_header.strip():
            current_expiry = expiry_header.strip()
            expiry_groups += 1
            continue
        strike = source.get("strike")
        # Backward compatibility with the synthetic WORK 04-C fixture schema.
        if strike is None and "strikePrice" in source:
            strike = source.get("strikePrice")
        if strike in (None, "", "--"):
            # Some non-Nasdaq fixtures use a separate date-only heading.
            heading = source.get("expiryDate") or source.get("expirationDate")
            if heading:
                current_expiry = str(heading)
                expiry_groups += 1
                continue
            issues.append(f"UNCLASSIFIED_ROW:{index}")
            continue
        row = dict(source)
        row["_source_row_index"] = index
        row["_expiry_group"] = current_expiry
        row["_expiration"] = _normalise_expiration(current_expiry, row.get("expiryDate"))
        row["_strike_raw"] = strike
        row["_strike_value"] = _positive_decimal(strike)
        row["_strike_valid"] = row["_strike_value"] is not None
        row["strikePrice"] = strike  # compatibility alias for the existing CSV writer
        row["_root"] = extract_root(source, item.symbol)
        row["_root_class"] = classify_root(row["_root"], item.expected_root)
        row["_route_side"] = extract_route_side(source.get("drillDownURL"))
        contracts.append(row)

    total = _int_or_none(data.get("totalRecord"))
    total_scope = "raw_table_rows"
    if total is None:
        total = _int_or_none(table.get("totalRecord"))
        total_scope = "contracts" if total is not None else "unknown"
    total_matches = (total == len(src_rows)) if total_scope == "raw_table_rows" else ((total == len(contracts)) if total_scope == "contracts" else None)
    if total is not None and not total_matches:
        issues.append("TOTAL_RECORD_RAW_ROWS_MISMATCH" if total_scope == "raw_table_rows" else "TOTAL_RECORD_CONTRACTS_MISMATCH")
    if not contracts:
        issues.append("EMPTY_CHAIN")
    if contracts and any(row.get("_expiry_group") is None for row in contracts):
        issues.append("CONTRACT_WITHOUT_EXPIRY_GROUP")
    quote = parse_last_trade(data.get("lastTrade"))
    schema_ok = not any(issue.startswith(("ROWS_MISSING", "DATA_OBJECT_MISSING", "TOTAL_RECORD_", "EMPTY_CHAIN", "UNCLASSIFIED_ROW")) for issue in issues)
    return ParsedChain(item.symbol, contracts, total, total_scope, len(src_rows), expiry_groups, schema_ok, issues,
                       data.get("lastTrade"), quote[0], quote[1], table.get("asOf") if isinstance(table, dict) else None)


def classify_root(root: str | None, expected_root: str) -> str:
    if not root:
        return "UNKNOWN"
    if root == expected_root:
        return "STANDARD"
    # OCC adjusted roots commonly retain the expected root plus a numeric or short alpha suffix.
    if root.startswith(expected_root) and re.fullmatch(r"[A-Z0-9]{1,2}", root[len(expected_root):]):
        return "ADJUSTED"
    return "UNKNOWN"

def extract_root(row: dict, expected_symbol: str | None = None) -> str | None:
    # Real Nasdaq rows put the call-route slug in drillDownURL, e.g. pltr--261120c00025000.
    url = row.get("drillDownURL")
    if isinstance(url, str):
        slug = url.rstrip("/").split("/")[-1]
        match = re.fullmatch(r"([A-Za-z0-9.]+?)-*(\d{6}[cCpP]\d{8})", slug)
        if match:
            return match.group(1).upper()
    # Keep support for OCC-style option symbols in offline fixtures.
    for key in ("c_Option", "p_Option", "option", "contractSymbol"):
        value = row.get(key)
        if not value:
            continue
        match = re.match(r"([A-Z]{1,6}\d{0,2})\s*\d{6}[CP]\d{8}", str(value))
        if match:
            return match.group(1)
    return None


def extract_route_side(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    match = re.search(r"\d{6}([cCpP])\d{8}$", url.rstrip("/").split("/")[-1])
    return match.group(1).upper() if match else None


def parse_last_trade(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, None
    match = re.search(r"LAST TRADE:\s*\$([\d,]+(?:\.\d+)?)\s*\(AS OF\s*([A-Z]{3}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)\s+ET\)", value, re.I)
    if not match:
        return None, None
    try:
        stamp = datetime.strptime(match.group(2).upper(), "%b %d, %Y %I:%M %p").replace(tzinfo=ZoneInfo("America/New_York"))
        return match.group(1).replace(",", ""), stamp.isoformat()
    except ValueError:
        return None, None


def _normalise_expiration(group: Any, row_expiry: Any) -> str | None:
    if not isinstance(group, str):
        return None
    try:
        return datetime.strptime(group, "%B %d, %Y").date().isoformat()
    except ValueError:
        pass
    if isinstance(row_expiry, str):
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(row_expiry, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def _positive_decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value).replace(",", "").replace("$", "").strip())
        return parsed if parsed.is_finite() and parsed > 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).replace(",", "")) if value is not None else None
    except (ValueError, TypeError):
        return None
