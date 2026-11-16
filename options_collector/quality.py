import hashlib
from collections import Counter
from datetime import datetime,timezone
from .status import Status
FIELDS=("c_Volume","p_Volume","c_Openinterest","p_Openinterest")
def inspect_quality(parsed,raw,response_status,api_rcode,collected_at_utc=None):
    fields={}
    for name in FIELDS:
        observed=miss=zeros=absent=0; kinds=Counter()
        for row in parsed.rows:
            if name not in row: miss+=1; absent+=1; kinds["field_absent"]+=1; continue
            v=row[name]
            if v is None: miss+=1; kinds["null"]+=1
            elif isinstance(v,str) and v=="": miss+=1; kinds["empty_string"]+=1
            elif v=="--": miss+=1; kinds["dash"]+=1
            else:
                observed+=1
                try: zeros+=float(str(v).replace(",",""))==0
                except (ValueError,TypeError): pass
        n=len(parsed.rows); fields[name]={"field_present_rows":n-absent,"observed_values":observed,"missing_count":miss,"missing_rate":miss/n if n else None,"explicit_zero_count":zeros,"missing_types":dict(kinds)}
    roots=Counter(r.get("_root_class","UNKNOWN") for r in parsed.rows)
    keys=[(str(r.get("_expiry_group")),str(r.get("strikePrice")),r.get("_root")) for r in parsed.rows]
    status=Status(api="API_VERIFIED" if response_status==200 and api_rcode==200 else ("ACCESS_BLOCKED" if response_status in (403,429) else "FETCH_ERROR"),data="DATA_OBSERVED" if parsed.rows and parsed.schema_ok else "SCHEMA_MISMATCH")
    if any(v["missing_count"] for v in fields.values()): status.reasons.append("VOLUME_OI_MISSING_VALUES"); status.data="QUALITY_LIMITED" if status.data=="DATA_OBSERVED" else status.data
    status.reasons.extend(parsed.issues)
    return {"symbol":parsed.symbol,"http_status":response_status,"api_rcode":api_rcode,"raw_sha256":hashlib.sha256(raw).hexdigest(),"raw_bytes":len(raw),"contract_rows":len(parsed.rows),"totalRecord":parsed.total_record,"total_record_matches":parsed.total_record==len(parsed.rows) if parsed.total_record is not None else None,"expiry_group_count":parsed.expiry_groups,"standard_adjusted_unknown_roots":dict(roots),"duplicate_contract_keys":len(keys)-len(set(keys)),"invalid_strike_count":sum(not r.get("_strike_valid") for r in parsed.rows),"volume_oi":fields,"option_chain_timestamp":None,"freshness":"EOD_UNVERIFIED","status":{"api":status.api,"data":status.data,"freshness":"EOD_UNVERIFIED","reasons":status.reasons},"collected_at_utc":collected_at_utc or datetime.now(timezone.utc).isoformat()}
