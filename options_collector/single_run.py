"""Safe one-symbol execution path. OFFLINE is default; LIVE requires two explicit gates.

This module is never run in LIVE mode by the test suite or WORK 04-E verification.
"""
import argparse, csv, hashlib, json, os, tempfile, uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .client import NasdaqClient
from .parser import parse_payload
from .quality import inspect_quality
from .registry import get_symbol
from .snapshot import write_snapshot

LIVE_SYMBOL = "MSTR"
LIVE_MAX_REQUESTS = 1

class SafetyGateError(RuntimeError):
    pass


def run_single(*, mode="offline", symbol=LIVE_SYMBOL, input_path=None, output_root="runs",
               confirm_live=False, client_factory=NasdaqClient):
    mode = str(mode).lower()
    if symbol != LIVE_SYMBOL:
        raise SafetyGateError("SINGLE_SYMBOL_GATE: only MSTR is enabled in WORK 04-E")
    get_symbol(symbol)
    if mode not in ("offline", "live"):
        raise SafetyGateError("MODE_GATE: mode must be offline or live")
    if mode == "offline" and not input_path:
        raise SafetyGateError("OFFLINE_INPUT_REQUIRED: provide preserved JSON or fixture")
    if mode == "live" and not confirm_live:
        raise SafetyGateError("LIVE_CONFIRMATION_REQUIRED: no request was made")

    run_id = f"naviopt04e-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = Path(output_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = run_dir / "execution_manifest.jsonl"
    started = datetime.now(timezone.utc).isoformat()
    _append_event(manifest, {"event":"RUN_STARTED", "run_id":run_id, "timestamp_utc":started,
                             "symbol":symbol, "mode":mode, "request_attempt_limit":LIVE_MAX_REQUESTS,
                             "network_requests_dispatched":0, "eod_freshness":"EOD_UNVERIFIED"})
    outcome = {"run_id":run_id, "run_dir":str(run_dir), "symbol":symbol, "mode":mode,
               "http_status":None, "api_rcode":None, "raw_bytes":None, "sha256":None,
               "contracts":None, "expiries":None, "quality_state":None,
               "eod_state":"EOD_UNVERIFIED", "snapshot_path":None,
               "request_count":0, "retry_count":0, "redirect_count":0,
               "result":"PENDING"}
    try:
        if mode == "offline":
            source = Path(input_path)
            if not source.is_file():
                raise FileNotFoundError(f"OFFLINE_INPUT_NOT_FOUND: {source}")
            raw = source.read_bytes()
            payload = _parse_json(raw)
            outcome["http_status"] = _historical_http_status(source, symbol)
            outcome["api_rcode"] = _rcode(payload)
            source_capture = _captured_at(source)
            _append_event(manifest, {"event":"OFFLINE_INPUT_LOADED", "timestamp_utc":datetime.now(timezone.utc).isoformat(),
                                     "source_capture_timestamp_utc":source_capture,
                                     "source_path":str(source), "input_bytes":len(raw),
                                     "input_sha256":hashlib.sha256(raw).hexdigest(), "network_requests":0})
        else:
            # This event marks intent only. Dispatch is separately recorded immediately before opener.open.
            _append_event(manifest, {"event":"REQUEST_INTENT_RECORDED", "timestamp_utc":datetime.now(timezone.utc).isoformat(),
                                     "symbol":symbol, "request_attempt_number":1, "request_attempt_limit":1})
            client = client_factory(timeout=30)
            _append_event(manifest, {"event":"REQUEST_DISPATCHED", "timestamp_utc":datetime.now(timezone.utc).isoformat(),
                                     "symbol":symbol, "request_attempt_number":1,
                                     "definition":"fetch_once invocation about to begin; not proof of transmission or server receipt"})
            outcome["request_count"] = 1
            fetched = client.fetch_once(symbol)
            outcome["http_status"] = fetched.http_status
            outcome["api_rcode"] = fetched.api_rcode
            if fetched.body is not None:
                raw = fetched.body
                outcome["raw_bytes"] = len(raw)
                outcome["sha256"] = hashlib.sha256(raw).hexdigest()
                _append_event(manifest, {"event":"HTTP_RESPONSE_RECEIVED", "timestamp_utc":datetime.now(timezone.utc).isoformat(),
                                         "symbol":symbol, "http_status":fetched.http_status, "api_rcode":fetched.api_rcode,
                                         "response_bytes":len(raw), "response_sha256":outcome["sha256"], "request_attempt_number":1})
            else:
                _append_event(manifest, {"event":"REQUEST_FAILED", "timestamp_utc":datetime.now(timezone.utc).isoformat(),
                                         "symbol":symbol, "http_status":fetched.http_status,
                                         "error_type":fetched.error_type, "error_detail":fetched.error_detail,
                                         "request_attempt_number":1, "retry_count":0})
                outcome["result"] = "HTTP_ACCESS_DENIED" if fetched.http_status in (403,429) else "NETWORK_ERROR"
                return _finalize(manifest, run_dir, outcome)
            if fetched.http_status in (403,429):
                outcome["result"] = "HTTP_ACCESS_DENIED"
                _save_unparsed_body(run_dir, raw)
                return _finalize(manifest, run_dir, outcome)
            if fetched.http_status != 200 or fetched.api_rcode != 200:
                outcome["result"] = "API_RESPONSE_INVALID"
                _save_unparsed_body(run_dir, raw)
                return _finalize(manifest, run_dir, outcome)
            payload = _parse_json(raw)

        if outcome["api_rcode"] != 200 or (mode == "live" and outcome["http_status"] != 200):
            outcome["result"] = "API_RESPONSE_INVALID"
            _save_unparsed_body(run_dir, raw)
            return _finalize(manifest, run_dir, outcome)
        parsed = parse_payload(raw, get_symbol(symbol))
        captured = datetime.now(timezone.utc).isoformat() if mode == "live" else (source_capture or datetime.now(timezone.utc).isoformat())
        quality = inspect_quality(parsed, raw, outcome["http_status"], outcome["api_rcode"], collected_at_utc=captured)
        outcome.update({"raw_bytes":len(raw), "sha256":hashlib.sha256(raw).hexdigest(),
                        "contracts":len(parsed.rows), "expiries":parsed.expiry_groups,
                        "quality_state":quality["status"]["data"], "eod_state":"EOD_UNVERIFIED"})
        if not parsed.schema_ok or not quality["parser_integrity"]["ok"]:
            outcome["result"] = "SCHEMA_MISMATCH"
            _save_unparsed_body(run_dir, raw)
            return _finalize(manifest, run_dir, outcome)
        trading_date = datetime.fromisoformat(captured.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        snap = write_snapshot(run_dir / "snapshot", symbol, trading_date, raw, parsed.rows, quality, captured)
        # Record the post-write check in quality.json, then validate the final bytes again.
        quality["snapshot_integrity"]["snapshot_readback_verified"] = True
        _atomic_text(snap / "quality.json", json.dumps(quality, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        # Validate durable artifacts after writing; original response bytes remain unmodified.
        _verify_snapshot(snap, outcome["sha256"], len(parsed.rows))
        outcome["snapshot_path"] = str(snap)
        outcome["result"] = "OFFLINE_E2E_PASSED" if mode == "offline" else "LIVE_RESULT_PERSISTED"
        _append_event(manifest, {"event":"RESULT_PERSISTED", "timestamp_utc":datetime.now(timezone.utc).isoformat(),
                                 "symbol":symbol, "http_status":outcome["http_status"], "api_rcode":outcome["api_rcode"],
                                 "response_bytes":outcome["raw_bytes"], "sha256":outcome["sha256"],
                                 "contracts":outcome["contracts"], "expiries":outcome["expiries"],
                                 "quality_state":outcome["quality_state"], "eod_state":"EOD_UNVERIFIED",
                                 "snapshot_path":str(snap), "readback_verified":True})
        return _finalize(manifest, run_dir, outcome)
    except Exception as exc:
        outcome["result"] = "PERSISTENCE_OR_PROCESSING_ERROR"
        _append_event(manifest, {"event":"RUN_ERROR", "timestamp_utc":datetime.now(timezone.utc).isoformat(),
                                 "error_type":type(exc).__name__, "error_detail":str(exc),
                                 "request_count":outcome["request_count"], "retry_count":0})
        _finalize(manifest, run_dir, outcome)
        raise


def _append_event(path, event):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush(); os.fsync(f.fileno())
    fd=os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def _parse_json(raw):
    try:
        value=json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict): raise ValueError("JSON_ROOT_NOT_OBJECT")
        return value
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise ValueError("INVALID_JSON") from exc


def _rcode(payload):
    try: return int(payload.get("status",{}).get("rCode"))
    except (TypeError,ValueError): return None


def _historical_http_status(source, symbol):
    manifest=source.parents[1]/"execution_manifest.jsonl"
    if not manifest.is_file(): return None
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try: event=json.loads(line)
        except json.JSONDecodeError: continue
        if event.get("symbol")==symbol and event.get("request_status")=="HTTP_RESPONSE_RECEIVED":
            return event.get("http_status")
    return None

def _captured_at(source):
    # Historical capture time comes from the retained request-intent event, not file mtime.
    run_manifest=source.parents[1]/"execution_manifest.jsonl"
    if run_manifest.is_file():
        for line in run_manifest.read_text(encoding="utf-8").splitlines():
            try: event=json.loads(line)
            except json.JSONDecodeError: continue
            if event.get("symbol")=="MSTR" and event.get("request_status")=="REQUEST_INTENT_RECORDED":
                return event.get("timestamp_utc")
    return None


def _save_unparsed_body(run_dir, raw):
    # Preserve even error/invalid bodies without pretending they are a valid chain snapshot.
    path=run_dir/"raw-response.bin"
    fd,name=tempfile.mkstemp(prefix=".raw-response.",dir=run_dir)
    try:
        with os.fdopen(fd,"wb") as f: f.write(raw); f.flush(); os.fsync(f.fileno())
        os.replace(name,path)
        fd=os.open(run_dir,os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    except Exception:
        try: os.unlink(name)
        except OSError: pass
        raise


def _verify_snapshot(snap, digest, contract_count):
    raw=(snap/"raw.json").read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digest: raise IOError("RAW_SHA256_MISMATCH")
    quality=json.loads((snap/"quality.json").read_text(encoding="utf-8"))
    manifest=json.loads((snap/"manifest.json").read_text(encoding="utf-8"))
    with (snap/"contracts.csv").open(encoding="utf-8",newline="") as f: count=sum(1 for _ in csv.DictReader(f))
    if count!=contract_count or quality.get("raw_sha256")!=digest or manifest.get("raw_sha256")!=digest:
        raise IOError("SNAPSHOT_READBACK_MISMATCH")


def _finalize(manifest, run_dir, outcome):
    report = ["# NAVI OPTIONS LAB — Single-symbol run", "",
              f"- run_id: `{outcome['run_id']}`", f"- mode: `{outcome['mode']}`", f"- symbol: `{outcome['symbol']}`",
              f"- result: `{outcome['result']}`", f"- HTTP/API: `{outcome['http_status']}/{outcome['api_rcode']}`",
              f"- contracts/expiries: `{outcome['contracts']}/{outcome['expiries']}`",
              f"- response bytes/SHA-256: `{outcome['raw_bytes']}/{outcome['sha256']}`",
              f"- quality/EOD: `{outcome['quality_state']}/{outcome['eod_state']}`",
              f"- requests/retries/redirects: `{outcome['request_count']}/{outcome['retry_count']}/{outcome['redirect_count']}`",
              f"- snapshot: `{outcome['snapshot_path']}`", ""]
    _atomic_text(run_dir/"final_report.md", "\n".join(report))
    outcome["final_report_path"] = str(run_dir/"final_report.md")
    outcome["summary_path"] = str(run_dir/"results_summary.csv")
    _atomic_text(run_dir/"results_summary.csv", _summary_csv(outcome))
    _append_event(manifest, {"event":"RUN_FINALIZED", "timestamp_utc":datetime.now(timezone.utc).isoformat(), **outcome})
    return outcome


def _summary_csv(result):
    import io
    columns=["run_id","mode","symbol","http_status","api_rcode","raw_bytes","sha256","contracts","expiries","quality_state","eod_state","request_count","retry_count","redirect_count","result"]
    out=io.StringIO(newline=""); w=csv.DictWriter(out,fieldnames=columns); w.writeheader(); w.writerow({k:result.get(k) for k in columns}); return out.getvalue()


def _atomic_text(path, text):
    fd,name=tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="") as f: f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(name,path); fd=os.open(path.parent,os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    except Exception:
        try: os.unlink(name)
        except OSError: pass
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description="One-symbol MSTR options collector; offline by default")
    parser.add_argument("--mode",choices=("offline","live"),default="offline")
    parser.add_argument("--symbol",choices=(LIVE_SYMBOL,),default=LIVE_SYMBOL)
    parser.add_argument("--input",help="preserved JSON input for offline mode")
    parser.add_argument("--output",default="runs")
    parser.add_argument("--confirm-live",action="store_true",help="required explicit acknowledgement; creates at most one live request")
    args=parser.parse_args(argv)
    result=run_single(mode=args.mode,symbol=args.symbol,input_path=args.input,output_root=args.output,confirm_live=args.confirm_live)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result["result"] in ("OFFLINE_E2E_PASSED","LIVE_RESULT_PERSISTED") else 1
if __name__=="__main__": raise SystemExit(main())
