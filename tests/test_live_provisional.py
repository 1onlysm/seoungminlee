import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from options_collector.live_provisional import SYMBOLS, run_live_batch


def _payload(symbol):
    return json.dumps({
        "status": {"rCode": 200},
        "data": {
            "totalRecord": 2,
            "table": {"rows": [
                {"expirygroup": "November 20, 2026"},
                {
                    "strike": "500", "drillDownURL": f"/option-chain/{symbol}-261120C00050000",
                    "c_Option": f"{symbol}  261120C00500000", "p_Option": "--",
                    "c_Volume": "12", "p_Volume": "7",
                    "c_Openinterest": "20", "p_Openinterest": "0",
                },
            ]},
        },
    }).encode()


class FakeClient:
    def __init__(self, *, failures=None):
        self.failures = failures or {}
        self.calls = []

    def fetch_once(self, symbol):
        self.calls.append(symbol)
        failure = self.failures.get(symbol)
        if failure == "network":
            raise OSError("offline simulated network error")
        if failure == 403:
            return SimpleNamespace(symbol=symbol, http_status=403, api_rcode=None, body=b"denied", error_type="HTTP_ERROR", error_detail=None)
        body = _payload(symbol)
        return SimpleNamespace(symbol=symbol, http_status=200, api_rcode=200, body=body, error_type=None, error_detail=None)


class LiveProvisionalTests(unittest.TestCase):
    def _factory(self, **kwargs):
        self.client = FakeClient(**kwargs)
        return lambda timeout: self.client

    def test_one_fake_call_per_symbol_and_analytics_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_live_batch(Path(temp) / "out", client_factory=self._factory())
            run_dir = Path(result["manifest_path"]).parent
            payload = json.loads(Path(result["analytics"]["json_path"]).read_text())
            with Path(result["analytics"]["csv_path"]).open(encoding="utf-8") as handle:
                csv_text = handle.read()
            summary_exists = (run_dir / "batch_summary.json").is_file()
            raw_count = len(list(run_dir.rglob("raw.json")))
        self.assertEqual(tuple(self.client.calls), SYMBOLS)
        self.assertEqual(result["request_count"], 14)
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["success_count"], 14)
        self.assertEqual(result["analytics_success_count"], 14)
        self.assertEqual(len(payload["symbols"]), 14)
        self.assertIn("PROVISIONAL", csv_text)
        self.assertEqual(payload["symbols"][0]["observed_volume_pcr"], 7 / 12)
        self.assertEqual(payload["symbols"][0]["status"], "PROVISIONAL")
        self.assertEqual(payload["symbols"][0]["limitations"], ["EOD_UNVERIFIED", "MISSINGNESS_CAUSE_UNKNOWN", "FULL_VOLUME_COMPLETENESS_UNVERIFIED"])
        self.assertTrue(summary_exists)
        self.assertEqual(raw_count, 14)

    def test_http_403_is_recorded_and_batch_continues_without_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_live_batch(Path(temp) / "out", client_factory=self._factory(failures={"SPY": 403}))
        self.assertEqual(tuple(self.client.calls), SYMBOLS)
        self.assertEqual(result["request_count"], 14)
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["results"][0]["verdict"], "HTTP_ACCESS_DENIED")
        self.assertEqual(result["analytics_success_count"], 13)

    def test_network_error_is_not_retried_and_other_symbols_continue(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_live_batch(Path(temp) / "out", client_factory=self._factory(failures={"MSTR": "network"}))
        self.assertEqual(tuple(self.client.calls), SYMBOLS)
        self.assertEqual(result["request_count"], 14)
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["results"][8]["verdict"], "NETWORK_ERROR")
        self.assertEqual(result["analytics_success_count"], 13)


if __name__ == "__main__":
    unittest.main()
