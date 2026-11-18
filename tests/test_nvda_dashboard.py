import json
import re
import shutil
import subprocess
import tempfile
import unittest
import csv
from pathlib import Path

from options_collector.nvda_dashboard import HTML, build_dashboard, load_verified_data, _validate_price_reference
from options_collector.nvda_strike_map import aggregate_strikes

RUN_ROOT = Path("/workspace/scratch/navi-options-work04r-live/naviopt04r-20261117T051903Z-80a05c75")
NVDA_DIR = RUN_ROOT / "snapshots/data/options/2026-11-17/NVDA/2026-11-17T05-19-47.924836Z"
T_OUT = Path("/workspace/scratch/navi-options-work04t-output-v2")


def _load_real():
    return load_verified_data(
        NVDA_DIR / "contracts.csv", T_OUT / "nvda_strike_summary.json",
        T_OUT / "nvda_strike_volume.csv", T_OUT / "nvda_strike_oi.csv",
        NVDA_DIR / "manifest.json", NVDA_DIR / "raw.json", RUN_ROOT / "batch_summary.json",
    )


def _run_viewport_js(expression, stdin=None):
    if not shutil.which("node"):
        raise unittest.SkipTest("Node.js unavailable; JavaScript viewport math not executed")
    match = re.search(r"/\* VIEWPORT_MATH_START \*/(.*?)/\* VIEWPORT_MATH_END \*/", HTML, re.S)
    if not match:
        raise AssertionError("Viewport helper block missing from dashboard HTML")
    script = match.group(1) + "\nconsole.log(JSON.stringify(" + expression + "));"
    result = subprocess.run(["node", "-e", script], input=stdin, check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def _run_quote_warning_js(expression):
    if not shutil.which("node"):
        raise unittest.SkipTest("Node.js unavailable; JavaScript quote-warning logic not executed")
    match = re.search(r"/\* QUOTE_WARNING_START \*/(.*?)/\* QUOTE_WARNING_END \*/", HTML, re.S)
    if not match:
        raise AssertionError("Quote warning helper missing from dashboard HTML")
    result = subprocess.run(["node", "-e", match.group(1) + "\nconsole.log(JSON.stringify(" + expression + "));"],
                            check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def _run_tooltip_position_js(expression):
    if not shutil.which("node"):
        raise unittest.SkipTest("Node.js unavailable; tooltip positioning helper not executed")
    match = re.search(r"/\* TOOLTIP_POSITION_START \*/(.*?)/\* TOOLTIP_POSITION_END \*/", HTML, re.S)
    if not match:
        raise AssertionError("Tooltip position helper missing from dashboard HTML")
    result = subprocess.run(["node", "-e", match.group(1) + "\nconsole.log(JSON.stringify(" + expression + "));"],
                            check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def _run_data_binding_js(expression, contracts):
    if not shutil.which("node"):
        raise unittest.SkipTest("Node.js unavailable; JavaScript data-binding helpers not executed")
    match = re.search(r"/\* DATA_BINDING_START \*/(.*?)/\* DATA_BINDING_END \*/", HTML, re.S)
    if not match:
        raise AssertionError("Data-binding helper block missing from dashboard HTML")
    script = match.group(1) + "\nconst input=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(" + expression + "));"
    result = subprocess.run(["node", "-e", script], input=json.dumps(contracts), check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


class NvdaDashboardTests(unittest.TestCase):
    def test_hotfix05_strike_labels_preserve_half_dollar_identity_and_expiration_counts(self):
        data, _ = _load_real()
        nov18_1575 = next(c for c in data["contracts"] if c["expiration"] == "2026-11-18" and c["strike"] == 157.5)
        all_1575 = [c for c in data["contracts"] if c["strike"] == 157.5]
        all_158 = [c for c in data["contracts"] if c["strike"] == 158.0]
        self.assertEqual((nov18_1575["call_volume"], nov18_1575["put_volume"], nov18_1575["call_oi"], nov18_1575["put_oi"]), (11767, 10824, 1074, 5337))
        self.assertEqual(len({c["expiration"] for c in all_1575}), 6)
        self.assertEqual(len({c["expiration"] for c in all_158}), 1)
        self.assertEqual(tuple(sum(c[k] or 0 for c in all_158) for k in ("call_volume", "put_volume", "call_oi", "put_oi")), (815, 755, 1392, 6755))
        result = _run_data_binding_js(
            "(()=>{const counts=strikeExpirationCounts(input);return {label1575:strikeFmt(157.5),label158:strikeFmt(158),count1575:counts.get(157.5),count158:counts.get(158)}})()",
            data["contracts"],
        )
        self.assertEqual(result, {"label1575": "157.5", "label158": "158", "count1575": 6, "count158": 1})

    def test_hotfix05_scope_and_tooltip_state_are_explicit_and_stale_tips_clear(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("expirationCounts.get(c.strike)||0", html)
        self.assertIn("전체 만기 합산 · 대상 ", html)
        self.assertIn("해당 행사가 관측 만기", html)
        self.assertIn("요약 구간 ", html)
        self.assertIn("function renderViewport(){hideTip('volume-tooltip');hideTip('oi-tooltip');", html)
        self.assertIn("$'+strikeFmt(selected)", html)
        self.assertIn("$'+strikeFmt(c.strike)", html)

    def test_volatility_status_is_source_derived_and_never_displays_fake_metrics(self):
        data, _ = _load_real()
        status = data["volatility_status"]
        self.assertEqual(status["iv"], "SOURCE_ABSENT")
        self.assertEqual(status["iv_fields_found"], [])
        self.assertEqual(status["iv_calculation"], "IV_CALCULATION_BLOCKED")
        self.assertEqual(status["iv_rank"], "IV_RANK_UNAVAILABLE")
        self.assertEqual(status["iv_percentile"], "IV_PERCENTILE_UNAVAILABLE")
        self.assertEqual(status["hv_rv"], "UNAVAILABLE_WITHOUT_VERIFIED_UNDERLYING_OHLC_HISTORY")
        self.assertEqual(data["price_reference"]["price_type"], "HISTORICAL_REFERENCE")
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, _load_real()[1], Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("변동성 분석 · 데이터 상태", html)
        self.assertIn("SOURCE_ABSENT", html)
        self.assertIn("IV_RANK_UNAVAILABLE", html)
        self.assertNotIn("IV 0%", html)
        self.assertNotIn("IV Rank 50", html)
        self.assertIn("IV_CALCULATION_BLOCKED", json.dumps(data["volatility_status"]))

    def test_raw_crossed_call_quote_at_160_is_preserved_and_maps_correctly(self):
        data, _ = _load_real()
        contract = next(c for c in data["contracts"] if c["expiration"] == "2026-11-18" and c["strike"] == 160)
        self.assertEqual((contract["call_bid"], contract["call_ask"]), (4.95, 4.85))
        self.assertEqual((contract["put_bid"], contract["put_ask"]), (8.60, 8.65))
        with Path(data["source"]["contracts_csv"]).open(encoding="utf-8", newline="") as handle:
            csv_contract = next(row for row in csv.DictReader(handle) if row["expiration"] == "2026-11-18" and float(row["strike"]) == 160)
        raw = json.loads(csv_contract["raw_row_json"])
        self.assertEqual((raw["c_Bid"], raw["c_Ask"], raw["p_Bid"], raw["p_Ask"]), ("4.95", "4.85", "8.60", "8.65"))
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, _load_real()[1], Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("c.call_bid", html)
        self.assertIn("c.call_ask", html)
        self.assertIn("quoteWarnings(c).map", html)
        self.assertIn("호가 역전 관측 — ", html)
        self.assertIn("원본값을 유지하며 정상적인 거래 가능 호가로 보증하지 않습니다.", html)

    def test_quote_warning_helper_handles_crossed_normal_missing_and_zero_without_mutation(self):
        observed = _run_quote_warning_js("(()=>{const crossed={call_bid:4.95,call_ask:4.85,put_bid:8.6,put_ask:8.65};const before=JSON.stringify(crossed);return {crossed:quoteWarnings(crossed),normal:quoteWarnings({call_bid:1,call_ask:1.1,put_bid:0,put_ask:0.1}),missing:quoteWarnings({call_bid:null,call_ask:1}),unchanged:JSON.stringify(crossed)===before}})()")
        self.assertEqual(observed["crossed"], [{"side":"콜","bid":4.95,"ask":4.85}])
        self.assertEqual(observed["normal"], [])
        self.assertEqual(observed["missing"], [])
        self.assertTrue(observed["unchanged"])

    def test_tooltip_position_stays_inside_small_chart_and_flips_below_when_needed(self):
        result = _run_tooltip_position_js("(()=>({right:tooltipPosition(312,120,320,250,240,92),left:tooltipPosition(1,240,320,250,210,80),top:tooltipPosition(155,4,320,250,190,90)}))()")
        widths = {"right":240,"left":210,"top":190}
        heights = {"right":92,"left":80,"top":90}
        for key, pos in result.items():
            self.assertGreaterEqual(pos["left"], 6)
            self.assertGreaterEqual(pos["top"], 6)
            self.assertLessEqual(pos["left"] + widths[key], 320)
            self.assertLessEqual(pos["top"] + heights[key], 250)
        self.assertEqual(result["top"]["top"], 16)

    def test_hotfix04_compact_mobile_buttons_range_labels_and_number_formatting(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr));width:100%", html)
        self.assertIn("white-space:nowrap", html)
        self.assertIn("차트 표시 경계 약 ", html)
        self.assertIn("연속 차트 경계값 ", html)
        self.assertIn("실제 계약 행사가와 다를 수 있음", html)
        self.assertIn("콜 '+safe(watch.call_volume_observed_sum)+' · 풋 '+safe(watch.put_volume_observed_sum)", html)
        self.assertIn("aria-pressed',String(atInitial)", html)
        self.assertIn("aria-pressed',String(viewMode==='full-overview')", html)

    def test_volatility_details_show_korean_reason_before_internal_codes(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("원본 데이터 미제공", html)
        self.assertIn("계산 입력 검증 미완료", html)
        self.assertIn("과거 IV 이력 없음", html)
        self.assertIn("행사가별 IV 미확보", html)
        self.assertIn("기초자산 가격 이력 미확보", html)
        self.assertIn("<code>'+status+'</code>", html)
        self.assertIn('<details class="panel volatility-status">', html)
        self.assertNotIn("IV 0%", html)
        self.assertNotIn("예상 변동폭", html)

    def test_2026_11_18_strike_165_card_and_chain_values_remain_in_sync(self):
        data, _ = _load_real()
        contracts = [c for c in data["contracts"] if c["expiration"] == "2026-11-18" and c["strike"] == 165]
        self.assertEqual(len(contracts), 1)
        contract = contracts[0]
        self.assertEqual((contract["call_volume"], contract["put_volume"], contract["call_oi"], contract["put_oi"]),
                         (20559, 1841, 6163, 3148))
        self.assertEqual(data["raw_sha256"], "85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce")
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, _load_real()[1], Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("safe(watch.call_volume_observed_sum)", html)
        self.assertIn("select(Number(tr.dataset.strike))", html)
        self.assertIn("classList.toggle('selected',Number(tr.dataset.strike)===selected)", html)

    def test_hotfix02_zoom_pan_regression_and_key_card_number_format_are_retained(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("const zoomSpan=(level,bounds)", html)
        self.assertIn("const ticks=(r,plotWidth,minSpacing)", html)
        self.assertIn("touch-action:pan-y", html)
        self.assertIn("VM.shift(gesture.startRange,delta,full)", html)
        self.assertIn("typeof k[2]==='number'?fmt(k[2]):k[2]", html)
        self.assertIn("과거 참고가격 $156.14", html)

    def test_historical_last_trade_is_not_mislabeled_as_current(self):
        data, validation = _load_real()
        ref = data["price_reference"]
        self.assertEqual(ref["price"], 156.14)
        self.assertEqual(ref["currency"], "USD")
        self.assertEqual(ref["price_type"], "HISTORICAL_REFERENCE")
        self.assertEqual(ref["price_timestamp"], "2026-11-16")
        self.assertEqual(ref["timestamp_precision"], "DATE")
        self.assertEqual(ref["verification_status"], "HISTORICAL_REFERENCE_ONLY")
        self.assertFalse(ref["synchronous_with_option_chain"])
        with tempfile.TemporaryDirectory() as temp:
            paths = build_dashboard(data, validation, Path(temp) / "dash", render_png=False)
            html = Path(paths["html"]).read_text(encoding="utf-8")
            price_data = json.loads(Path(paths["price_data_contract_json"]).read_text(encoding="utf-8"))
            audit = json.loads(Path(paths["price_source_audit_json"]).read_text(encoding="utf-8"))
        self.assertIn("NVDA 과거 참고가격", html)
        self.assertIn("Number(priceReference.price).toFixed(2)", html)
        self.assertIn("synchronous_with_option_chain", json.dumps(price_data))
        self.assertFalse(audit["is_current_price"])
        self.assertFalse(audit["is_regular_close_verified"])
        self.assertEqual(audit["option_data_time_synchronization"], "NOT_ESTABLISHED")

    def test_price_contract_negative_cases_and_missing_source_fallback(self):
        self.assertIsNone(_validate_price_reference(None)["price"])
        self.assertEqual(_validate_price_reference(None)["verification_status"], "SPOT_PRICE_SOURCE_UNAVAILABLE")
        base = {"symbol":"NVDA", "price":123.45, "currency":"USD", "price_type":"HISTORICAL_REFERENCE",
                "price_timestamp":"2026-11-16", "captured_timestamp":"TEST_ONLY:2026-11-17T00:00:00-05:00",
                "source":"TEST_ONLY fixture", "verification_status":"HISTORICAL_REFERENCE_ONLY"}
        for bad in (None, "bad", 0, -1):
            with self.subTest(price=bad), self.assertRaises(ValueError):
                _validate_price_reference({**base, "price":bad})
        for missing in ("price_timestamp", "captured_timestamp", "source"):
            fixture = {**base, missing:None}
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                _validate_price_reference(fixture)
        with self.assertRaisesRegex(ValueError, "HISTORICAL_PRICE_CANNOT_BE_MARKED_CURRENT"):
            _validate_price_reference({**base, "verification_status":"VERIFIED_PRICE_REFERENCE_AVAILABLE"})
        with self.assertRaisesRegex(ValueError, "PRICE_TYPE_UNVERIFIED"):
            _validate_price_reference({**base, "price_type":"UNKNOWN", "verification_status":"HISTORICAL_REFERENCE_ONLY"})

    def test_price_line_shares_strike_axis_and_is_range_conditional(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("priceReference.price>=range.min&&priceReference.price<=range.max", html)
        self.assertIn("const x=xval(priceReference.price)", html)
        self.assertEqual(html.count("price-reference-line"), 2)
        self.assertIn("황금 점선은 과거 참고가격이며 옵션 데이터와 시점이 동기화되지 않았습니다.", html)
        self.assertIn("과거 참고가격이 현재 차트 행사가 범위 밖입니다.", html)
        self.assertNotIn("현재가 기준으로 가장 가까운 행사가", html)

    def test_real_source_and_reference_numerical_contract(self):
        if not NVDA_DIR.exists() or not T_OUT.exists():
            self.skipTest("Preserved WORK 04-R/T evidence unavailable outside this workspace")
        data, validation = _load_real()
        self.assertTrue(validation["all_checks_pass"])
        self.assertEqual(data["contracts_count"], 2188)
        self.assertEqual(data["strike_count"], 444)
        self.assertEqual(data["totals"]["call_volume_observed_sum"], 1457430)
        self.assertEqual(data["totals"]["put_volume_observed_sum"], 953110)
        self.assertEqual(data["totals"]["call_oi_observed_sum"], 9839124)
        self.assertEqual(data["totals"]["put_oi_observed_sum"], 8636754)
        self.assertEqual(data["run_id"], "naviopt04r-20261117T051903Z-80a05c75")

    def test_top5_matches_work04t_reference(self):
        data, validation = _load_real()
        self.assertTrue(all(validation["top5_match_work04t_reference"].values()))
        self.assertEqual(data["top5"]["call_volume"][0]["strike"], 170)
        self.assertEqual(data["top5"]["put_volume"][0]["strike"], 150)
        self.assertEqual(data["top5"]["call_oi"][0]["strike"], 200)
        self.assertEqual(data["top5"]["put_oi"][0]["strike"], 150)

    def test_volume_and_oi_donut_ratios_are_separate_and_sum_to_100(self):
        data, _ = _load_real()
        self.assertAlmostEqual(data["donuts"]["volume"]["call_pct"] + data["donuts"]["volume"]["put_pct"], 100)
        self.assertAlmostEqual(data["donuts"]["oi"]["call_pct"] + data["donuts"]["oi"]["put_pct"], 100)
        self.assertNotEqual(data["donuts"]["volume"]["call_pct"], data["donuts"]["oi"]["call_pct"])
        self.assertAlmostEqual(data["observed_volume_pcr"], 953110 / 1457430)
        self.assertAlmostEqual(data["oi_ratio"], 8636754 / 9839124)

    def test_missing_is_not_imputed_to_zero(self):
        result = aggregate_strikes([
            {"symbol": "NVDA", "strike": "100", "c_volume": "--", "p_volume": "0", "c_openinterest": "", "p_openinterest": "2"},
        ])
        row = result["rows"][0]
        self.assertIsNone(row["call_volume_observed_sum"])
        self.assertEqual(row["call_volume_observed_count"], 0)
        self.assertEqual(row["put_volume_observed_sum"], 0)
        self.assertEqual(row["put_volume_observed_count"], 1)

    def test_full_data_retained_separately_from_initial_display_range(self):
        data, _ = _load_real()
        self.assertEqual(len(data["rows"]), 444)
        self.assertGreater(data["full_range"]["max"], data["default_range"]["max"])
        self.assertLess(data["default_range"]["max"] - data["default_range"]["min"], data["full_range"]["max"] - data["full_range"]["min"])

    def test_standalone_html_and_validation_files_are_created_and_not_overwritten(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "dashboard"
            paths = build_dashboard(data, validation, out, render_png=False)
            html = Path(paths["html"]).read_text(encoding="utf-8")
            embedded = html.split('<script id="dashboard-data" type="application/json">', 1)[1].split("</script>", 1)[0]
            loaded = json.loads(embedded)
            self.assertEqual(len(loaded["rows"]), 444)
            self.assertIn("wheel", html)
            self.assertIn("pointerdown", html)
            self.assertNotIn("https://", html)
            self.assertNotIn("Gamma Exposure", html.split("<script id=\"dashboard-data\"", 1)[0])
            self.assertTrue(Path(paths["data_json"]).is_file())
            self.assertTrue(Path(paths["validation_json"]).is_file())
            with self.assertRaises(FileExistsError):
                build_dashboard(data, validation, out, render_png=False)

    def test_png_preview_is_rendered_from_the_validated_dataset(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            paths = build_dashboard(data, validation, Path(temp) / "dashboard", render_png=True)
            png = Path(paths["png"])
            self.assertTrue(png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertFalse(paths["browser_rendered"])
            self.assertTrue(paths["png_rendered_from_verified_data"])
            saved_validation = json.loads(Path(paths["validation_json"]).read_text(encoding="utf-8"))
            self.assertEqual(saved_validation["html_browser_render"], "UNVERIFIED")
            self.assertEqual(saved_validation["dashboard_png_render"], "same_verified_data_matplotlib")


    def test_mobile_focused_range_is_separate_and_full_rows_remain(self):
        data, validation = _load_real()
        self.assertEqual(data["mobile_initial_range"], {"min": 140, "max": 220})
        self.assertEqual(len(data["rows"]), 444)
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("if(active==='all'&&isMobile)return {...D.mobile_initial_range}", html)
        self.assertIn("range={...initialRange}", html)
        self.assertIn("range={...full}", html)
        self.assertIn("draw('volume-chart','call_volume_observed_sum','put_volume_observed_sum','volume-tooltip')", html)
        self.assertIn("draw('oi-chart','call_oi_observed_sum','put_oi_observed_sum','oi-tooltip')", html)
        self.assertIn("id=\"oi-range-note\"", html)
        self.assertIn("공유 표시 경계 약 '+compact(range.min)+'–'+compact(range.max)", html)
        self.assertIn("$('reset-range').onclick=()=>{viewMode='focused';range={...initialRange};renderViewport()}", html)
        self.assertIn("$('full-range').onclick=()=>{viewMode='full-overview';range={...full};renderViewport()}", html)

    def test_raw_expiration_count_and_totalrecord_contract(self):
        data, validation = _load_real()
        self.assertEqual(validation["raw_total_record"], 2212)
        self.assertEqual(validation["raw_row_count"], 2212)
        self.assertEqual(validation["raw_expiry_header_count"], 24)
        self.assertEqual(data["expiry_count"], 24)
        self.assertEqual(data["contracts_count"], 2188)
        self.assertTrue(all(validation["expiration_sums_match"].values()))

    def test_expiration_groups_reconcile_to_all_expirations(self):
        data, validation = _load_real()
        self.assertEqual(len(data["expiration_audit"]), 24)
        self.assertEqual(sum(x["contracts"] for x in data["expiration_audit"]), 2188)
        for field in ("call_volume_observed_sum", "put_volume_observed_sum", "call_oi_observed_sum", "put_oi_observed_sum"):
            key = field.replace("_observed_sum", "")
            self.assertEqual(sum(x["observed_sums"][key] for x in data["expiration_audit"]), data["totals"][field])
        first = data["expirations"][0]
        subset = [x for x in data["contracts"] if x["expiration"] == first]
        self.assertTrue(subset)
        self.assertEqual({x["expiration"] for x in subset}, {first})

    def test_chain_field_audit_preserves_missing_and_bid_ask_semantics(self):
        data, _ = _load_real()
        audit = data["field_audit"]
        self.assertEqual(audit["c_Volume"]["valid_numeric_count"], 1610)
        self.assertEqual(audit["c_Volume"]["counts"]["DASH_PLACEHOLDER"], 578)
        self.assertEqual(audit["p_Volume"]["valid_numeric_count"], 1293)
        self.assertEqual(audit["c_Openinterest"]["valid_numeric_count"], 2049)
        self.assertGreater(audit["c_Bid"]["valid_numeric_count"], 0)
        self.assertGreater(audit["p_Ask"]["valid_numeric_count"], 0)
        self.assertEqual(audit["c_ImpliedVolatility"]["counts"]["FIELD_ABSENT"], 2188)
        self.assertFalse(audit["c_ImpliedVolatility"]["usable"])

    def test_expiration_selector_updates_every_derived_panel_and_chain(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        for element_id in ("expiration-filter", "kpis", "donut-volume", "donut-oi", "pcr", "oi-ratio", "coverage", "rank-grid", "key-grid", "facts", "selected-values", "chain-body"):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("for(const exp of D.expirations)", html)
        self.assertIn("selectEl.addEventListener('change',switchExpiration)", html)
        self.assertIn("active=selectEl.value;S=stateFor(active)", html)
        self.assertIn("const contracts=D.contracts.filter(c=>exp==='all'||c.expiration===exp)", html)
        self.assertIn("b[k]-a[k]||a.strike-b.strike", html)
        self.assertIn("body.querySelectorAll('tr[data-strike]')", html)

    def test_mobile_chain_table_is_scrollable_and_uses_only_observed_bid_ask(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("class=\"chain-scroll\"", html)
        self.assertIn("overflow:auto", html)
        self.assertIn("Bid", html)
        self.assertIn("Ask", html)
        self.assertNotIn("Call IV", html)
        self.assertIn("관측되지 않음", html)
        self.assertIn("숫자 0과 다릅니다", html)

    def test_expiration_and_field_audit_outputs_are_saved_and_reopenable(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            paths = build_dashboard(data, validation, Path(temp) / "dash", render_png=False)
            expiration = json.loads(Path(paths["expiration_validation_json"]).read_text(encoding="utf-8"))
            fields = json.loads(Path(paths["field_audit_json"]).read_text(encoding="utf-8"))
        self.assertEqual(expiration["expiration_count"], 24)
        self.assertTrue(expiration["passed"])
        self.assertEqual(expiration["sum_reconciliation"], {k: True for k in expiration["sum_reconciliation"]})
        self.assertEqual(fields["fields"]["c_Volume"]["counts"]["DASH_PLACEHOLDER"], 578)
        self.assertEqual(fields["fields"]["c_ImpliedVolatility"]["counts"]["FIELD_ABSENT"], 2188)

    def test_y_axis_uses_numeric_ticks_without_rotated_title_overlap(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("class:'tick'", html)
        self.assertIn("lab.textContent=fmt(max*i/2)", html)
        self.assertNotIn("ylabel.textContent", html)
        self.assertNotIn("transform:`rotate(-90", html)

    def test_mobile_tick_density_and_responsive_chart_geometry(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("const W=isMobile?560:1000", html)
        self.assertIn("VM.ticks(range,plotW,isMobile?74:86)", html)
        self.assertIn("svg.setAttribute('viewBox'", html)
        self.assertIn(".tick{font-size:13px}", html)

    def test_mobile_tap_selects_nearest_real_strike_and_drag_remains_pan(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("const dx=e.clientX-gesture.startX,dy=e.clientY-gesture.startY", html)
        self.assertIn("nearest=nearestActualStrike(target)", html)
        self.assertIn("if(nearest!=null)select(nearest)", html)
        self.assertIn("gesture.mode==='pan'", html)
        self.assertEqual(data["selected_strike"], 170)

    def test_mobile_controls_have_touch_sized_targets_and_initial_range_button(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn(".chart-toolbar button{min-height:40px", html)
        self.assertIn(".range-buttons button{min-height:42px", html)
        self.assertIn("id=\"reset-range\"", html)
        self.assertIn("id=\"full-range\"", html)
        self.assertIn("id=\"center-selected\"", html)


    def test_korean_ui_prevents_browser_translation_and_uses_financial_terms(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn('<html lang="ko" translate="no">', html)
        self.assertIn('<meta name="google" content="notranslate">', html)
        for phrase in ("콜 거래량", "풋 거래량", "미결제약정(OI)", "행사가", "관측률", "기본 보기", "전체 행사가"):
            self.assertIn(phrase, html)
        for broken in ("통화량", "볼륨을 높이세요", "미결제 약정을 설정하세요", "풋옵션 넣기", "풋블리 커버리지", "관찰된 부피"):
            self.assertNotIn(broken, html)
        self.assertIn("PROVISIONAL", html)
        self.assertIn("EOD_UNVERIFIED", html)

    def test_chain_is_grouped_call_strike_put_and_mobile_quotes_expand_per_contract(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("grid-template-columns:4fr 1fr 4fr", html)
        self.assertIn("콜 데이터", html)
        self.assertIn('행사가</th><th colspan="4">풋', html)
        self.assertIn(".chain-table .quote-col{display:none}", html)
        self.assertIn("quote-detail-grid", html)
        self.assertIn("quoteFmt(c.call_bid)", html)
        self.assertIn("콜 Bid (매수호가)", html)
        self.assertIn("expandedKey===key", html)
        self.assertIn("select(Number(tr.dataset.strike))", html)
        self.assertIn("classList.toggle('selected'", html)
        self.assertNotIn("IV</th>", html)

    def test_snapshot_metadata_is_collapsed_but_keeps_id_timestamp_and_hash_accessible(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn('<details class="panel snapshot-details">', html)
        self.assertIn("['실행 ID',D.run_id],['원본 SHA-256',D.raw_sha256]", html)
        self.assertIn("수집 시각(UTC)", html)
        self.assertIn("수집 시각(ET)", html)
        self.assertIn("range={...initialRange}", html)
        self.assertIn("range={...full}", html)

    def test_coverage_formula_is_independent_per_raw_field_and_shows_numerator_denominator(self):
        data, validation = _load_real()
        rows = [row for row in data["contracts"] if row["expiration"] == "2026-11-18"]
        self.assertEqual(len(rows), 90)
        expected = {"call_volume": 85, "put_volume": 73, "call_oi": 85, "put_oi": 73}
        observed_sets = {}
        for metric, count in expected.items():
            observed_sets[metric] = {row["strike"] for row in rows if row[metric] is not None}
            self.assertEqual(len(observed_sets[metric]), count)
            self.assertAlmostEqual(count / len(rows) * 100, 94.44 if count == 85 else 81.11, places=2)
        # Equal percentages come from equal counts, not a shared paired-strike mask.
        self.assertNotEqual(observed_sets["call_volume"], observed_sets["call_oi"])
        self.assertNotEqual(observed_sets["put_volume"], observed_sets["put_oi"])
        self.assertEqual(data["raw_sha256"], "85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce")
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("fmt(S.totals[x[1]+'_observed_count'])+' / '+fmt(S.contracts.length)", html)
        self.assertIn("totals[m+'_observed_count']/contracts.length*100", html)

    def test_chain_quick_navigation_uses_verified_historical_reference_and_real_rows(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        for label in ("참고가격 부근", "선택 행사가", "처음으로"):
            self.assertIn(label, html)
        self.assertIn("chain-reference-nav').disabled=!refOk", html)
        self.assertIn("chain-selected-nav').disabled=selected==null||!S.contracts.some(c=>c.strike===selected)", html)
        self.assertIn("검증된 과거 참고가격이 없어 참고가격 이동을 사용할 수 없습니다.", html)
        self.assertIn("priceReference.verification_status==='HISTORICAL_REFERENCE_ONLY'", html)
        self.assertIn("strikes.reduce((a,b)=>Math.abs(b-priceReference.price)", html)
        self.assertIn("scrollChainToStrike(nearest)", html)
        self.assertIn("scrollChainToStrike(selected)", html)
        self.assertIn("scrollChainToStrike(first.strike)", html)
        self.assertIn("box.scrollTo({top:Math.max(0,top),behavior:'smooth'})", html)
        self.assertIn("과거 참고가격 $156.14", html)
        self.assertNotIn("현재가 기준으로 가장 가까운 행사가", html)

    def test_selected_strike_chain_sync_and_expiration_filter_are_preserved(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("document.querySelectorAll('#chain-body tr[data-strike]')", html)
        self.assertIn("classList.toggle('selected',Number(tr.dataset.strike)===selected)", html)
        self.assertIn("select(Number(tr.dataset.strike))", html)
        self.assertIn("active=selectEl.value;S=stateFor(active)", html)
        self.assertIn("const found=S.rows.some(r=>r.strike===selected)", html)
        self.assertIn("if(!found)selected=S.rows.length?S.rows.reduce", html)
        self.assertIn("id=\"center-selected\">선택 행사가로 이동", html)
        self.assertIn("선택 행사가로 이동", html)

    def test_top5_numbers_keep_thousands_separators_and_all_limitations(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("new Intl.NumberFormat('en-US'", html)
        for status in ("EOD_UNVERIFIED", "MISSINGNESS_CAUSE_UNKNOWN", "FULL_VOLUME_COMPLETENESS_UNVERIFIED"):
            self.assertIn(status, html)
        self.assertIn(".rankline b{white-space:nowrap}", html)
        self.assertIn(".chain-scroll{overscroll-behavior:contain", html)

    def test_viewport_contract_caps_ordinary_zoom_and_separates_full_overview(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("const zoomBounds=(center=", html)
        self.assertIn("Math.min(focus*4,320)", html)
        self.assertIn("min=\"1\" max=\"8\" step=\"0.1\"", html)
        self.assertIn("viewMode='full-overview'", html)
        self.assertIn("VM.overview(actual,full)", html)
        self.assertIn("$('zoom').disabled=viewMode==='full-overview'", html)
        self.assertIn("전체 범위 $", html)
        self.assertIn("(full.max-full.min)/72", html)
        self.assertNotIn("$('zoom').max=String(Math.min(32", html)

    def test_actual_javascript_viewport_math_zoom_pan_clamps_and_repeats(self):
        result = _run_viewport_js("(()=>{const d={min:1,max:2500},b={minSpan:VM.minimumUsefulSpan([{strike:178},{strike:180},{strike:182},{strike:184},{strike:186}],180),maxSpan:320};let r=VM.fit(180,80,d);const initial={...r};for(let i=0;i<100;i++){r=VM.fit((r.min+r.max)/2,VM.zoomSpan(i%2?1:8,b),d);if(!Number.isFinite(r.min)||!Number.isFinite(r.max)||r.min<=0||r.max<=r.min)throw Error('invalid zoom')}const inSpan=r.max-r.min;let left=VM.shift({min:1,max:321},-5000,d),right=VM.shift({min:2180,max:2500},5000,d);let pan={...initial};for(let i=0;i<100;i++){pan=VM.shift(pan,i%2?18:-18,d)}return {default:initial,zoomLow:VM.zoomSpan(1,b),zoomHigh:VM.zoomSpan(8,b),minUsefulSpan:b.minSpan,inSpan,left,right,pan,level:VM.zoomLevel(80,b)}})()")
        self.assertEqual(result["default"], {"min": 140, "max": 220})
        self.assertEqual(result["zoomLow"], 320)
        self.assertAlmostEqual(result["zoomHigh"], result["minUsefulSpan"])
        self.assertLessEqual(result["inSpan"], 320)
        self.assertEqual(result["left"]["min"], 1)
        self.assertEqual(result["right"]["max"], 2500)
        self.assertTrue(1 <= result["pan"]["min"] < result["pan"]["max"] <= 2500)
        self.assertTrue(1 < result["level"] < 8)

    def test_actual_javascript_full_range_bins_reconcile_real_nvda_observations(self):
        data, validation = _load_real()
        payload = json.dumps({"rows": data["rows"], "domain": data["full_range"]}, separators=(",", ":"))
        expr = "(()=>{const input=JSON.parse(require('fs').readFileSync(0,'utf8')),rows=input.rows,domain=input.domain,bins=VM.overview(rows,domain),keys=['call_volume_observed_sum','put_volume_observed_sum','call_oi_observed_sum','put_oi_observed_sum'];const total=a=>a.reduce((s,r)=>s+(r==null?0:r),0),step=VM.niceStep((domain.max-domain.min)/72);return {binCount:bins.length,sourceStrikeCount:new Set(rows.map(r=>r.strike)).size,binStrikeCount:new Set(bins.flatMap(b=>b.actual_strikes)).size,nearestAreReal:bins.every(b=>b.actual_strikes.includes(b.nearest_strike)),centersFinite:bins.every(b=>Number.isFinite(b.bin_center)&&b.bin_center>=domain.min&&b.bin_center<=domain.max),binStep:step,totals:Object.fromEntries(keys.map(k=>[k,{source:total(rows.map(r=>r[k])),binned:total(bins.map(r=>r[k]))}]))}})()"
        result = _run_viewport_js(expr, payload)
        self.assertLess(result["binCount"], 444)
        self.assertEqual(result["sourceStrikeCount"], 444)
        self.assertEqual(result["binStrikeCount"], 444)
        self.assertTrue(result["nearestAreReal"])
        self.assertTrue(result["centersFinite"])
        self.assertEqual(result["binStep"], 50)
        for metric, pair in result["totals"].items():
            self.assertEqual(pair["source"], pair["binned"], metric)
        self.assertTrue(validation["all_checks_pass"])

    def test_actual_javascript_ticks_are_adaptive_and_nonuniform_strikes_use_price_axis(self):
        result = _run_viewport_js("(()=>{const r={min:140,max:220},ticks=VM.ticks(r,500,74),x150=VM.x(150,r,58,490),x200=VM.x(200,r,58,490),domain={min:1,max:2500},outer=VM.ticks(domain,500,74),invalid=VM.x(170,{min:10,max:10},0,500);return {ticks,outer,x150,x200,invalid,finite:outer.every(t=>Number.isFinite(t.x)&&Number.isFinite(t.value)),nonduplicate:new Set(outer.map(t=>t.value)).size===outer.length}})()")
        self.assertTrue(result["finite"])
        self.assertTrue(result["nonduplicate"])
        self.assertGreaterEqual(len(result["ticks"]), 2)
        self.assertTrue(all(b["x"] - a["x"] >= 74 for a, b in zip(result["outer"], result["outer"][1:])))
        self.assertAlmostEqual(result["x200"] - result["x150"], 490 * 50 / 80)
        self.assertIsNone(result["invalid"])

    def test_pan_zoom_preserve_selection_and_reference_transform_contract(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("touch-action:pan-y", html)
        self.assertIn("mode:'pending'", html)
        self.assertIn("startSpan:range.max-range.min", html)
        self.assertIn("gesture.mode='vertical'", html)
        self.assertIn("gesture.mode='pan'", html)
        self.assertIn("svg.onpointercancel=e=>clearGesture(e)", html)
        self.assertIn("svg.onlostpointercapture", html)
        self.assertIn("viewMode==='full-overview'", html)
        self.assertIn("const x=xval(priceReference.price)", html)
        self.assertIn("priceReference.price>=range.min&&priceReference.price<=range.max", html)
        self.assertIn("function select(s){if(!S.rows.some(r=>r.strike===s))return;selected=s;renderViewport();renderSelection()}", html)
        self.assertIn("선택 행사가가 현재 차트 범위 밖입니다", html)
        self.assertIn("viewMode='focused';range={...initialRange}", html)
        self.assertEqual(data["selected_strike"], 170)

if __name__ == "__main__":
    unittest.main()


