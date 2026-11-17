import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from options_collector import manual_refresh
from options_collector.live_provisional import run_live_batch


class ManualRefreshTests(unittest.TestCase):
    def test_help_exits_without_live_runner(self):
        with patch.object(manual_refresh, "run_live_batch") as run:
            with self.assertRaises(SystemExit) as caught:
                manual_refresh.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        run.assert_not_called()

    def test_invalid_arguments_exit_without_live_runner(self):
        with patch.object(manual_refresh, "run_live_batch") as run:
            with self.assertRaises(SystemExit) as caught:
                manual_refresh.main(["--invalid"])
        self.assertEqual(caught.exception.code, 2)
        run.assert_not_called()

    def test_missing_live_confirmation_exits_without_live_runner(self):
        with patch.object(manual_refresh, "run_live_batch") as run:
            with self.assertRaises(SystemExit) as caught:
                manual_refresh.main(["--mode", "live", "--output-root", "/tmp/unused"])
        self.assertEqual(caught.exception.code, 2)
        run.assert_not_called()

    def test_manual_completion_prints_paths_and_symbol_outcomes(self):
        summary = {
            "run_id": "sample", "symbols": ["SPY"] * 14, "request_count": 14, "retry_count": 0,
            "success_count": 13, "analytics_success_count": 13,
            "manifest_path": "/tmp/run/execution_manifest.jsonl", "snapshot_root": "/tmp/run/snapshots",
            "analytics": {"json_path": "/tmp/run/analytics.json", "csv_path": "/tmp/run/analytics.csv"},
            "results": [{"symbol": "SPY", "verdict": "LIVE_COLLECTION_SUCCESS", "analytics_status": "PROVISIONAL"},
                        {"symbol": "QQQ", "verdict": "HTTP_ACCESS_DENIED", "analytics_status": "NOT_RUN"}],
        }
        output = io.StringIO()
        with patch.object(manual_refresh, "run_live_batch", return_value=summary) as run:
            with contextlib.redirect_stdout(output):
                code = manual_refresh.main(["--mode", "live", "--confirm-live", "--output-root", "/tmp/out"])
        run.assert_called_once_with("/tmp/out")
        self.assertEqual(code, 1)
        self.assertIn("successful_symbols", output.getvalue())
        self.assertIn("HTTP_ACCESS_DENIED", output.getvalue())
        self.assertIn("analytics_json_path", output.getvalue())

    def test_run_id_collision_fails_before_client_creation(self):
        class NeverClient:
            def __init__(self, **kwargs):
                raise AssertionError("client must not be constructed when run path collides")
        with tempfile.TemporaryDirectory() as temp:
            run_id = "naviopt04r-20261117T000000Z-fixed000"
            (Path(temp) / run_id).mkdir()
            with patch("options_collector.live_provisional._now_utc") as now, patch("options_collector.live_provisional.uuid.uuid4") as uuid:
                from datetime import datetime, timezone
                now.return_value = datetime(2026, 11, 17, tzinfo=timezone.utc)
                uuid.return_value.hex = "fixed000"
                with self.assertRaises(FileExistsError):
                    run_live_batch(temp, client_factory=NeverClient)


if __name__ == "__main__":
    unittest.main()
