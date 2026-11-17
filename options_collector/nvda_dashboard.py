"""Build a self-contained, offline NVDA options-flow dashboard from verified files."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

from .nvda_strike_map import aggregate_strikes

REFERENCE = {
    "contracts": 2188,
    "strike_count": 444,
    "call_volume_observed_sum": 1457430,
    "put_volume_observed_sum": 953110,
    "call_oi_observed_sum": 9839124,
    "put_oi_observed_sum": 8636754,
}
TOP5_REFERENCE = {
    "call_volume": [(170, 133245), (200, 129267), (160, 125486), (180, 108477), (175, 78244)],
    "put_volume": [(150, 106756), (140, 79929), (155, 78619), (145, 72738), (160, 60599)],
    "call_oi": [(200, 853791), (250, 434092), (300, 391677), (210, 387819), (220, 371382)],
    "put_oi": [(150, 647469), (100, 428220), (140, 420000), (200, 409670), (160, 399856)],
}


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _num(value):
    if value in (None, "", "--"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _same_num(a, b) -> bool:
    if a in (None, "", "--") and b in (None, "", "--"):
        return True
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def load_verified_data(contracts_csv, strike_summary, volume_csv, oi_csv, manifest_json, raw_json, batch_summary) -> tuple[dict, dict]:
    paths = {"contracts_csv": Path(contracts_csv), "strike_summary": Path(strike_summary),
             "volume_csv": Path(volume_csv), "oi_csv": Path(oi_csv), "manifest": Path(manifest_json),
             "raw_json": Path(raw_json), "batch_summary": Path(batch_summary)}
    if any(not p.is_file() for p in paths.values()):
        missing = [str(p) for p in paths.values() if not p.is_file()]
        raise FileNotFoundError("INPUT_EVIDENCE_UNAVAILABLE:" + ",".join(missing))

    manifest = _read_json(paths["manifest"])
    raw = paths["raw_json"].read_bytes()
    raw_sha = hashlib.sha256(raw).hexdigest()
    if manifest.get("symbol") != "NVDA" or raw_sha != manifest.get("raw_sha256") or len(raw) != manifest.get("raw_bytes"):
        raise ValueError("RAW_EVIDENCE_INTEGRITY_FAILED")
    with paths["contracts_csv"].open(encoding="utf-8", newline="") as f:
        contracts = list(csv.DictReader(f))
    if len(contracts) != manifest.get("contract_rows") or any(row.get("symbol") != "NVDA" for row in contracts):
        raise ValueError("CONTRACT_CSV_MANIFEST_MISMATCH")

    computed = aggregate_strikes(contracts)
    source = _read_json(paths["strike_summary"])
    source_rows = {float(row["strike"]): row for row in source.get("rows", [])}
    computed_rows = {float(row["strike"]): row for row in computed["rows"]}
    row_match = set(source_rows) == set(computed_rows)
    if row_match:
        for strike, row in computed_rows.items():
            prior = source_rows[strike]
            for metric in ("call_volume", "put_volume", "call_oi", "put_oi"):
                for suffix in ("_observed_sum", "_observed_count", "_missing_count"):
                    key = metric + suffix
                    if not _same_num(row.get(key), prior.get(key)):
                        row_match = False

    csv_match = True
    for file_key, fields in (
        ("volume_csv", ("call_volume_observed_sum", "put_volume_observed_sum", "call_volume_observed_count", "put_volume_observed_count")),
        ("oi_csv", ("call_oi_observed_sum", "put_oi_observed_sum", "call_oi_observed_count", "put_oi_observed_count")),
    ):
        with paths[file_key].open(encoding="utf-8", newline="") as f:
            file_rows = list(csv.DictReader(f))
        if len(file_rows) != len(computed_rows):
            csv_match = False
            continue
        by_strike = {float(row["strike"]): row for row in file_rows}
        if set(by_strike) != set(computed_rows):
            csv_match = False
            continue
        for strike, row in computed_rows.items():
            for field in fields:
                if not _same_num(by_strike[strike].get(field), row.get(field)):
                    csv_match = False

    batch = _read_json(paths["batch_summary"])
    batch_row = next((row for row in batch.get("results", []) if row.get("symbol") == "NVDA"), None)
    batch_match = bool(batch_row and batch_row.get("response_sha256") == raw_sha and batch_row.get("contracts_count") == len(contracts))
    source_match = row_match and csv_match and batch_match
    totals = computed["totals"]
    totals_match = {key: totals.get(key) == value for key, value in REFERENCE.items()}
    top5_match = {}
    for name, expected in TOP5_REFERENCE.items():
        actual = [(int(row["strike"]), int(row["observed_sum"])) for row in computed["top5"][name]]
        top5_match[name] = actual == expected

    expirations = sorted({str(row.get("expiration")) for row in contracts if row.get("expiration")})
    call_vol_pct = totals["call_volume_observed_count"] / len(contracts) * 100
    put_vol_pct = totals["put_volume_observed_count"] / len(contracts) * 100
    vol_sum = totals["call_volume_observed_sum"] + totals["put_volume_observed_sum"]
    oi_sum = totals["call_oi_observed_sum"] + totals["put_oi_observed_sum"]
    display = source.get("chart_display", {})
    vol_range, oi_range = display.get("volume", {}), display.get("open_interest", {})
    default_min = min(x for x in (vol_range.get("strike_min"), oi_range.get("strike_min")) if x is not None)
    default_max = max(x for x in (vol_range.get("strike_max"), oi_range.get("strike_max")) if x is not None)
    data = {
        "brand": "NAVI OPTIONS LAB", "symbol": "NVDA", "title": "NVDA Options Flow Summary",
        "subtitle": "Observed Nasdaq Options Snapshot · All Expirations",
        "run_id": batch.get("run_id"), "snapshot_timestamp_utc": manifest.get("collected_at_utc"),
        "snapshot_timestamp_et": manifest.get("collected_at_et"), "trading_date_et": manifest.get("trading_date_et"),
        "contracts_count": len(contracts), "expiry_count": len(expirations), "strike_count": len(computed["rows"]),
        "all_expirations": True, "status": "PROVISIONAL",
        "limitations": ["EOD_UNVERIFIED", "MISSINGNESS_CAUSE_UNKNOWN", "FULL_VOLUME_COMPLETENESS_UNVERIFIED"],
        "totals": totals, "observed_volume_pcr": totals["put_volume_observed_sum"] / totals["call_volume_observed_sum"],
        "oi_ratio": totals["put_oi_observed_sum"] / totals["call_oi_observed_sum"],
        "donuts": {
            "volume": {"call": totals["call_volume_observed_sum"], "put": totals["put_volume_observed_sum"],
                       "call_pct": totals["call_volume_observed_sum"] / vol_sum * 100, "put_pct": totals["put_volume_observed_sum"] / vol_sum * 100},
            "oi": {"call": totals["call_oi_observed_sum"], "put": totals["put_oi_observed_sum"],
                   "call_pct": totals["call_oi_observed_sum"] / oi_sum * 100, "put_pct": totals["put_oi_observed_sum"] / oi_sum * 100},
        },
        "rows": computed["rows"], "top5": computed["top5"],
        "default_range": {"min": default_min, "max": default_max},
        "mobile_initial_range": {"min": 140, "max": 220},
        "full_range": {"min": min(float(row["strike"]) for row in computed["rows"]), "max": max(float(row["strike"]) for row in computed["rows"])},
        "coverage_pct": {"call_volume": call_vol_pct, "put_volume": put_vol_pct,
                         "call_oi": totals["call_oi_observed_count"] / len(contracts) * 100,
                         "put_oi": totals["put_oi_observed_count"] / len(contracts) * 100},
        "selected_strike": 170,
        "source": {key: str(path.resolve()) for key, path in paths.items()},
    }
    validation = {
        "raw_sha256": raw_sha, "raw_bytes": len(raw), "manifest_sha256_match": True,
        "manifest_contract_count": manifest.get("contract_rows"), "csv_contract_count": len(contracts),
        "computed_strike_count": len(computed["rows"]), "source_t_json_rows": len(source_rows),
        "snapshot_batch_run_id": batch.get("run_id"), "batch_nvda_sha256_match": batch_match,
        "strike_rows_match_work04t_json": row_match, "strike_csvs_match_recalculation": csv_match,
        "reference_totals_match": totals_match, "top5_match_work04t_reference": top5_match,
        "all_checks_pass": bool(source_match and all(totals_match.values()) and all(top5_match.values()) and len(contracts) == REFERENCE["contracts"] and len(computed["rows"]) == REFERENCE["strike_count"]),
    }
    if not validation["all_checks_pass"]:
        raise ValueError("DASHBOARD_DATA_VALIDATION_FAILED:" + json.dumps(validation, sort_keys=True))
    return data, validation


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">
<title>NAVI OPTIONS LAB · NVDA Flow</title>
<style>
:root{--bg:#090d12;--panel:#111820;--panel2:#151e27;--line:#26323e;--text:#eef4f7;--muted:#8fa0ad;--green:#42e0ad;--green2:#1aa980;--pink:#ff6687;--pink2:#d94368;--cyan:#69c8ff;--amber:#f4c46a;--shadow:0 16px 44px #0006}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 16% -10%,#16312d 0,transparent 38%),radial-gradient(ellipse at 100% 0,#1b2436 0,transparent 31%),var(--bg);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}.shell{max-width:1600px;margin:auto;padding:24px clamp(14px,2.3vw,34px) 48px}.topbar{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:26px}.brand{display:flex;align-items:center;gap:12px;font-size:13px;font-weight:800;letter-spacing:.17em}.brandmark{width:34px;height:34px;border-radius:11px;background:linear-gradient(140deg,#42e0ad,#1a9d87);display:grid;place-items:center;color:#07110f;font-weight:950;font-size:17px;box-shadow:0 0 25px #42e0ad55}.brand small{display:block;color:var(--muted);font-weight:600;letter-spacing:.04em;font-size:10px;margin-top:2px}.head-right{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end}.pill{border:1px solid var(--line);background:#111a22;border-radius:99px;padding:7px 11px;color:#c4d0d7;font-size:11px}.pill.status{border-color:#377d66;color:#72f1c2;background:#10231e;font-weight:800;letter-spacing:.09em}.hero{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin:8px 0 19px}.hero h1{font-size:clamp(27px,3vw,40px);line-height:1.08;letter-spacing:-.04em;margin:0 0 7px}.hero p{margin:0;color:var(--muted)}.hero-symbol{font-size:28px;font-weight:900;letter-spacing:.06em}.hero-symbol span{display:block;color:var(--green);font-size:11px;letter-spacing:.12em;text-align:right}.limitations{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:17px}.lim{color:#e6ba75;background:#241d12;border:1px solid #554326;padding:6px 9px;border-radius:8px;font-size:10px;font-weight:700;letter-spacing:.04em}.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:14px}.card,.panel{background:linear-gradient(145deg,#141c24,#10171e);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}.kpi{padding:16px 18px;position:relative;overflow:hidden}.kpi:after{content:"";position:absolute;width:86px;height:86px;right:-25px;top:-30px;background:var(--glow,#42e0ad);filter:blur(50px);opacity:.22}.kpi label{display:block;color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.kpi strong{display:block;font-variant-numeric:tabular-nums;font-size:clamp(23px,2.5vw,32px);letter-spacing:-.035em;margin:8px 0 2px}.kpi .sub{font-size:10px;color:#768895}.call{color:var(--green)}.put{color:var(--pink)}.summary-grid{display:grid;grid-template-columns:1fr 1fr 1.2fr;gap:13px;margin-bottom:14px}.panel{padding:17px 18px}.panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:13px}.panel h2{font-size:15px;margin:0;font-weight:800;letter-spacing:-.01em}.eyebrow{color:var(--muted);font-size:10px;margin-top:3px}.donut-row{display:flex;align-items:center;gap:19px;min-height:123px}.donut{width:105px;height:105px;position:relative;flex:none}.donut svg{transform:rotate(-90deg);width:100%;height:100%}.donut circle{fill:none;stroke-width:13}.donut .track{stroke:#26323e}.donut .seg{stroke:var(--green);stroke-linecap:butt}.donut .seg.putseg{stroke:var(--pink)}.donut center{position:absolute;inset:0;display:grid;place-content:center;text-align:center;font-size:21px;font-weight:850}.donut center small{display:block;font-size:9px;color:var(--muted);font-weight:650;letter-spacing:.08em}.legend{display:grid;gap:10px;min-width:0}.leg{display:grid;grid-template-columns:8px 1fr auto;gap:8px;align-items:center;font-size:11px}.swatch{height:8px;width:8px;border-radius:3px}.leg b{font-variant-numeric:tabular-nums}.ratio-box{display:flex;align-items:baseline;gap:12px;margin:9px 0}.ratio-box strong{font-size:30px;letter-spacing:-.04em}.ratio-box span{color:var(--muted);font-size:10px}.mini-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:12px}.mini{background:#0d141a;border:1px solid #202b34;padding:10px;border-radius:9px}.mini span{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.07em}.mini b{display:block;font-size:14px;margin-top:4px;font-variant-numeric:tabular-nums}.main-grid{display:grid;grid-template-columns:minmax(0,2.15fr) minmax(300px,.9fr);gap:13px;align-items:start}.chart-panel{padding:17px 18px 13px;min-width:0}.chart-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.toolbar-group{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.toggle{display:inline-flex;align-items:center;gap:6px;color:#c8d4dc;font-size:11px}.toggle input{accent-color:var(--green)}button{border:1px solid #34434f;background:#17212a;color:#dce6eb;border-radius:8px;padding:7px 10px;font:inherit;font-size:10px;font-weight:700;cursor:pointer}button:hover{border-color:var(--green);color:#fff}.rangetext{color:var(--muted);font-size:10px}.chart-wrap{position:relative;margin-top:7px;border-radius:10px;background:linear-gradient(#101820,#0d141a);border:1px solid #1d2933;overflow:hidden}svg.flow{display:block;width:100%;height:320px;touch-action:none;cursor:crosshair}.axis{stroke:#657682;stroke-width:1}.gridline{stroke:#25323d;stroke-width:1;stroke-dasharray:3 5}.zero{stroke:#82929d;stroke-width:1.2}.tick{fill:#8fa0ad;font-size:10px}.axislabel{fill:#a8b5bf;font-size:10px}.bar-call{fill:var(--green);opacity:.88}.bar-put{fill:var(--pink);opacity:.86}.bar-call:hover,.bar-put:hover{opacity:1;filter:drop-shadow(0 0 4px currentColor)}.hoverline{stroke:#e8f1f5;stroke-width:1;stroke-dasharray:2 4;opacity:.65}.tooltip{position:absolute;z-index:10;display:none;pointer-events:none;min-width:190px;background:#081016f2;border:1px solid #435664;border-radius:9px;padding:10px 12px;box-shadow:var(--shadow);font-size:10px}.tooltip strong{display:block;font-size:12px;margin-bottom:6px}.tooltip .ttrow{display:flex;justify-content:space-between;gap:16px;color:#b8c4cb;padding:2px 0}.tooltip .ttrow b{font-variant-numeric:tabular-nums;color:#fff}.below-chart{display:grid;grid-template-columns:1.1fr 1fr;gap:12px;margin-top:12px}.selected,.range-control{background:#0e151b;border:1px solid #23303a;border-radius:10px;padding:12px}.selected-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.selected-head b{font-size:18px}.selected-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:9px}.selected-grid div{font-size:9px;color:var(--muted)}.selected-grid strong{display:block;font-size:12px;color:#e8f0f4;font-variant-numeric:tabular-nums;margin-top:3px}.range-control label{color:var(--muted);font-size:10px;display:block}.range-control input{width:100%;accent-color:var(--green);margin:12px 0 5px}.range-buttons{display:flex;gap:6px;justify-content:flex-end}.stack{display:grid;gap:13px}.rank-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.rank{background:#0e151b;border:1px solid #222e37;border-radius:10px;padding:10px;min-width:0}.rank h3{font-size:10px;text-transform:uppercase;letter-spacing:.07em;margin:0 0 8px;color:#b8c5cd}.rankline{display:grid;grid-template-columns:25px 1fr auto;gap:6px;align-items:center;padding:5px 0;border-bottom:1px solid #1b252d;font-size:10px}.rankline:last-child{border-bottom:0}.rankline .n{color:#667986}.rankline b{font-variant-numeric:tabular-nums}.rankline small{display:block;color:var(--muted);font-size:8px}.rankline .pct{color:#90a1ab;font-size:9px}.keys{margin-top:14px}.key-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:9px}.key{background:linear-gradient(145deg,#14201f,#10171e);border:1px solid #29453f;border-radius:10px;padding:11px}.key.pink{background:linear-gradient(145deg,#24161d,#10171e);border-color:#53303c}.key .strike{font-size:17px;font-weight:900}.key .label{font-size:9px;color:var(--muted);margin:3px 0 7px}.key strong{font-size:12px;font-variant-numeric:tabular-nums}.interpret{margin-top:14px;display:grid;grid-template-columns:1.2fr 1fr;gap:14px}.interpret h2{margin:0 0 9px;font-size:14px}.facts{display:grid;gap:7px}.fact{border-left:2px solid var(--green);padding:5px 9px;color:#d1dce2;font-size:11px}.warning{color:#c5d0d7;font-size:10px;margin:6px 0}.warning:before{content:"• ";color:var(--amber)}.footer{display:flex;justify-content:space-between;gap:12px;color:#687a87;font-size:9px;padding:15px 3px}.hidden{display:none!important}@media(max-width:1100px){.summary-grid{grid-template-columns:1fr 1fr}.summary-grid .ratio-card{grid-column:1/-1}.main-grid{grid-template-columns:1fr}.stack{grid-template-columns:1fr 1fr}.key-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:700px){.shell{padding:13px 9px 26px}.topbar{align-items:flex-start;flex-direction:column;gap:10px;margin-bottom:16px}.brand{letter-spacing:.12em}.head-right{justify-content:flex-start;gap:6px}.pill{white-space:normal;overflow-wrap:anywhere}.hero{align-items:flex-start;flex-direction:column;gap:8px;margin:6px 0 14px}.hero-symbol{font-size:21px}.hero-symbol span{text-align:left}.limitations{margin-bottom:12px}.lim{font-size:9px;overflow-wrap:anywhere}.kpis{grid-template-columns:1fr 1fr;gap:7px}.kpi{padding:11px}.kpi label{font-size:10px}.kpi strong{font-size:21px}.summary-grid{grid-template-columns:1fr}.summary-grid .ratio-card{grid-column:auto}.panel{padding:12px}.chart-panel{padding:11px 9px 10px}.panel-head{gap:7px;margin-bottom:9px}.panel h2{font-size:14px;line-height:1.25;overflow-wrap:anywhere}.stack{grid-template-columns:1fr}.rank-grid{grid-template-columns:1fr 1fr}.key-grid{grid-template-columns:1fr 1fr}.interpret{grid-template-columns:1fr}.below-chart{grid-template-columns:1fr;gap:8px;margin-top:9px}.selected-grid{grid-template-columns:1fr 1fr;gap:9px}.selected-head b{font-size:22px}.selected-grid div{font-size:10px}.selected-grid strong{font-size:14px}.chart-toolbar{align-items:stretch;gap:8px}.toolbar-group{gap:6px}.chart-toolbar button{min-height:40px;padding:8px 9px;flex:1}.toggle{min-height:36px;font-size:12px}.rangetext{font-size:11px;line-height:1.35}.chart-wrap{margin-top:5px}.chart-wrap svg.flow{height:250px}.tick{font-size:13px}.axislabel{font-size:13px}.tooltip{font-size:12px;min-width:205px}.tooltip strong{font-size:14px}.tooltip .ttrow{gap:10px}.range-control{padding:11px}.range-control input{height:32px;margin:8px 0}.range-buttons button{min-height:42px;min-width:150px}.rankline{font-size:11px}.rankline small{font-size:9px}.footer{flex-direction:column;overflow-wrap:anywhere}}
</style></head><body>
<main class="shell">
<header class="topbar"><div class="brand"><div class="brandmark">N</div><div>NAVI OPTIONS LAB<small>REAL-DATA FLOW ANALYTICS</small></div></div><div class="head-right"><span class="pill status">PROVISIONAL</span><span class="pill">EOD UNVERIFIED</span><span class="pill" id="run-id"></span></div></header>
<section class="hero"><div><h1>NVDA Options Flow Summary</h1><p>Observed Nasdaq Options Snapshot · All Expirations</p></div><div class="hero-symbol">NVDA<span>NASDAQ OPTIONS · ALL EXPIRATIONS</span></div></section>
<div class="limitations" id="limitations"></div>
<section class="kpis" id="kpis"></section>
<section class="summary-grid">
 <article class="panel"><div class="panel-head"><div><h2>Calls vs Puts — Volume</h2><div class="eyebrow">Observed contract volume</div></div><span class="pill">VOLUME</span></div><div class="donut-row" id="donut-volume"></div></article>
 <article class="panel"><div class="panel-head"><div><h2>Calls vs Puts — Open Interest</h2><div class="eyebrow">Outstanding contracts</div></div><span class="pill">OPEN INTEREST</span></div><div class="donut-row" id="donut-oi"></div></article>
 <article class="panel ratio-card"><div class="panel-head"><div><h2>Observed Ratios</h2><div class="eyebrow">Computed from observed sums only</div></div></div><div class="ratio-box"><strong id="pcr"></strong><span>Observed Volume PCR<br>Put Volume ÷ Call Volume</span></div><div class="ratio-box"><strong id="oi-ratio"></strong><span>OI Ratio<br>Put OI ÷ Call OI</span></div><div class="mini-grid" id="coverage"></div></article>
</section>
<section class="main-grid">
 <div class="stack-main">
  <article class="panel chart-panel"><div class="panel-head"><div><h2>NVDA Options Volume by Strike</h2><div class="eyebrow">Call above zero · Put below zero for visual separation; put volume itself is positive</div></div><span class="pill">OBSERVED VOLUME</span></div><div class="chart-toolbar"><div class="toolbar-group"><label class="toggle"><input type="checkbox" id="show-call" checked> Call</label><label class="toggle"><input type="checkbox" id="show-put" checked> Put</label><span class="rangetext" id="range-note"></span></div><div class="toolbar-group"><button id="reset-range">Initial view</button><button id="full-range">Full strike range</button></div></div><div class="chart-wrap"><svg id="volume-chart" class="flow" viewBox="0 0 1000 350" role="img" aria-label="NVDA call and put observed volume by strike"></svg><div class="tooltip" id="volume-tooltip"></div></div><div class="below-chart"><div class="selected"><div class="selected-head"><span class="eyebrow">SELECTED STRIKE · OBSERVED VALUES</span><b id="selected-strike">—</b></div><div class="selected-grid" id="selected-values"></div></div><div class="range-control"><label for="zoom">Zoom · drag chart to pan · wheel to zoom</label><input id="zoom" type="range" min="1" max="8" step="0.1" value="1"><div class="range-buttons"><button id="center-selected">Center selected strike</button></div></div></div></article>
  <article class="panel chart-panel"><div class="panel-head"><div><h2>NVDA Open Interest by Strike</h2><div class="eyebrow">Call / Put open contracts · distinct from daily volume</div><div class="eyebrow" id="oi-range-note">Shared strike view · $140–$220</div></div><span class="pill">OPEN INTEREST</span></div><div class="chart-wrap"><svg id="oi-chart" class="flow" viewBox="0 0 1000 350" role="img" aria-label="NVDA call and put open interest by strike"></svg><div class="tooltip" id="oi-tooltip"></div></div></article>
 </div>
 <aside class="stack"><article class="panel"><div class="panel-head"><div><h2>Top 5 Concentration</h2><div class="eyebrow">Share of each observed total</div></div></div><div class="rank-grid" id="rank-grid"></div></article><article class="panel"><div class="panel-head"><div><h2>Snapshot Details</h2><div class="eyebrow">Source manifest metadata</div></div></div><div class="mini-grid" id="meta-grid"></div></article></aside>
</section>
<section class="panel keys"><div class="panel-head"><div><h2>Key Observed Strikes</h2><div class="eyebrow">Concentration markers, not support/resistance or trade signals</div></div></div><div class="key-grid" id="key-grid"></div></section>
<section class="panel interpret"><div><h2>NAVI 관측 수급 해석</h2><div class="facts" id="facts"></div></div><div><h2>해석 제한</h2><p class="warning">전체 만기 합산 관측값이며 향후 주가 방향을 확정하지 않습니다.</p><p class="warning">풋 거래량이나 OI 집중은 자동으로 지지선이 되지 않습니다.</p><p class="warning">콜 거래량 집중은 상승 신호, 풋 거래량 집중은 하락 신호가 아닙니다.</p><p class="warning">매수·매도 방향, 현재 주가, 옵션 프리미엄, OTM/ITM 비율, GEX, 예측 확률은 표시하거나 계산하지 않았습니다.</p></div></section>
<footer class="footer"><span>Source: preserved WORK 04-R NVDA snapshot → WORK 04-T strike aggregation · Offline dashboard</span><span id="source-time"></span></footer>
</main>
<script id="dashboard-data" type="application/json">__EMBEDDED_DATA__</script>
<script>
(()=>{const D=JSON.parse(document.getElementById('dashboard-data').textContent);window.NAVI_DASHBOARD_DATA=D;const fmt=n=>n==null?'—':new Intl.NumberFormat('en-US',{maximumFractionDigits:0}).format(n);const pct=n=>n==null?'—':`${n.toFixed(2)}%`;const $=id=>document.getElementById(id);const safe=(v)=>v==null?'Not observed':fmt(v);
 $('run-id').textContent=`RUN ${D.run_id}`;$('limitations').innerHTML=D.limitations.map(x=>`<span class="lim">${x}</span>`).join('');
 const kpis=[['CALL VOLUME',D.totals.call_volume_observed_sum,'call','Observed contracts'],['PUT VOLUME',D.totals.put_volume_observed_sum,'put','Observed contracts'],['CALL OPEN INTEREST',D.totals.call_oi_observed_sum,'call','Outstanding contracts'],['PUT OPEN INTEREST',D.totals.put_oi_observed_sum,'put','Outstanding contracts']];
 $('kpis').innerHTML=kpis.map(([label,value,kind,sub])=>`<article class="card kpi" style="--glow:var(--${kind==='call'?'green':'pink'})"><label>${label}</label><strong class="${kind}">${fmt(value)}</strong><div class="sub">${sub}</div></article>`).join('');
 function donut(id,obj){const c=2*Math.PI*40,callLen=c*obj.call_pct/100,putLen=c*obj.put_pct/100;$(id).innerHTML=`<div class="donut"><svg viewBox="0 0 100 100"><circle class="track" cx="50" cy="50" r="40"/><circle class="seg" cx="50" cy="50" r="40" stroke-dasharray="${callLen} ${c-callLen}"/><circle class="seg putseg" cx="50" cy="50" r="40" stroke-dasharray="${putLen} ${c-putLen}" stroke-dashoffset="-${callLen}"/></svg><center>${pct(obj.call_pct)}<small>CALL SHARE</small></center></div><div class="legend"><div class="leg"><i class="swatch" style="background:var(--green)"></i><span>Call · ${fmt(obj.call)}</span><b>${pct(obj.call_pct)}</b></div><div class="leg"><i class="swatch" style="background:var(--pink)"></i><span>Put · ${fmt(obj.put)}</span><b>${pct(obj.put_pct)}</b></div></div>`}
 donut('donut-volume',D.donuts.volume);donut('donut-oi',D.donuts.oi);$('pcr').textContent=D.observed_volume_pcr.toFixed(4);$('oi-ratio').textContent=D.oi_ratio.toFixed(4);
 $('coverage').innerHTML=[['Call Vol coverage',D.coverage_pct.call_volume],['Put Vol coverage',D.coverage_pct.put_volume],['Call OI coverage',D.coverage_pct.call_oi],['Put OI coverage',D.coverage_pct.put_oi]].map(x=>`<div class="mini"><span>${x[0]}</span><b>${pct(x[1])}</b></div>`).join('');
 $('meta-grid').innerHTML=[['Contracts',fmt(D.contracts_count)],['Unique strikes',fmt(D.strike_count)],['Expiration groups',fmt(D.expiry_count)],['Trading date ET',D.trading_date_et],['Captured UTC',D.snapshot_timestamp_utc],['Captured ET',D.snapshot_timestamp_et]].map(x=>`<div class="mini"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('');$('source-time').textContent=`Captured ${D.snapshot_timestamp_utc} · ${D.trading_date_et} ET`; 
 const titles={call_volume:'Call Volume',put_volume:'Put Volume',call_oi:'Call OI',put_oi:'Put OI'};const ranks=Object.entries(titles).map(([key,title])=>`<div class="rank"><h3>${title} TOP 5</h3>${D.top5[key].map((r,i)=>`<div class="rankline"><span class="n">0${i+1}</span><b>$${fmt(r.strike)}<small>${fmt(r.observed_sum)}</small></b><span class="pct">${r.share_pct.toFixed(2)}%</span></div>`).join('')}</div>`).join('');$('rank-grid').innerHTML=ranks;
 const facts=[`콜 거래량은 $${fmt(D.top5.call_volume[0].strike)}·$${fmt(D.top5.call_volume[1].strike)}·$${fmt(D.top5.call_volume[2].strike)} 행사가에서 상위 집중을 보입니다.`,`풋 거래량 최대 행사가와 풋 OI 최대 행사가가 모두 $${fmt(D.top5.put_volume[0].strike)}입니다.`,`Call/Put Volume 관측 합계는 각각 ${fmt(D.totals.call_volume_observed_sum)} / ${fmt(D.totals.put_volume_observed_sum)}이며 관측 PCR은 ${D.observed_volume_pcr.toFixed(4)}입니다.`];$('facts').innerHTML=facts.map(x=>`<div class="fact">${x}</div>`).join('');
 const keyCards=[['$'+fmt(D.top5.call_volume[0].strike),'Call Volume Peak',D.top5.call_volume[0].observed_sum,'call'],['$'+fmt(D.top5.put_volume[0].strike),'Put Volume Peak',D.top5.put_volume[0].observed_sum,'pink'],['$'+fmt(D.top5.call_oi[0].strike),'Call OI Peak',D.top5.call_oi[0].observed_sum,'call'],['$'+fmt(D.top5.put_oi[0].strike),'Put OI Peak',D.top5.put_oi[0].observed_sum,'pink'],['$160','Watch Strike',`C ${fmt(D.rows.find(r=>r.strike===160)?.call_volume_observed_sum)} · P ${fmt(D.rows.find(r=>r.strike===160)?.put_volume_observed_sum)}`,'call']];$('key-grid').innerHTML=keyCards.map(k=>`<div class="key ${k[3]==='pink'?'pink':''}"><div class="strike ${k[3]==='pink'?'put':'call'}">${k[0]}</div><div class="label">${k[1]}</div><strong>${typeof k[2]==='number'?fmt(k[2]):k[2]}</strong></div>`).join('');
 const isMobile=window.matchMedia('(max-width:700px)').matches;const initialRange=isMobile&&D.mobile_initial_range?{...D.mobile_initial_range}:{...D.default_range};let range={...initialRange},full={...D.full_range},selected=D.selected_strike,zoomLevel=1,drag=null;const maxZoom=Math.min(32,Math.max(8,(full.max-full.min)/(initialRange.max-initialRange.min)));$('zoom').max=String(maxZoom);const svgNs='http://www.w3.org/2000/svg';const create=(name,attrs={})=>{const el=document.createElementNS(svgNs,name);for(const [k,v]of Object.entries(attrs))el.setAttribute(k,v);return el};
 const visibleRows=()=>D.rows.filter(r=>r.strike>=range.min&&r.strike<=range.max);
 function draw(id,callKey,putKey,tooltipId){const svg=$(id);while(svg.firstChild)svg.removeChild(svg.firstChild);const W=isMobile?560:1000,H=350,L=isMobile?58:66,R=isMobile?12:20,T=isMobile?12:17,B=48,plotW=W-L-R,plotH=H-T-B,mid=T+plotH/2,rows=visibleRows();svg.setAttribute('viewBox',`0 0 ${W} ${H}`);if(!rows.length)return;const max=Math.max(1,...rows.flatMap(r=>[r[callKey]??0,r[putKey]??0]));const step=(range.max-range.min)||1;const xval=x=>L+(x-range.min)/step*plotW;const yScale=(plotH/2-10)/max;
  for(let i=-2;i<=2;i++){const y=mid-i*(plotH/4);svg.appendChild(create('line',{x1:L,y1:y,x2:W-R,y2:y,class:i===0?'zero':'gridline'}));const lab=create('text',{x:L-9,y:y+3,'text-anchor':'end',class:'tick'});lab.textContent=fmt(max*i/2);svg.appendChild(lab)}
  const stride=Math.max(1,Math.ceil(rows.length/(isMobile?6:13)));rows.filter((_,i)=>i%stride===0||i===rows.length-1).forEach(r=>{const x=xval(r.strike);svg.appendChild(create('line',{x1:x,y1:T,x2:x,y2:H-B,class:'gridline',opacity:'.3'}));const lab=create('text',{x,y:H-B+17,'text-anchor':'middle',class:'tick'});lab.textContent='$'+fmt(r.strike);svg.appendChild(lab)});
  const barW=Math.max(isMobile?3:1,Math.min(isMobile?12:10,(plotW/Math.max(1,rows.length))*0.68));const callsOn=$('show-call').checked,putsOn=$('show-put').checked;
  rows.forEach(r=>{const x=xval(r.strike);if(callsOn&&r[callKey]!=null){const h=r[callKey]*yScale;const rect=create('rect',{x:x-barW/2,y:mid-h,width:barW,height:Math.max(h,.65),rx:'.5',class:'bar-call','data-strike':r.strike});rect.addEventListener('pointermove',e=>showTip(e,r,tooltipId,callKey,putKey));rect.addEventListener('pointerleave',()=>hideTip(tooltipId));rect.addEventListener('click',()=>select(r.strike));svg.appendChild(rect)}if(putsOn&&r[putKey]!=null){const h=r[putKey]*yScale;const rect=create('rect',{x:x-barW/2,y:mid,width:barW,height:Math.max(h,.65),rx:'.5',class:'bar-put','data-strike':r.strike});rect.addEventListener('pointermove',e=>showTip(e,r,tooltipId,callKey,putKey));rect.addEventListener('pointerleave',()=>hideTip(tooltipId));rect.addEventListener('click',()=>select(r.strike));svg.appendChild(rect)}});
  const xlabel=create('text',{x:L+plotW/2,y:H-8,'text-anchor':'middle',class:'axislabel'});xlabel.textContent='Strike Price ($)';svg.appendChild(xlabel);
  const cross=create('line',{id:id+'-cross',y1:T,y2:H-B,class:'hoverline',visibility:'hidden'});svg.appendChild(cross);svg.onpointermove=e=>{if(drag){const dx=(e.clientX-drag.x)/svg.getBoundingClientRect().width*step;range={min:Math.max(full.min,drag.min-dx),max:Math.min(full.max,drag.max-dx)};if(range.max-range.min<step/100){range.max=range.min+step/100}render()}else{const rect=svg.getBoundingClientRect(),local=(e.clientX-rect.left)/rect.width*W;cross.setAttribute('x1',local);cross.setAttribute('x2',local);cross.setAttribute('visibility','visible')}};svg.onpointerleave=()=>{if(!drag)cross.setAttribute('visibility','hidden')};svg.onpointerdown=e=>{drag={x:e.clientX,min:range.min,max:range.max};svg.setPointerCapture(e.pointerId)};svg.onpointerup=e=>{if(!drag)return;const start=drag;drag=null;if(Math.abs(e.clientX-start.x)<8){const rect=svg.getBoundingClientRect(),local=(e.clientX-rect.left)/rect.width*W,target=Math.max(range.min,Math.min(range.max,range.min+(local-L)/plotW*step)),nearest=rows.reduce((a,b)=>Math.abs(b.strike-target)<Math.abs(a.strike-target)?b:a,rows[0]);if(nearest)select(nearest.strike)}};svg.onpointercancel=()=>{drag=null};svg.onwheel=e=>{e.preventDefault();const rect=svg.getBoundingClientRect(),px=(e.clientX-rect.left)/rect.width*W;const center=range.min+(px-L)/plotW*(range.max-range.min);const factor=e.deltaY<0?.8:1.25;const width=Math.min(full.max-full.min,Math.max((full.max-full.min)/8,(range.max-range.min)*factor));const ratio=(center-range.min)/(range.max-range.min||1);range={min:Math.max(full.min,center-width*ratio),max:Math.min(full.max,center+width*(1-ratio))};render()};svg.dataset.rendered='true';
 }
 function showTip(e,r,id,c,p){const t=$(id),svg=e.currentTarget.ownerSVGElement,box=svg.getBoundingClientRect();t.style.display='block';t.style.left=Math.min(e.clientX-box.left+12,box.width-205)+'px';t.style.top=Math.max(8,e.clientY-box.top-35)+'px';t.innerHTML=`<strong>NVDA · $${fmt(r.strike)}</strong><div class="ttrow"><span>Call Volume</span><b>${safe(r.call_volume_observed_sum)} · ${r.call_volume_observed_count} obs.</b></div><div class="ttrow"><span>Put Volume</span><b>${safe(r.put_volume_observed_sum)} · ${r.put_volume_observed_count} obs.</b></div><div class="ttrow"><span>Call OI</span><b>${safe(r.call_oi_observed_sum)} · ${r.call_oi_observed_count} obs.</b></div><div class="ttrow"><span>Put OI</span><b>${safe(r.put_oi_observed_sum)} · ${r.put_oi_observed_count} obs.</b></div><div class="ttrow"><span>Expirations</span><b>${r.expiration_count}</b></div>`}
 function hideTip(id){$(id).style.display='none'}function select(s){selected=s;render();const r=D.rows.find(x=>x.strike===s);$('selected-strike').textContent=r?'$'+fmt(s):'—';$('selected-values').innerHTML=[['Call Volume',r?.call_volume_observed_sum],['Put Volume',r?.put_volume_observed_sum],['Call OI',r?.call_oi_observed_sum],['Put OI',r?.put_oi_observed_sum]].map(x=>`<div>${x[0]}<strong>${safe(x[1])}</strong></div>`).join('')}
 function render(){draw('volume-chart','call_volume_observed_sum','put_volume_observed_sum','volume-tooltip');draw('oi-chart','call_oi_observed_sum','put_oi_observed_sum','oi-tooltip');$('range-note').textContent=`Initial view $${fmt(range.min)}–$${fmt(range.max)} · all 444 strike rows retained; use Full strike range for $${fmt(full.min)}–$${fmt(full.max)}`;$('oi-range-note').textContent=`Shared strike view · $${fmt(range.min)}–$${fmt(range.max)}`;const span=range.max-range.min,base=full.max-full.min;$('zoom').value=Math.min(maxZoom,Math.max(1,base/span))}
 $('show-call').onchange=render;$('show-put').onchange=render;$('reset-range').onclick=()=>{range={...initialRange};render()};$('full-range').onclick=()=>{range={...full};render()};$('zoom').oninput=e=>{zoomLevel=Number(e.target.value);const center=(range.min+range.max)/2,width=(full.max-full.min)/zoomLevel;range={min:Math.max(full.min,center-width/2),max:Math.min(full.max,center+width/2)};render()};$('center-selected').onclick=()=>{const width=range.max-range.min,half=width/2;range={min:Math.max(full.min,selected-half),max:Math.min(full.max,selected+half)};render()};render();select(selected);window.NAVI_READY=true;
})();
</script></body></html>'''


def build_dashboard(data: dict, validation: dict, output_dir: str | Path, *, render_png: bool = True) -> dict:
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    names = ("nvda_options_dashboard.html", "nvda_options_dashboard.png", "nvda_dashboard_data.json", "nvda_dashboard_validation.json")
    existing = [destination / name for name in names if (destination / name).exists()]
    if existing:
        raise FileExistsError("DASHBOARD_OUTPUT_EXISTS:" + ",".join(str(x) for x in existing))
    safe_json = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = HTML.replace("__EMBEDDED_DATA__", safe_json)
    data_path = destination / "nvda_dashboard_data.json"
    validation_path = destination / "nvda_dashboard_validation.json"
    html_path = destination / "nvda_options_dashboard.html"
    png_path = destination / "nvda_options_dashboard.png"
    _write_atomic(data_path, (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    _write_atomic(html_path, html.encode("utf-8"))
    rendered = False
    if render_png:
        _render_data_png(data, png_path)
        rendered = True
    validation = dict(validation)
    validation["dashboard_png_render"] = "same_verified_data_matplotlib"
    validation["html_browser_render"] = "UNVERIFIED"
    validation["html_browser_render_note"] = "Chromium blocked file:/data: pages by organization policy; isolated localhost was unreachable from the browser session."
    _write_atomic(validation_path, (json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    return {"html": str(html_path), "png": str(png_path) if rendered else None,
            "data_json": str(data_path), "validation_json": str(validation_path),
            "browser_rendered": False, "png_rendered_from_verified_data": rendered}


def _render_browser_png(html_path: Path, png_path: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1200}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.wait_for_function("window.NAVI_READY === true", timeout=15000)
        page.screenshot(path=str(png_path), full_page=True)
        browser.close()
    if errors:
        png_path.unlink(missing_ok=True)
        raise RuntimeError("BROWSER_RENDER_ERROR:" + " | ".join(errors))


def _render_data_png(data: dict, png_path: Path) -> None:
    """Render a review image from the same validated data embedded in the HTML."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    from matplotlib.ticker import FuncFormatter

    bg, panel, text, muted = "#090d12", "#111820", "#eef4f7", "#8fa0ad"
    green, pink, line = "#42e0ad", "#ff6687", "#26323e"
    fig = plt.figure(figsize=(16, 17), dpi=140, facecolor=bg)
    gs = GridSpec(6, 4, figure=fig, height_ratios=[.34, .72, 1.05, 1.25, .9, .78], hspace=.34, wspace=.24,
                  left=.045, right=.96, top=.94, bottom=.045)

    fig.text(.047, .975, "NAVI OPTIONS LAB  /  NVDA", color=green, fontsize=10, weight="bold", va="top")
    fig.text(.047, .946, "NVDA Options Flow Summary", color=text, fontsize=23, weight="bold", va="top")
    fig.text(.047, .919, "Observed Nasdaq Options Snapshot · All Expirations", color=muted, fontsize=10, va="top")
    fig.text(.96, .972, "PROVISIONAL", color=green, fontsize=10, weight="bold", ha="right", va="top")
    fig.text(.96, .949, f"{data['contracts_count']:,} contracts  ·  {data['strike_count']:,} strikes  ·  {data['expiry_count']} expirations", color=muted, fontsize=9, ha="right", va="top")
    fig.text(.96, .927, f"RUN {data['run_id']}  ·  {data['snapshot_timestamp_utc']} UTC", color=muted, fontsize=8, ha="right", va="top")

    totals = data["totals"]
    metrics = [("CALL VOLUME", totals["call_volume_observed_sum"], green),
               ("PUT VOLUME", totals["put_volume_observed_sum"], pink),
               ("CALL OPEN INTEREST", totals["call_oi_observed_sum"], green),
               ("PUT OPEN INTEREST", totals["put_oi_observed_sum"], pink)]
    for idx, (label, value, color) in enumerate(metrics):
        ax = fig.add_subplot(gs[1, idx]); ax.set_facecolor(panel)
        for sp in ax.spines.values(): sp.set_color(line)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.text(.08, .73, label, color=muted, fontsize=8, weight="bold", transform=ax.transAxes)
        ax.text(.08, .37, f"{value:,.0f}", color=color, fontsize=18, weight="bold", transform=ax.transAxes)
        ax.text(.08, .13, "OBSERVED CONTRACT VALUES", color=muted, fontsize=7, transform=ax.transAxes)

    for col, name, title, call_key, put_key in (
        (0, "volume", "CALLS VS PUTS · VOLUME", "call_volume_observed_sum", "put_volume_observed_sum"),
        (1, "oi", "CALLS VS PUTS · OPEN INTEREST", "call_oi_observed_sum", "put_oi_observed_sum"),
    ):
        ax = fig.add_subplot(gs[2, col]); ax.set_facecolor(panel)
        obj = data["donuts"][name]
        ax.pie([obj["call"], obj["put"]], colors=[green, pink], startangle=90, radius=.72,
               wedgeprops={"width": .22, "edgecolor": panel, "linewidth": 2})
        ax.text(0, .06, f"{obj['call_pct']:.1f}%", color=text, ha="center", va="center", fontsize=15, weight="bold")
        ax.text(0, -.2, "CALL SHARE", color=muted, ha="center", va="center", fontsize=7)
        ax.set_title(title, color=text, fontsize=9, weight="bold", pad=12)
        ax.text(-.92, -.91, f"Call  {obj['call']:,}  ({obj['call_pct']:.2f}%)", color=green, fontsize=8)
        ax.text(-.92, -.77, f"Put    {obj['put']:,}  ({obj['put_pct']:.2f}%)", color=pink, fontsize=8)
        ax.set_aspect("equal")

    for col, title, value, color in ((2, "OBSERVED VOLUME PCR", data["observed_volume_pcr"], green),
                                     (3, "OBSERVED PUT / CALL OI", data["oi_ratio"], pink)):
        ax = fig.add_subplot(gs[2, col]); ax.set_facecolor(panel)
        for sp in ax.spines.values(): sp.set_color(line)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.text(.08, .76, title, color=muted, fontsize=8, weight="bold", transform=ax.transAxes)
        ax.text(.08, .47, f"{value:.4f}", color=color, fontsize=24, weight="bold", transform=ax.transAxes)
        ax.text(.08, .2, "Observed sum ratio · PROVISIONAL", color=muted, fontsize=8, transform=ax.transAxes)

    rows = data["rows"]
    xs = [r["strike"] for r in rows]
    for col, title, call_key, put_key, ylabel in (
        (slice(0, 2), "NVDA Options Volume by Strike", "call_volume_observed_sum", "put_volume_observed_sum", "Observed Option Volume"),
        (slice(2, 4), "NVDA Open Interest by Strike", "call_oi_observed_sum", "put_oi_observed_sum", "Observed Open Interest"),
    ):
        ax = fig.add_subplot(gs[3, col]); ax.set_facecolor(panel)
        ax.bar(xs, [r[call_key] if r[call_key] is not None else math.nan for r in rows], color=green, width=1.0, alpha=.9, label="Call")
        ax.bar(xs, [-(r[put_key]) if r[put_key] is not None else math.nan for r in rows], color=pink, width=1.0, alpha=.9, label="Put · shown below zero")
        ax.axhline(0, color="#90a0ad", linewidth=.7)
        ax.set_title(title, color=text, fontsize=10, weight="bold", loc="left", pad=9)
        ax.set_xlabel("Strike Price ($)", color=muted, fontsize=8); ax.set_ylabel(ylabel, color=muted, fontsize=8)
        ax.tick_params(colors=muted, labelsize=7); ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
        ax.grid(axis="y", color=line, linewidth=.5, alpha=.6); ax.legend(frameon=False, labelcolor=text, fontsize=7, loc="upper right")
        view = data["default_range"]
        ax.set_xlim(view["min"], view["max"])
        for sp in ax.spines.values(): sp.set_color(line)

    rank_defs = (("call_volume", "CALL VOLUME TOP 5", green), ("put_volume", "PUT VOLUME TOP 5", pink),
                 ("call_oi", "CALL OPEN INTEREST TOP 5", green), ("put_oi", "PUT OPEN INTEREST TOP 5", pink))
    for col, (key, title, color) in enumerate(rank_defs):
        ax = fig.add_subplot(gs[4, col]); ax.set_facecolor(panel)
        for sp in ax.spines.values(): sp.set_color(line)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.text(.07, .88, title, color=color, fontsize=8, weight="bold", transform=ax.transAxes)
        for idx, row in enumerate(data["top5"][key]):
            y = .70 - idx * .135
            ax.text(.08, y, f"0{idx + 1}", color=muted, fontsize=8, transform=ax.transAxes)
            ax.text(.25, y, f"${row['strike']:,.0f}", color=text, fontsize=8, weight="bold", transform=ax.transAxes)
            ax.text(.57, y, f"{row['observed_sum']:,.0f}", color=text, fontsize=8, ha="right", transform=ax.transAxes)
            ax.text(.93, y, f"{row['share_pct']:.2f}%", color=color, fontsize=7, ha="right", transform=ax.transAxes)

    ax = fig.add_subplot(gs[5, :2]); ax.set_facecolor(panel)
    for sp in ax.spines.values(): sp.set_color(line)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    keys = (("$170", "Call Volume Peak", data["top5"]["call_volume"][0]["observed_sum"], green),
            ("$150", "Put Volume / OI Peak", data["top5"]["put_volume"][0]["observed_sum"], pink),
            ("$200", "Call OI Peak", data["top5"]["call_oi"][0]["observed_sum"], green),
            ("$160", "Watch · Call / Put Vol", "125,486 / 60,599", green))
    for idx, (strike, label, value, color) in enumerate(keys):
        x = .04 + idx * .24
        ax.text(x, .72, strike, color=color, fontsize=14, weight="bold", transform=ax.transAxes)
        ax.text(x, .48, label, color=muted, fontsize=7, transform=ax.transAxes)
        ax.text(x, .23, f"{value:,}" if isinstance(value, int) else value, color=text, fontsize=9, weight="bold", transform=ax.transAxes)
    ax = fig.add_subplot(gs[5, 2:]); ax.set_facecolor(panel)
    for sp in ax.spines.values(): sp.set_color(line)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(.06, .78, "NAVI OBSERVED FLOW · PROVISIONAL", color=green, fontsize=8, weight="bold", transform=ax.transAxes)
    ax.text(.06, .52, f"Call volume is concentrated at ${data['top5']['call_volume'][0]['strike']}, ${data['top5']['call_volume'][1]['strike']}, and ${data['top5']['call_volume'][2]['strike']}.", color=text, fontsize=8, transform=ax.transAxes)
    ax.text(.06, .29, "Strike concentrations describe observed contracts; they do not confirm support, resistance, or price direction.", color=muted, fontsize=7, transform=ax.transAxes)

    fig.text(.047, .02,
             "EOD_UNVERIFIED  ·  MISSINGNESS_CAUSE_UNKNOWN  ·  FULL_VOLUME_COMPLETENESS_UNVERIFIED  ·  Puts drawn below zero for visual comparison only",
             color="#e6ba75", fontsize=8, va="bottom")
    fig.savefig(png_path, facecolor=bg, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description="Generate a verified offline NVDA options-flow dashboard")
    p.add_argument("--contracts-csv", required=True)
    p.add_argument("--strike-summary", required=True)
    p.add_argument("--volume-csv", required=True)
    p.add_argument("--oi-csv", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--raw-json", required=True)
    p.add_argument("--batch-summary", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--no-png", action="store_true", help="Only write HTML/JSON; skip browser rendering")
    args = p.parse_args()
    data, validation = load_verified_data(args.contracts_csv, args.strike_summary, args.volume_csv,
                                          args.oi_csv, args.manifest, args.raw_json, args.batch_summary)
    result = build_dashboard(data, validation, args.output_dir, render_png=not args.no_png)
    print(json.dumps({"result": "NVDA_REAL_DASHBOARD_READY" if result["browser_rendered"] else "NVDA_REAL_DASHBOARD_RENDER_UNVERIFIED",
                      **result, "validation": validation}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

