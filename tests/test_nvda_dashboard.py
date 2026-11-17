import json
import tempfile
import unittest
from pathlib import Path

from options_collector.nvda_dashboard import build_dashboard, load_verified_data, _validate_price_reference
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


class NvdaDashboardTests(unittest.TestCase):
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
        self.assertIn("공유 행사가 범위 $'+fmt(range.min)+'–$'+fmt(range.max)", html)
        self.assertIn("$('reset-range').onclick=()=>{range={...initialRange};render()}", html)
        self.assertIn("$('full-range').onclick=()=>{range={...full};render()}", html)

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
        self.assertIn("Math.ceil(rows.length/(isMobile?6:13))", html)
        self.assertIn("svg.setAttribute('viewBox'", html)
        self.assertIn(".tick{font-size:13px}", html)

    def test_mobile_tap_selects_nearest_real_strike_and_drag_remains_pan(self):
        data, validation = _load_real()
        with tempfile.TemporaryDirectory() as temp:
            html = Path(build_dashboard(data, validation, Path(temp) / "dash", render_png=False)["html"]).read_text(encoding="utf-8")
        self.assertIn("Math.abs(e.clientX-start.x)<8", html)
        self.assertIn("nearest=rows.reduce", html)
        self.assertIn("if(nearest)select(nearest.strike)", html)
        self.assertIn("if(drag){const dx=", html)
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
        self.assertIn("if(!found&&S.rows.length)selected=S.rows.reduce", html)
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

if __name__ == "__main__":
    unittest.main()

