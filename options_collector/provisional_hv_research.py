"""Rights-gated, local-only historical-volatility research lane.

This module is intentionally separate from the VERIFIED historical-volatility
contract and production dashboard. It accepts only an explicit local research
rights decision, never treats a provisional result as production eligible, and
refuses to write research results inside the repository tree.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from typing import Sequence

from .historical_volatility import OHLCObservation


class ProvisionalResearchBlocked(ValueError):
    """A research permission, evidence, or input gate was not satisfied."""


@dataclass(frozen=True)
class CandidateBundleAudit:
    """Hash-verified metadata and parsed rows from an embedded candidate bundle."""

    bundle_sha256: str
    payload_sha256: str
    symbol: str
    rows: tuple[OHLCObservation, ...]
    first_session: str
    last_session: str


def audit_candidate_bundle_bytes(
    bundle_bytes: bytes,
    *,
    expected_bundle_sha256: str,
    expected_payload_sha256: str,
    expected_symbol: str = "NVDA",
    expected_rows: int = 90,
) -> CandidateBundleAudit:
    """Verify original bundle bytes and embedded canonical payload digest.

    This confirms byte consistency only. It does not authenticate the upstream
    market-data provider, its license, or adjustment semantics.
    """
    if not isinstance(bundle_bytes, bytes) or not bundle_bytes:
        raise ProvisionalResearchBlocked("ORIGINAL_BUNDLE_BYTES_UNAVAILABLE")
    bundle_digest = hashlib.sha256(bundle_bytes).hexdigest()
    if bundle_digest != expected_bundle_sha256:
        raise ProvisionalResearchBlocked("BUNDLE_SHA256_MISMATCH")
    try:
        bundle = json.loads(bundle_bytes)
        output = bundle["execution_bundle"]["producer_attendance"][5]["output"]
        payload = output["raw_ohlcv_90d"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ProvisionalResearchBlocked("CANDIDATE_PAYLOAD_NOT_FOUND_OR_INVALID") from exc
    if output.get("symbol") != expected_symbol:
        raise ProvisionalResearchBlocked("WRONG_SYMBOL")
    if not isinstance(payload, list) or len(payload) != expected_rows:
        raise ProvisionalResearchBlocked("CANDIDATE_ROW_COUNT_MISMATCH")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload_digest = hashlib.sha256(canonical).hexdigest()
    if payload_digest != expected_payload_sha256 or output.get("raw_ohlcv_90d_sha256") != expected_payload_sha256:
        raise ProvisionalResearchBlocked("PAYLOAD_SHA256_MISMATCH")
    rows: list[OHLCObservation] = []
    previous: date | None = None
    for raw in payload:
        if not isinstance(raw, dict) or set(raw) != {"date", "open", "high", "low", "close", "volume"}:
            raise ProvisionalResearchBlocked("CANDIDATE_ROW_SCHEMA_INVALID")
        try:
            session = date.fromisoformat(raw["date"])
        except (TypeError, ValueError) as exc:
            raise ProvisionalResearchBlocked("INVALID_SESSION_DATE") from exc
        if previous is not None and session <= previous:
            raise ProvisionalResearchBlocked("DUPLICATE_OR_UNSORTED_SESSION")
        previous = session
        values = [raw[key] for key in ("open", "high", "low", "close", "volume")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            raise ProvisionalResearchBlocked("CANDIDATE_NUMERIC_FIELD_INVALID")
        open_, high, low, close, volume = map(float, values)
        if any(value <= 0 for value in (open_, high, low, close)):
            raise ProvisionalResearchBlocked("NONPOSITIVE_OHLC")
        if volume < 0:
            raise ProvisionalResearchBlocked("NEGATIVE_VOLUME")
        if low > min(open_, close) or high < max(open_, close) or high < low:
            raise ProvisionalResearchBlocked("INVALID_OHLC_RELATIONSHIP")
        rows.append(OHLCObservation(raw["date"], open_, high, low, close))
    if not rows:
        raise ProvisionalResearchBlocked("EMPTY_CANDIDATE_PAYLOAD")
    return CandidateBundleAudit(
        bundle_sha256=bundle_digest, payload_sha256=payload_digest,
        symbol=expected_symbol, rows=tuple(rows),
        first_session=rows[0].session_date, last_session=rows[-1].session_date,
    )


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS = (10, 20, 30, 60)
_RESEARCH_LABELS = (
    "PROVISIONAL_RESEARCH_ONLY",
    "NOT_FOR_PRODUCTION",
    "NOT_CURRENT",
    "NOT_IMPLIED_VOLATILITY",
)


@dataclass(frozen=True)
class ResearchEvidence:
    symbol: str
    source_status: str
    source_sha256: str
    payload_sha256: str
    actual_bytes_recovered: bool
    observation_count: int
    first_session: str
    last_session: str
    local_research_permission: str
    permission_evidence_ref: str | None
    adjustment_status: str
    corporate_action_status: str
    observation_class: str = "PRESERVED_CANDIDATE_OHLCV"
    redistribution_status: str = "NOT_VERIFIED"
    publication_eligible: bool = False


@dataclass(frozen=True)
class ProvisionalHVValue:
    name: str
    window_returns: int
    annualized_percent: float
    first_session: str
    last_session: str
    valid_closes: int
    valid_returns: int
    status: str = "PROVISIONAL_RESEARCH_ONLY"


@dataclass(frozen=True)
class ProvisionalHVReport:
    symbol: str
    lane: str
    source_status: str
    adjustment_status: str
    source_sha256: str
    payload_sha256: str
    as_of_session: str
    observation_class: str
    values: tuple[ProvisionalHVValue, ...]
    warnings: tuple[str, ...]
    production_eligible: bool = False
    publication_eligible: bool = False
    volatility_type: str = "HISTORICAL_CLOSE_TO_CLOSE"

    def to_dict(self) -> dict:
        """Return a research-only payload, never the VERIFIED schema."""
        return {
            "symbol": self.symbol,
            "research_lane": self.lane,
            "source_status": self.source_status,
            "adjustment_status": self.adjustment_status,
            "source_sha256": self.source_sha256,
            "payload_sha256": self.payload_sha256,
            "as_of_session": self.as_of_session,
            "observation_class": self.observation_class,
            "volatility_type": self.volatility_type,
            "values": [asdict(value) for value in self.values],
            "warnings": list(self.warnings),
            "labels": list(_RESEARCH_LABELS),
            "production_eligible": False,
            "publication_eligible": False,
            "implied_volatility": None,
        }


def validate_research_evidence(evidence: ResearchEvidence) -> None:
    """Enforce the research lane's provenance, rights, and non-production gates."""
    if evidence.symbol != "NVDA":
        raise ProvisionalResearchBlocked("WRONG_SYMBOL")
    if evidence.observation_class not in {"PRESERVED_CANDIDATE_OHLCV", "TEST_ONLY"}:
        raise ProvisionalResearchBlocked("OBSERVATION_CLASS_UNSUPPORTED")
    if not evidence.actual_bytes_recovered:
        raise ProvisionalResearchBlocked("ORIGINAL_BYTES_UNAVAILABLE")
    if not _SHA256.fullmatch(evidence.source_sha256 or ""):
        raise ProvisionalResearchBlocked("INVALID_SOURCE_SHA256")
    if not _SHA256.fullmatch(evidence.payload_sha256 or ""):
        raise ProvisionalResearchBlocked("INVALID_PAYLOAD_SHA256")
    if evidence.observation_count < 2:
        raise ProvisionalResearchBlocked("INSUFFICIENT_CANDIDATE_RECORDS")
    try:
        first, last = date.fromisoformat(evidence.first_session), date.fromisoformat(evidence.last_session)
    except (TypeError, ValueError) as exc:
        raise ProvisionalResearchBlocked("INVALID_EVIDENCE_DATE_RANGE") from exc
    if first > last:
        raise ProvisionalResearchBlocked("REVERSED_EVIDENCE_DATE_RANGE")
    if evidence.local_research_permission != "VERIFIED_ALLOWED" or not evidence.permission_evidence_ref:
        raise ProvisionalResearchBlocked("LOCAL_RESEARCH_PERMISSION_UNVERIFIED")
    if evidence.corporate_action_status not in {"NO_AFFECTING_ACTION_VERIFIED", "ACTIONS_ACCOUNTED_FOR"}:
        raise ProvisionalResearchBlocked("CORPORATE_ACTION_STATUS_UNVERIFIED")
    if evidence.publication_eligible:
        raise ProvisionalResearchBlocked("PROVISIONAL_OUTPUT_CANNOT_BE_PUBLICATION_ELIGIBLE")
    if evidence.redistribution_status == "AUTHORIZED":
        raise ProvisionalResearchBlocked("REDISTRIBUTION_IS_OUTSIDE_THIS_RESEARCH_LANE")


