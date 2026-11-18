"""Strict, rights-gated importer for the NAVI NVDA HV bridge artifact.

No authorization is inferred from fields inside the JSON payload. Callers must
provide independent, current rights evidence before an artifact is accepted.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
import re
from typing import Any


SCHEMA_VERSION = "1.0"
ARTIFACT_TYPE = "NAVI_NVDA_HV_RESEARCH"
EXPECTED_FIELDS = {
    "schema_version", "artifact_type", "symbol", "provider", "price_field",
    "adjustment_basis", "as_of_session", "observations", "formula_id",
    "hv", "annualization_sessions", "standard_deviation_ddof", "status",
    "rights_status", "raw_ohlcv_included", "token_included", "integrity",
}
FORBIDDEN_KEYS = {"open", "high", "low", "close", "adjclose", "volume", "ohlcv",
                  "rows", "raw_ohlcv", "rawohlcv", "daily_returns", "returns", "api_key", "token",
                  "authorization", "headers", "account_id"}
FORMULA_ID = "LOG_RETURN_SAMPLE_SD_DDOF1_SQRT252_V1"


class HVImportError(ValueError):
    """Machine-readable bridge rejection reason."""


def _contains_forbidden(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in {re.sub(r"[^a-z0-9]", "", k) for k in FORBIDDEN_KEYS}:
                return True
            if _contains_forbidden(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden(child) for child in value)
    return False


def _canonical(payload: dict) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "integrity"}
    return json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def payload_sha256(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _valid_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def validate_hv_artifact(payload_or_json: dict | str | bytes, *,
                         rights_evidence: dict | None = None,
                         today: date | None = None,
                         max_age_days: int = 5) -> dict:
    """Validate a payload and return normalized research values.

    rights_evidence is a separate trusted input from the local operator, not
    payload metadata. Unknown or missing evidence always denies import.
    """
    try:
        if isinstance(payload_or_json, bytes):
            payload = json.loads(payload_or_json.decode("utf-8"))
        elif isinstance(payload_or_json, str):
            payload = json.loads(payload_or_json)
        else:
            payload = payload_or_json
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HVImportError("MALFORMED_JSON") from exc
    if not isinstance(payload, dict):
        raise HVImportError("ROOT_MUST_BE_OBJECT")
    if _contains_forbidden(payload):
        raise HVImportError("FORBIDDEN_RAW_OR_CREDENTIAL_FIELD")
    if set(payload) != EXPECTED_FIELDS:
        raise HVImportError("SCHEMA_FIELDS_MISMATCH")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise HVImportError("UNSUPPORTED_SCHEMA_VERSION")
    if payload["artifact_type"] != ARTIFACT_TYPE or payload["symbol"] != "NVDA":
        raise HVImportError("ARTIFACT_OR_SYMBOL_MISMATCH")
    if payload["provider"] != "TIINGO_EOD" or payload["price_field"] != "adjClose":
        raise HVImportError("PROVIDER_OR_PRICE_FIELD_MISMATCH")
    if payload["adjustment_basis"] != "SPLIT_AND_DIVIDEND_ADJUSTED":
        raise HVImportError("ADJUSTMENT_BASIS_INVALID")
    if payload["formula_id"] != FORMULA_ID:
        raise HVImportError("CALCULATION_METHOD_INVALID")
    if payload["annualization_sessions"] != 252 or payload["standard_deviation_ddof"] != 1:
        raise HVImportError("CALCULATION_PARAMETERS_INVALID")
    if payload["status"] != "PROVISIONAL":
        raise HVImportError("PRODUCTION_STATUS_NOT_ALLOWED")
    if payload["rights_status"] != "AUTHORIZED" or payload["raw_ohlcv_included"] is not False or payload["token_included"] is not False:
        raise HVImportError("DECLARED_RIGHTS_OR_SAFETY_FLAGS_INVALID")
    if not _valid_iso_date(payload["as_of_session"]):
        raise HVImportError("INVALID_AS_OF_DATE")
    observations = payload["observations"]
    if isinstance(observations, bool) or not isinstance(observations, int) or not 61 <= observations <= 260:
        raise HVImportError("INVALID_OBSERVATION_COUNT")
    hv = payload["hv"]
    if not isinstance(hv, dict) or set(hv) != {"hv10", "hv20", "hv30", "hv60"}:
        raise HVImportError("HV_FIELDS_INVALID")
    for name, value in hv.items():
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise HVImportError("HV_VALUE_INVALID:" + name)
    integrity = payload["integrity"]
    if not isinstance(integrity, dict) or set(integrity) != {"algorithm", "sha256"} or integrity.get("algorithm") != "SHA-256":
        raise HVImportError("INTEGRITY_METADATA_INVALID")
    if not re.fullmatch(r"[0-9a-f]{64}", str(integrity.get("sha256", ""))) or integrity["sha256"] != payload_sha256(payload):
        raise HVImportError("PAYLOAD_INTEGRITY_FAILED")
    # Never trust the payload's rights_status as proof. Require independent evidence.
    if not isinstance(rights_evidence, dict) or rights_evidence.get("verified") is not True or \
       rights_evidence.get("provider") != "TIINGO" or \
       rights_evidence.get("scope") != "PERSONAL_CROSS_PROJECT_DERIVED_METRICS" or \
       not isinstance(rights_evidence.get("evidence_ref"), str) or not rights_evidence["evidence_ref"].strip():
        raise HVImportError("RIGHTS_AUTHORIZATION_EVIDENCE_REQUIRED")
    current = today or datetime.now(timezone.utc).date()
    as_of = date.fromisoformat(payload["as_of_session"])
    age = (current - as_of).days
    if age < 0:
        raise HVImportError("FUTURE_AS_OF_DATE")
    return {
        "symbol": "NVDA", "provider": "TIINGO_EOD", "hv": dict(hv),
        "as_of_session": payload["as_of_session"], "observations": observations,
        "price_field": "adjClose", "adjustment_basis": payload["adjustment_basis"],
        "formula_id": FORMULA_ID, "status": "PROVISIONAL",
        "freshness": "STALE" if age > max_age_days else "RECENT",
        "age_calendar_days": age, "production_eligible": False,
    }


def research_panel_state(options_snapshot_date: str, hv: dict | None) -> dict:
    """Build a display-only state without deriving IV or changing option data."""
    if not _valid_iso_date(options_snapshot_date):
        raise HVImportError("INVALID_OPTIONS_SNAPSHOT_DATE")
    if hv is None:
        return {"available": False, "options_snapshot_date": options_snapshot_date,
                "hv_as_of_session": None, "timestamp_mismatch": False,
                "warning": "Tiingo HV 권한 확인 및 가져온 결과가 없어 표시하지 않습니다."}
    mismatch = options_snapshot_date != hv["as_of_session"]
    return {"available": True, "options_snapshot_date": options_snapshot_date,
            "hv_as_of_session": hv["as_of_session"], "timestamp_mismatch": mismatch,
            "warning": "옵션 스냅샷일과 HV 기준일이 다릅니다." if mismatch else "",
            "status": "PROVISIONAL", "values": dict(hv["hv"]),
            "freshness": hv["freshness"], "adjustment_basis": hv["adjustment_basis"]}

