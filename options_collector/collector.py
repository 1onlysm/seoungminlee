"""Explicit one-shot collection orchestration. This module is never run by tests."""
import argparse, json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from .client import NasdaqClient
from .parser import parse_payload
from .quality import inspect_quality
from .registry import REGISTRY, get_symbol
from .snapshot import write_snapshot

def collect(symbols, output):
    client=NasdaqClient(timeout=30); results=[]
    for symbol in symbols:
        item=get_symbol(symbol)
        result=client.fetch_once(symbol)  # one attempt only
        entry={"symbol":symbol,"http_status":result.http_status,"api_rcode":result.api_rcode,"error_type":result.error_type}
        results.append(entry)
        if result.http_status in (403,429) or result.error_type or result.api_rcode!=200: break
        if result.http_status!=200 or result.body is None: break
        parsed=parse_payload(result.body,item)
        quality=inspect_quality(parsed,result.body,result.http_status,result.api_rcode)
        now=datetime.now(ZoneInfo("America/New_York")); date_et=now.date().isoformat()
        write_snapshot(output,symbol,date_et,result.body,parsed.rows,quality,datetime.now(ZoneInfo("UTC")).isoformat())
    return results

def main():
    p=argparse.ArgumentParser(); p.add_argument("--symbols",nargs="+",choices=sorted(REGISTRY),required=True); p.add_argument("--output",default="data"); a=p.parse_args()
    print(json.dumps(collect(a.symbols,a.output),indent=2))
if __name__=="__main__": main()
