from dataclasses import dataclass, field

API_STATES = {"API_VERIFIED", "FETCH_ERROR", "ACCESS_BLOCKED"}
DATA_STATES = {"DATA_OBSERVED", "QUALITY_LIMITED", "SCHEMA_MISMATCH"}
FRESHNESS_STATES = {"EOD_UNVERIFIED", "PENDING_EOD", "STALE", "EOD_VERIFIED"}
@dataclass
class Status:
    api: str = "FETCH_ERROR"
    data: str = "SCHEMA_MISMATCH"
    freshness: str = "EOD_UNVERIFIED"
    reasons: list[str] = field(default_factory=list)
def derived_indicators_allowed(status: Status) -> bool:
    return status.freshness == "EOD_VERIFIED" and status.api == "API_VERIFIED" and status.data == "DATA_OBSERVED"
def require_derived_indicators(status: Status) -> None:
    if not derived_indicators_allowed(status): raise RuntimeError("DERIVED_INDICATORS_BLOCKED: EOD/data verification gate not satisfied")
