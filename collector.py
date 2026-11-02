"""Experimental Nasdaq SPY options snapshot collector; independent of NAVI."""
import csv, hashlib, json, os, re, sys, urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

URL = "https://api.nasdaq.com/api/quote/SPY/option-chain?assetclass=etf&limit=20000&fromdate=all"
ET = ZoneInfo("America/New_York")
FIELDS = ("c_Volume", "p_Volume", "c_Openinterest", "p_Openinterest")

def number(value):
    if value is None or value == "" or value == "--":
        return None
    n = int(str(value).replace(",", ""))
    if n < 0:
        raise ValueError("negative number")
    return n

def parse(payload):
    if payload.get("status", {}).get("rCode") != 200:
        raise ValueError("API status not 200")
    data = payload.get("data") or {}
    rows = (data.get("table") or {}).get("rows")
    if not isinstance(rows, list) or len(rows) < 500 or data.get("totalRecord") != len(rows):
        raise ValueError("missing, short or truncated rows")
    expiry = None
    out, seen = [], set()
    for row in rows:
        if row.get("expirygroup"):
            expiry = datetime.strptime(row["expirygroup"], "%B %d, %Y").date().isoformat()
            continue
        if not expiry or not row.get("strike"):
            raise ValueError("unrecognized row")
        match = re.search(r"/([a-z0-9]+)-+\d{6}c\d+", row.get("drillDownURL") or "", re.I)
        if not match:
            raise ValueError("unknown contract root")
        root, strike = match.group(1).upper(), str(row["strike"])
        key = (root, expiry, strike)
        if key in seen:
            raise ValueError("duplicate contract")
        seen.add(key)
        record = {"root": root, "expiry": expiry, "strike": strike}
        for field in FIELDS:
            record[field] = number(row.get(field))
        out.append(record)
    return data, out

def main():
    now = datetime.now(ET)
    if now.weekday() >= 5 or not (16 <= now.hour <= 23) or (now.hour == 16 and now.minute < 30):
        raise ValueError("outside weekday post-close window")
    req = urllib.request.Request(URL, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept": "application/json", "Referer": "https://www.nasdaq.com/"})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read(25000001)
    if len(raw) > 25000000:
        raise ValueError("oversized response")
    data, contracts = parse(json.loads(raw))
    stamp = data.get("lastTrade", "")
    m = re.search(r"AS OF\s+([A-Z]{3})\s+(\d{1,2}),\s+(\d{4})\s+(\d{1,2}):(\d{2})\s+(AM|PM)\s+ET", stamp, re.I)
    if not m:
        raise ValueError("timestamp unavailable")
    quoted = datetime.strptime(" ".join(m.groups()), "%b %d %Y %I %M %p").replace(tzinfo=ET)
    if quoted.date() != now.date() or quoted.hour < 16:
        raise ValueError("stale or intraday quote; EOD not verified")
    missing = {f: sum(c[f] is None for c in contracts) for f in FIELDS}
    totals = {f: sum(c[f] for c in contracts if c[f] is not None) for f in FIELDS}
    summary = {
        "source": URL, "data_date_et": quoted.date().isoformat(),
        "fetched_at_et": now.isoformat(), "nasdaq_last_trade": stamp,
        "reported_rows": len((data["table"])["rows"]), "contract_rows": len(contracts),
        "expiry_count": len(set(c["expiry"] for c in contracts)),
        "roots": dict(Counter(c["root"] for c in contracts)),
        "missing_fields": missing, "observed_totals_excluding_missing": totals,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "status": "EXPERIMENTAL_POST_CLOSE_UNVERIFIED",
        "approved_for_navi": False,
    }
    dest = Path("output") / quoted.date().isoformat()
    dest.mkdir(parents=True, exist_ok=False)
    (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (dest / "contracts.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["root", "expiry", "strike", *FIELDS])
        writer.writeheader()
        writer.writerows(contracts)
    # Raw JSON is intentionally not published to artifacts in this PUBLIC repo.
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