def _validate_rows(rows: Sequence[OHLCObservation], expected_sessions: Sequence[str], evidence: ResearchEvidence) -> None:
    if len(rows) != evidence.observation_count:
        raise ProvisionalResearchBlocked("ROW_COUNT_MISMATCH")
    if len(rows) != len(expected_sessions):
        raise ProvisionalResearchBlocked("EXPECTED_SESSION_COUNT_MISMATCH")
    row_dates = [row.session_date for row in rows]
    if row_dates != list(expected_sessions):
        raise ProvisionalResearchBlocked("MISSING_DUPLICATE_OR_UNSORTED_SESSION")
    if len(set(row_dates)) != len(row_dates):
        raise ProvisionalResearchBlocked("DUPLICATE_SESSION")
    try:
        parsed = [date.fromisoformat(item) for item in row_dates]
    except (TypeError, ValueError) as exc:
        raise ProvisionalResearchBlocked("INVALID_SESSION_DATE") from exc
    if parsed != sorted(parsed) or parsed[0].isoformat() != evidence.first_session or parsed[-1].isoformat() != evidence.last_session:
        raise ProvisionalResearchBlocked("SESSION_ORDER_OR_RANGE_MISMATCH")
    for row in rows:
        vals = (row.open, row.high, row.low, row.close)
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vals):
            raise ProvisionalResearchBlocked("NONFINITE_OR_NONNUMERIC_OHLC")
        if any(value <= 0 for value in vals):
            raise ProvisionalResearchBlocked("NONPOSITIVE_OHLC")
        if row.low > min(row.open, row.close) or row.high < max(row.open, row.close) or row.high < row.low:
            raise ProvisionalResearchBlocked("INVALID_OHLC_RELATIONSHIP")


