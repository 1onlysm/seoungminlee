import json
import tempfile
import unittest
from pathlib import Path

from options_collector.nvda_dashboard import build_dashboard, load_verified_data
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


if __name__ == "__main__":
    unittest.main()
