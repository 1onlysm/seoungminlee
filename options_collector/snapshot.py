import csv, hashlib, json, os, tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from datetime import datetime, timezone

CSV_FIELDS = ["symbol","expiration","strike","root","root_class","call_option","put_option","c_volume","p_volume","c_openinterest","p_openinterest","raw_row_json"]

def write_snapshot(base_dir, symbol, trading_date_et, raw: bytes, contracts, quality, collected_at_utc=None):
    """Write immutable version directory. Exact same response hash is deduplicated."""
    digest=hashlib.sha256(raw).hexdigest(); stamp=(collected_at_utc or datetime.now(timezone.utc).isoformat()).replace(":","-")
    parent=Path(base_dir)/"data"/"options"/trading_date_et/symbol
    parent.mkdir(parents=True,exist_ok=True)
    for existing in parent.iterdir():
        manifest=existing/"manifest.json"
        if manifest.is_file():
            try:
                if json.loads(manifest.read_text()).get("raw_sha256")==digest:
                    _verify(existing,digest); return existing
            except (OSError,json.JSONDecodeError): pass
    target=parent/stamp
    suffix=1
    while target.exists(): target=parent/f"{stamp}-v{suffix}"; suffix+=1
    temp=Path(tempfile.mkdtemp(prefix=".pending-",dir=parent))
    try:
        _atomic_bytes(temp/"raw.json",raw)
        _atomic_text(temp/"contracts.csv",_csv_text(symbol,contracts))
        _atomic_text(temp/"quality.json",json.dumps(quality,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
        utc_stamp=collected_at_utc or datetime.now(timezone.utc).isoformat()
        parsed_utc=datetime.fromisoformat(utc_stamp.replace("Z","+00:00"))
        et_stamp=parsed_utc.astimezone(ZoneInfo("America/New_York")).isoformat()
        manifest_data={"symbol":symbol,"trading_date_et":trading_date_et,"collected_at_utc":utc_stamp,"collected_at_et":et_stamp,"raw_sha256":digest,"raw_bytes":len(raw),"contract_rows":len(contracts),"freshness":"EOD_UNVERIFIED","snapshot_kind":"collection_snapshot","version":target.name}
        _atomic_text(temp/"manifest.json",json.dumps(manifest_data,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
        _verify(temp,digest)
        os.replace(temp,target); _fsync_dir(parent); _verify(target,digest)
        return target
    except Exception:
        # Do not remove prior snapshots. Incomplete temp evidence is left for inspection.
        raise

def _csv_text(symbol,rows):
    import io
    out=io.StringIO(newline=""); w=csv.DictWriter(out,fieldnames=CSV_FIELDS,extrasaction="ignore"); w.writeheader()
    for row in rows:
        w.writerow({"symbol":symbol,"expiration":row.get("_expiry_group"),"strike":row.get("strikePrice"),"root":row.get("_root"),"root_class":row.get("_root_class"),"call_option":row.get("c_Option"),"put_option":row.get("p_Option"),"c_volume":row.get("c_Volume"),"p_volume":row.get("p_Volume"),"c_openinterest":row.get("c_Openinterest"),"p_openinterest":row.get("p_Openinterest"),"raw_row_json":json.dumps(row,ensure_ascii=False,separators=(",",":"))})
    return out.getvalue()
def _atomic_bytes(path,data):
    _atomic_write(path,data,True)
def _atomic_text(path,data):
    _atomic_write(path,data,False)
def _atomic_write(path,data,binary):
    mode="wb" if binary else "w"
    kwargs={} if binary else {"encoding":"utf-8","newline":""}
    fd,name=tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
    try:
        with os.fdopen(fd,mode,**kwargs) as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(name,path); _fsync_dir(path.parent)
    except Exception:
        try: os.unlink(name)
        except OSError: pass
        raise
def _verify(directory,digest):
    raw=(directory/"raw.json").read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digest: raise IOError("RAW_SHA256_MISMATCH")
    json.loads((directory/"quality.json").read_text(encoding="utf-8"))
    json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
    with (directory/"contracts.csv").open(encoding="utf-8",newline="") as f: list(csv.DictReader(f))
def _fsync_dir(path):
    fd=os.open(path,os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