def calculate_provisional_hv(
    rows: Sequence[OHLCObservation],
    *,
    expected_sessions: Sequence[str],
    evidence: ResearchEvidence,
    windows: Sequence[int] = _WINDOWS,
) -> ProvisionalHVReport:
    """Calculate candidate HV only after the rights and session gates pass.

    The result is explicitly research-only. It is never connected to the
    verified dashboard or its data contract. Callers must provide a documented
    local-rights decision and corporate-action disposition.
    """
    validate_research_evidence(evidence)
    _validate_rows(rows, expected_sessions, evidence)
    values: list[ProvisionalHVValue] = []
    for window in windows:
        if not isinstance(window, int) or window < 2:
            raise ProvisionalResearchBlocked("INVALID_RETURN_WINDOW")
        if len(rows) < window + 1:
            continue
        trailing = rows[-(window + 1):]
        returns = [math.log(float(now.close) / float(prev.close)) for prev, now in zip(trailing, trailing[1:])]
        result = statistics.stdev(returns) * math.sqrt(252) * 100
        if not math.isfinite(result):
            raise ProvisionalResearchBlocked("NONFINITE_CALCULATION")
        values.append(ProvisionalHVValue(
            name=f"HV{window}", window_returns=window, annualized_percent=result,
            first_session=trailing[0].session_date, last_session=trailing[-1].session_date,
            valid_closes=window + 1, valid_returns=window,
        ))
    warnings = list(_RESEARCH_LABELS)
    if evidence.source_status != "UPSTREAM_SOURCE_VERIFIED":
        warnings.append("UPSTREAM_SOURCE_UNVERIFIED")
    if evidence.adjustment_status != "VERIFIED_CONSISTENT":
        warnings.append("PRICE_ADJUSTMENT_UNVERIFIED")
    if evidence.observation_class == "TEST_ONLY":
        warnings.append("TEST_ONLY_FIXTURE")
    return ProvisionalHVReport(
        symbol=evidence.symbol, lane="PROVISIONAL", source_status=evidence.source_status,
        adjustment_status=evidence.adjustment_status, source_sha256=evidence.source_sha256,
        payload_sha256=evidence.payload_sha256, as_of_session=rows[-1].session_date,
        observation_class=evidence.observation_class, values=tuple(values), warnings=tuple(warnings),
    )


def write_local_research_json(report: ProvisionalHVReport, output_path: str | Path, *, repository_root: str | Path) -> Path:
    """Write only outside the repository; do not create publishable artifacts."""
    destination = Path(output_path).expanduser().resolve()
    root = Path(repository_root).expanduser().resolve()
    if destination == root or root in destination.parents:
        raise ProvisionalResearchBlocked("RESEARCH_OUTPUT_MUST_REMAIN_OUTSIDE_REPOSITORY")
    if report.production_eligible or report.publication_eligible:
        raise ProvisionalResearchBlocked("RESEARCH_REPORT_HAS_INVALID_ELIGIBILITY_FLAGS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination
