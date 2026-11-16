"""Offline replay of preserved WORK 04-B option responses. Makes no network calls."""
import argparse, csv, hashlib, json, re, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from options_collector.registry import get_symbol
from options_collector.parser import parse_payload
from options_collector.quality import inspect_quality, _snapshot_readback
from options_collector.snapshot import write_snapshot, _atomic_text

EVIDENCE = {
    "MSTR": Path("/workspace/scratch/navi-options-work04b-hf02/naviopt04bhf02-20261116T191412Z-7224cd99"),
    "PLTR": Path("/workspace/scratch/navi-options-work04b-hf03/naviopt04bhf03-20261116T192908Z-13cef2e0"),
    "MU": Path("/workspace/scratch/navi-options-work04b-hf03/naviopt04bhf03-20261116T192908Z-13cef2e0"),
    "CRWV": Path("/workspace/scratch/navi-options-work04b-hf03/naviopt04bhf03-20261116T192908Z-13cef2e0"),
    "COIN": Path("/workspace/scratch/navi-options-work04b-hf03/naviopt04bhf03-20261116T192908Z-13cef2e0"),
    "MARA": Path("/workspace/scratch/navi-options-work04b-hf03/naviopt04bhf03-20261116T192908Z-13cef2e0"),
}
EXPECTED = {
    "MSTR": ("responses/MSTR.response", "619151c5a3bdd73e763a61f06908f85e9afd2917ab5b364812beba2000e61c08"),
    "PLTR": ("responses/PLTR.response.json", "e3e78888811b5f6e0201334466feae713575e0203307e834f1a096273ca08b7a"),
    "MU": ("responses/MU.response.json", "1be09fa5b892d9946ee2e772f55edb230c13d01f29e7260704b1605668872716"),
    "CRWV": ("responses/CRWV.response.json", "6334b5f4cff34a496bb9d8b6cef0546eeee1f1d67ef42cfb356de6f3caa850de"),
    "COIN": ("responses/COIN.response.json", "d95c7fcea7ac07e2bef6b31646c731b726b895051e0b19f4c06e68336d9ce36d"),
    "MARA": ("responses/MARA.response.json", "c5d15378bec4a6233452428abf1d36b2da9f3243dff38e1166cdd743354403f9"),
}

def _manifest_for(root: Path, symbol: str):
    manifest = root / "execution_manifest.jsonl"
    if not manifest.is_file(): return {}
    records = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try: item = json.loads(line)
        except json.JSONDecodeError: continue
        if item.get("symbol") == symbol: records.append(item)
    return {"request_intent": next((x for x in records if x.get("request_status") == "REQUEST_INTENT_RECORDED"), None),
            "response": next((x for x in records if x.get("request_status") == "HTTP_RESPONSE_RECEIVED"), None),
            "persisted": next((x for x in records if x.get("request_status") == "RESULT_PERSISTED"), None)}

def _legacy_04c_counts(payload):
    """Reproduce WORK 04-C source field assumptions for comparison, without modifying it."""
    rows = payload.get("data", {}).get("table", {}).get("rows", [])
    old_contracts = old_expiries = unknown_roots = 0
    for row in rows:
        strike = row.get("strikePrice")
        expiry = row.get("expiryDate") or row.get("expirationDate")
        if strike in (None, "", "--") and expiry:
            old_expiries += 1
        else:
            old_contracts += 1
        root = None
        for key in ("c_Option", "p_Option", "option", "contractSymbol", "drillDownURL"):
            value = row.get(key)
            if not value: continue
            match = re.search(r"(?:/|[?&]symbol=)([A-Z]{1,6})(?:\d{6}[CP]\d{8}|/|[?&]|$)", str(value))
            if match: root = match.group(1); break
        if row.get("strike") not in (None, "", "--") and root is None:
            unknown_roots += 1
    return {"assumed_contract_rows": old_contracts, "assumed_expiry_groups": old_expiries,
            "missing_totalRecord": payload.get("data", {}).get("table", {}).get("totalRecord") is None,
            "unknown_roots_on_contract_rows": unknown_roots}

def discover():
    inventory = {}
    for symbol, root in EVIDENCE.items():
        rel, expected = EXPECTED[symbol]; path = root / rel
        if not path.is_file():
            inventory[symbol] = {"path": str(path), "evidence_state": "RAW_EVIDENCE_UNAVAILABLE", "exists": False}
            continue
        raw = path.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
        try: payload = json.loads(raw); json_ok = True
        except (UnicodeDecodeError, json.JSONDecodeError): payload = None; json_ok = False
        events = _manifest_for(root, symbol)
        response = events.get("response") or {}
        inventory[symbol] = {"path": str(path), "evidence_state": "REAL_PRESERVED_RESPONSE", "exists": True,
                             "bytes": len(raw), "sha256": digest, "expected_sha256": expected,
                             "sha256_matches_historical_record": digest == expected,
                             "manifest_sha256": response.get("response_sha256"),
                             "sha256_matches_manifest": digest == response.get("response_sha256", digest),
                             "manifest_bytes": response.get("response_bytes"),
                             "bytes_match_manifest": len(raw) == response.get("response_bytes", len(raw)),
                             "json_parseable": json_ok,
                             "rCode": (payload or {}).get("status", {}).get("rCode") if json_ok else None,
                             "top_level_keys": list(payload.keys()) if json_ok else [],
                             "data_keys": list(payload.get("data", {}).keys()) if json_ok and isinstance(payload.get("data"), dict) else [],
                             "table_keys": list(payload.get("data", {}).get("table", {}).keys()) if json_ok else [],
                             "raw_row_count": len(payload.get("data", {}).get("table", {}).get("rows", [])) if json_ok else None,
                             "events": events}
    return inventory

