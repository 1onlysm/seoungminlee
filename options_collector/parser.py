import json,re
from dataclasses import dataclass
from typing import Any
from .registry import Symbol
@dataclass
class ParsedChain:
    symbol:str; rows:list[dict[str,Any]]; total_record:int|None; expiry_groups:int; schema_ok:bool; issues:list[str]
def parse_payload(raw,item:Symbol):
    try: root=raw if isinstance(raw,dict) else json.loads(raw.decode("utf-8") if isinstance(raw,bytes) else raw)
    except (UnicodeDecodeError,json.JSONDecodeError,TypeError) as exc: raise ValueError("INVALID_JSON") from exc
    table=((root.get("data") or {}).get("table") or {}); src=table.get("rows")
    if not isinstance(src,list): return ParsedChain(item.symbol,[],_int(table.get("totalRecord")),0,False,["ROWS_MISSING"])
    count=0; expiry=None; contracts=[]; issues=[]
    for source in src:
        if not isinstance(source,dict): issues.append("NON_OBJECT_ROW"); continue
        strike=source.get("strikePrice"); exp=source.get("expiryDate") or source.get("expirationDate")
        if strike in (None,"","--") and exp: expiry=str(exp); count+=1; continue
        row=dict(source); row["_expiry_group"]=expiry; row["_root"]=extract_root(source)
        row["_root_class"]="STANDARD" if row["_root"]==item.expected_root else ("ADJUSTED" if row["_root"] else "UNKNOWN")
        row["_strike_valid"]=_valid(strike); contracts.append(row)
    total=_int(table.get("totalRecord"))
    if total is not None and total!=len(contracts): issues.append("TOTAL_RECORD_MISMATCH")
    if not contracts: issues.append("EMPTY_CHAIN")
    return ParsedChain(item.symbol,contracts,total,count,not issues,issues)
def extract_root(row):
    for key in ("c_Option","p_Option","option","contractSymbol","drillDownURL"):
        val=row.get(key)
        if not val: continue
        text=str(val); m=re.search(r"(?:/|[?&]symbol=)([A-Z]{1,6}\d{0,2})(?:\s*\d{6}[CP]\d{8}|/|[?&]|$)",text)
        if m:return m.group(1)
        m=re.match(r"([A-Z]{1,6}\d{0,2})\s*\d{6}[CP]\d{8}",text)
        if m:return m.group(1)
    return None
def _valid(v):
    try:return float(str(v).replace(",","").replace("$",""))>0
    except (ValueError,TypeError):return False
def _int(v):
    try:return int(str(v).replace(",","")) if v is not None else None
    except (ValueError,TypeError):return None
