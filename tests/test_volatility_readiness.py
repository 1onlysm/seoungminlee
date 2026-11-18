import csv
import hashlib
import json
import unittest
from pathlib import Path

from options_collector.nvda_dashboard import _field_class, load_verified_data


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = Path("/workspace/scratch/navi-options-work04r-live/naviopt04r-20261117T051903Z-80a05c75")
NVDA_DIR = RUN_ROOT / "snapshots/data/options/2026-11-17/NVDA/2026-11-17T05-19-47.924836Z"
T_OUT = Path("/workspace/scratch/navi-options-work04t-output-v2")
RAW_SHA256 = "85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce"


def load_real_data():
    return load_verified_data(
        NVDA_DIR / "contracts.csv", T_OUT / "nvda_strike_summary.json",
        T_OUT / "nvda_strike_volume.csv", T_OUT / "nvda_strike_oi.csv",
        NVDA_DIR / "manifest.json", NVDA_DIR / "raw.json", RUN_ROOT / "batch_summary.json",
    )


class VolatilityReadinessTests(unittest.TestCase):
    def test_preserved_snapshot_integrity_and_volatility_statuses(self):
        raw_bytes = (NVDA_DIR / "raw.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw_bytes).hexdigest(), RAW_SHA256)
        data, validation = load_real_data()
        self.assertTrue(validation["all_checks_pass"])
        self.assertEqual(data["contracts_count"], 2188)
        self.assertEqual(data["strike_count"], 444)
        self.assertEqual(data["expiry_count"], 24)
        self.assertEqual(data["totals"]["call_volume_observed_sum"], 1457430)
        self.assertEqual(data["totals"]["put_volume_observed_sum"], 953110)
        self.assertEqual(data["totals"]["call_oi_observed_sum"], 9839124)
        self.assertEqual(data["totals"]["put_oi_observed_sum"], 8636754)
        status = data["volatility_status"]
        self.assertEqual(status["iv"], "SOURCE_ABSENT")
        self.assertEqual(status["iv_fields_found"], [])
        self.assertEqual(status["iv_calculation"], "IV_CALCULATION_BLOCKED")
        self.assertEqual(status["iv_rank"], "IV_RANK_UNAVAILABLE")
        self.assertEqual(status["iv_percentile"], "IV_PERCENTILE_UNAVAILABLE")
        self.assertEqual(status["iv_skew"], "UNAVAILABLE_WITHOUT_VERIFIED_PER_CONTRACT_IV")
        self.assertEqual(status["hv_rv"], "UNAVAILABLE_WITHOUT_VERIFIED_UNDERLYING_OHLC_HISTORY")

    def test_raw_contract_rows_have_quotes_and_last_but_no_iv_or_quote_time(self):
        with (NVDA_DIR / "contracts.csv").open(encoding="utf-8", newline="") as handle:
            contracts = list(csv.DictReader(handle))
        raw_rows = [json.loads(row["raw_row_json"]) for row in contracts]
        self.assertEqual(len(raw_rows), 2188)
        keys = {key for row in raw_rows for key in row}
        self.assertTrue({"c_Bid", "c_Ask", "p_Bid", "p_Ask", "c_Last", "p_Last", "strike", "expiryDate"}.issubset(keys))
        self.assertFalse(any("impliedvolatility" in key.lower() or key.lower() in {"iv", "c_iv", "p_iv"} for key in keys))
        self.assertFalse(any("timestamp" in key.lower() or key.lower() in {"quoteTime", "quote_time"} for key in keys))
        self.assertFalse(any(key.lower() in {"underlyingprice", "underlying_price"} for key in keys))

    def test_missing_placeholders_are_not_zero_and_explicit_zero_is_observed(self):
        self.assertEqual(_field_class(None), "JSON_NULL")
        self.assertEqual(_field_class(""), "EMPTY_STRING")
        self.assertEqual(_field_class("--"), "DASH_PLACEHOLDER")
        self.assertEqual(_field_class("0"), "EXPLICIT_ZERO")
        self.assertEqual(_field_class(0), "EXPLICIT_ZERO")
        self.assertEqual(_field_class("12.5"), "OBSERVED_NUMERIC")

    def test_formula_contract_separates_formula_from_data_and_display_readiness(self):
        contract = json.loads((ROOT / "options_collector/volatility_contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["symbol"], "NVDA")
        self.assertFalse(contract["observation_policy"]["missing_is_zero"])
        self.assertTrue(contract["observation_policy"]["explicit_numeric_zero_is_observed"])
        for indicator in ("per_contract_iv", "iv_rank", "iv_percentile", "historical_volatility", "intraday_realized_volatility"):
            self.assertTrue(contract["formulas"][indicator]["formula_specified"])
            self.assertFalse(contract["formulas"][indicator]["production_calculation_allowed"])
        self.assertFalse(contract["formulas"]["iv_skew"]["formula_specified"])
        self.assertFalse(contract["formulas"]["iv_term_structure"]["formula_specified"])
        self.assertIn("EOD_UNVERIFIED", contract["observation_policy"]["limitations"])
        self.assertIn("MISSINGNESS_CAUSE_UNKNOWN", contract["observation_policy"]["limitations"])
        self.assertIn("FULL_VOLUME_COMPLETENESS_UNVERIFIED", contract["observation_policy"]["limitations"])


if __name__ == "__main__":
    unittest.main()