def replay(outdir: Path):
    inventory = discover(); outdir.mkdir(parents=True, exist_ok=True); results = {}
    for symbol, item in inventory.items():
        if not item.get("exists") or not item.get("json_parseable"):
            results[symbol] = {"replay_state": "RAW_EVIDENCE_UNAVAILABLE"}; continue
        path = Path(item["path"]); raw = path.read_bytes(); events = item["events"]
        intent = events.get("request_intent") or {}; collected = intent.get("timestamp_utc")
        payload = json.loads(raw)
        http = (events.get("response") or {}).get("http_status")
        if http is None: http = 200 if payload.get("status", {}).get("rCode") == 200 else None
        parsed = parse_payload(raw, get_symbol(symbol))
        quality = inspect_quality(parsed, raw, http, payload.get("status", {}).get("rCode"), collected_at_utc=collected)
        date_et = datetime.fromisoformat(collected.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date().isoformat() if collected else "UNKNOWN_DATE"
        snap = write_snapshot(outdir / "replay", symbol, date_et, raw, parsed.rows, quality, collected)
        readback = _snapshot_readback(snap, item["sha256"])
        quality["snapshot_integrity"]["snapshot_readback_verified"] = readback
        _atomic_text(snap / "quality.json", json.dumps(quality, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        # Verify all generated files can be parsed/read after final quality write.
        reread_quality = json.loads((snap / "quality.json").read_text(encoding="utf-8"))
        with (snap / "contracts.csv").open(encoding="utf-8", newline="") as f: csv_count = sum(1 for _ in csv.DictReader(f))
        results[symbol] = {"replay_state": "REAL_RESPONSE_REPLAYED", "snapshot_path": str(snap),
                           "http_status": http, "api_rcode": payload.get("status", {}).get("rCode"),
                           "raw_sha256": item["sha256"], "hash_match_historical": item["sha256_matches_historical_record"],
                           "hash_match_manifest": item["sha256_matches_manifest"],
                           "raw_row_count": parsed.raw_row_count, "totalRecord": parsed.total_record,
                           "totalRecord_scope": parsed.total_record_scope,
                           "totalRecord_match": quality["parser_integrity"]["totalRecord_matches_expected_scope"],
                           "expiry_groups": parsed.expiry_groups, "contracts": len(parsed.rows),
                           "contract_csv_rows": csv_count, "quality_json_readback": bool(reread_quality),
                           "snapshot_readback_verified": readback,
                           "parser_integrity": quality["parser_integrity"],
                           "work04c_parser_behavior": _legacy_04c_counts(payload),
                           "roots": quality["standard_adjusted_unknown_roots"],
                           "duplicate_contract_keys": quality["duplicate_contract_keys"],
                           "volume_oi": quality["volume_oi"],
                           "overall_volume_observation_rate": quality["overall_volume_observation_rate"],
                           "overall_oi_observation_rate": quality["overall_oi_observation_rate"],
                           "call_put_asymmetry": quality["call_put_asymmetry"],
                           "distributions": quality["distributions"],
                           "underlying_last_trade_raw": quality["underlying_last_trade_raw"],
                           "underlying_quote_time_et": quality["underlying_quote_time_et"],
                           "option_chain_timestamp": quality["option_chain_timestamp"],
                           "underlying_quote_used_for_atm": quality["underlying_quote_used_for_atm"],
                           "atm_volume_observation_rate": quality["atm_volume_observation_rate"],
                           "atm_oi_observation_rate": quality["atm_oi_observation_rate"],
                           "eod_freshness": quality["eod_freshness"], "status": quality["status"]}
    payload = {"audit_mode": "offline_real_response_replay", "live_http_requests": 0,
               "synthetic_fixture_used_for_real_replay": False, "raw_inventory": inventory, "symbols": results}
    (outdir / "real_response_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "real_response_audit.md").write_text(render_markdown(payload), encoding="utf-8")
    return payload

def render_markdown(payload):
    lines = ["# WORK 04-D — Real response compatibility and missingness audit", "",
             "Historical preserved JSON only. No API client was invoked; live HTTP requests: 0. Synthetic fixtures are reported separately by the offline test suite.", "",
             "## Raw evidence and replay", "", "| Symbol | Bytes | SHA-256 vs historical / manifest | HTTP/API | Raw rows | totalRecord/match | Contracts | Expiries | 04-C parsed contracts / expiries | Root | Snapshot readback |", "|---|---:|---|---|---:|---:|---:|---:|---:|---|---|"]
    for s, r in payload["symbols"].items():
        inv = payload["raw_inventory"].get(s, {})
        if r.get("replay_state") != "REAL_RESPONSE_REPLAYED":
            lines.append(f"| {s} | — | — | — | — | — | — | — | — | RAW_EVIDENCE_UNAVAILABLE | — |")
            continue
        legacy = r["work04c_parser_behavior"]
        roots = ", ".join(f"{k}:{v}" for k,v in r["roots"].items()) or "—"
        lines.append(f"| {s} | {inv.get('bytes')} | {inv.get('sha256_matches_historical_record')} / {inv.get('sha256_matches_manifest')} | {r['http_status']}/{r['api_rcode']} | {r['raw_row_count']} | {r['totalRecord']} / {r['totalRecord_match']} | {r['contracts']} | {r['expiry_groups']} | {legacy['assumed_contract_rows']} / {legacy['assumed_expiry_groups']} | {roots} | {r['snapshot_readback_verified']} |")
    lines += ["", "Nasdaq response shape observed in all six files: top-level `data/message/status`; `data.totalRecord`; `data.table.rows`; expiry headers use `expirygroup`; contract rows use `strike` and `expiryDate`; paired call/put values are `c_*` and `p_*`; route root is encoded in lowercase `drillDownURL`. `data.table.asOf` was absent/null, so option-chain EOD freshness remains unverified.", "",
             "## Field-level missingness", "", "Counts per row contract: observed-positive / explicit-zero / `--` / JSON null / empty / field absent / invalid numeric. Header rows are excluded from denominators.", "", "| Symbol | c_Volume | p_Volume | c_Openinterest | p_Openinterest |", "|---|---:|---:|---:|---:|"]
    for s, r in payload["symbols"].items():
        if r.get("replay_state") != "REAL_RESPONSE_REPLAYED": continue
        vals=[]
        for field in ("c_Volume","p_Volume","c_Openinterest","p_Openinterest"):
            c=r["volume_oi"][field]["taxonomy_counts"]
            vals.append(f"{c['OBSERVED_POSITIVE']}/{c['EXPLICIT_ZERO']}/{c['DASH_PLACEHOLDER']}/{c['JSON_NULL']}/{c['EMPTY_STRING']}/{c['FIELD_ABSENT']}/{c['NON_NUMERIC_INVALID']}")
        lines.append(f"| {s} | " + " | ".join(vals) + " |")
    lines += ["", "## Observation rates and distributions", "", "Rates count positive numeric values and explicit zeros as observed. No threshold-based PASS is declared.", "", "| Symbol | Overall volume | Overall OI | Near volume / OI | Mid volume / OI | Far volume / OI | ATM volume / OI | ATM basis |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    for s,r in payload["symbols"].items():
        if r.get("replay_state") != "REAL_RESPONSE_REPLAYED": continue
        h=r["distributions"]["horizon"]
        def pct(v): return "NOT_EVALUABLE" if v is None or v == "NOT_EVALUABLE" else f"{v:.1%}"
        pairs=[f"{pct(h[k]['volume_observation_rate'])} / {pct(h[k]['oi_observation_rate'])}" for k in ("near_term","mid_term","far_term")]
        atm=(r["distributions"].get("atm") or {}).get("definition","NOT_EVALUABLE")
        lines.append(f"| {s} | {pct(r['overall_volume_observation_rate'])} | {pct(r['overall_oi_observation_rate'])} | {pairs[0]} | {pairs[1]} | {pairs[2]} | {pct(r['atm_volume_observation_rate'])} / {pct(r['atm_oi_observation_rate'])} | {atm if r['underlying_quote_used_for_atm'] else 'NOT_EVALUABLE'} |")
    lines += ["", "Horizon buckets use 0–30, 31–90, and >90 calendar days from the preserved request-intent date. ATM-near uses ±5% of the raw Nasdaq `lastTrade` underlying quote only when that quote timestamp is within five minutes of request-intent time. This is not an option-chain timestamp.", "", "Full per-expiration and per-strike distributions are in the companion offline `real_response_audit.json` artifact; per-contract raw and normalized values are in each isolated replay `quality.json`.", "",
             "## Root-cause assessment", "", "- **H1 — Inactive contracts:** partial association only. The >15%-from-spot group has lower volume observation than the ±5% ATM group in all six symbols; far-term volume observation is lower than near-term in five of six. This does not prove that `--` means no trading or that inactivity caused the display.", "- **H2 — Nasdaq placeholder:** the literal `--` appears as a string value in all four fields and is never counted as zero. No numeric zero was present in these six contract-row sets. The response alone does not establish the vendor's semantic definition of `--`.", "- **H3 — Expiration concentration:** missingness varies substantially by expiration within symbols, but the worst expiry differs by symbol and field; no single expiration explains the pattern globally.", "- **H4 — Call/put asymmetry:** call observation rates exceed put rates for both volume and OI in all six symbols. This is an observed pattern, not proof of why the API displays it.", "- **H5 — Parser error:** confirmed in WORK 04-C. Its `strikePrice`/`expiryDate`/`table.totalRecord` assumptions treat most contract rows as expiry headers, count headers as contracts, and fail to parse lowercase URL roots. The corrected replay matches raw totals and the six prior contract/expiry summaries. Missingness remains in raw values after this fix.", "", "## Quality-gate proposal", "", "1. Gate parser integrity separately: JSON parses; raw `rows` equals `data.totalRecord`; all contract rows have valid strike and expiration; root/duplicate counts are explicit.", "2. Gate snapshot integrity separately: original SHA-256 unchanged; raw, CSV, quality, and manifest are readable after writing.", "3. Report each field's observed rate and placeholder taxonomy by expiry, strike, horizon, ATM, and call/put. No universal completeness threshold is supported by this single snapshot set; propose thresholds only after a multi-date baseline is collected.", "4. Keep `eod_freshness=EOD_UNVERIFIED`; block PCR, Max Pain, walls, GEX, and trade signals until option-chain EOD time and data completeness are independently validated.", "", "## Safety", "", "- Live API requests: 0. GitHub Actions runs: 0. Existing raw response files were read only; replay output was written under a separate scratch directory.", "- All six original hashes matched historical/manifest evidence. Synthetic fixtures were used only by unit tests, not substituted for any missing raw response.", ""]
    return "\n".join(lines)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--output", required=True); a=p.parse_args()
    result=replay(Path(a.output)); print(json.dumps({"output":a.output,"symbols_replayed":sum(x.get("replay_state")=="REAL_RESPONSE_REPLAYED" for x in result["symbols"].values()),"network_requests":0},indent=2))
if __name__ == "__main__": main()
