import hashlib, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from options_collector.client import FetchResult
from options_collector.single_run import LIVE_MAX_REQUESTS, SafetyGateError, run_single

FIXTURE = Path(__file__).parent / 'fixtures' / 'synthetic_real_shape.json'
RAW = FIXTURE.read_bytes()
MSTR_RAW = RAW.replace(b'pltr', b'mstr').replace(b'PLTR', b'MSTR')
class FakeClient:
    def __init__(self, result, **kwargs): self.result=result; self.calls=0
    def fetch_once(self, symbol): self.calls+=1; self.symbol=symbol; return self.result

def result(status=200, rcode=200, body=MSTR_RAW, error=None):
    return FetchResult('MSTR',status,rcode,body,error,None)

class SingleRunTests(unittest.TestCase):
    def test_01_offline_e2e_never_constructs_network_client(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'mstr.json'; source.write_bytes(MSTR_RAW)
            with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden')) as opener:
                out=run_single(input_path=source,output_root=d,client_factory=lambda **k: (_ for _ in ()).throw(AssertionError('client constructed')))
                self.assertEqual(out['result'],'OFFLINE_E2E_PASSED'); self.assertEqual(out['request_count'],0); self.assertEqual(opener.call_count,0)
    def test_02_offline_sha_and_snapshot_readback(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'mstr.json'; source.write_bytes(MSTR_RAW); out=run_single(input_path=source,output_root=d)
            snap=Path(out['snapshot_path']); self.assertEqual(hashlib.sha256((snap/'raw.json').read_bytes()).hexdigest(),hashlib.sha256(MSTR_RAW).hexdigest())
            self.assertTrue(json.loads((snap/'quality.json').read_text())['snapshot_integrity']['snapshot_readback_verified'])
    def test_03_offline_manifest_records_zero_requests(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'mstr.json'; source.write_bytes(MSTR_RAW); out=run_single(input_path=source,output_root=d)
            events=[json.loads(x) for x in (Path(out['run_dir'])/'execution_manifest.jsonl').read_text().splitlines()]
            self.assertEqual(events[0]['mode'],'offline'); self.assertEqual(events[-1]['event'],'RUN_FINALIZED'); self.assertEqual(out['request_count'],0)
    def test_04_live_mode_is_blocked_without_explicit_confirmation(self):
        calls=[]
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(SafetyGateError,'LIVE_CONFIRMATION_REQUIRED'):
                run_single(mode='live',output_root=d,client_factory=lambda **k:calls.append(k))
        self.assertEqual(calls,[])
    def test_05_only_mstr_is_enabled(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(SafetyGateError,'SINGLE_SYMBOL_GATE'):
                run_single(mode='offline',symbol='SPY',input_path=FIXTURE,output_root=d)
    def test_06_invalid_mode_is_blocked(self):
        with self.assertRaisesRegex(SafetyGateError,'MODE_GATE'): run_single(mode='anything')
    def test_07_offline_requires_input(self):
        with self.assertRaisesRegex(SafetyGateError,'OFFLINE_INPUT_REQUIRED'): run_single()
    def test_08_offline_missing_input_recorded_without_request(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(FileNotFoundError,'OFFLINE_INPUT_NOT_FOUND'):
                run_single(input_path=Path(d)/'missing.json',output_root=d)
    def test_09_live_dispatch_is_one_fake_call_only(self):
        fake=FakeClient(result()); config={}
        def factory(**kwargs): config.update(kwargs); return fake
        with tempfile.TemporaryDirectory() as d:
            out=run_single(mode='live',confirm_live=True,output_root=d,client_factory=factory)
        self.assertEqual(config.get('timeout'),30); self.assertEqual(LIVE_MAX_REQUESTS,1)
        self.assertEqual(fake.calls,1); self.assertEqual(fake.symbol,'MSTR'); self.assertEqual(out['request_count'],1); self.assertEqual(out['retry_count'],0)
    def test_10_live_manifest_intent_precedes_dispatch(self):
        fake=FakeClient(result())
        with tempfile.TemporaryDirectory() as d:
            out=run_single(mode='live',confirm_live=True,output_root=d,client_factory=lambda **k:fake)
            events=[json.loads(x) for x in (Path(out['run_dir'])/'execution_manifest.jsonl').read_text().splitlines()]
            names=[x['event'] for x in events]; self.assertLess(names.index('REQUEST_INTENT_RECORDED'),names.index('REQUEST_DISPATCHED'))
            self.assertIn('not proof',events[names.index('REQUEST_DISPATCHED')]['definition'])
    def test_11_http_403_stops_and_preserves_body(self): self._blocked_status(403)
    def test_12_http_429_stops_and_preserves_body(self): self._blocked_status(429)
    def test_13_dns_error_stops_without_retry(self): self._transport_error('gaierror')
    def test_14_timeout_stops_without_retry(self): self._transport_error('TimeoutError')
    def test_15_api_rcode_error_is_not_success(self):
        fake=FakeClient(result(status=200,rcode=500,body=b'{"status":{"rCode":500}}'))
        with tempfile.TemporaryDirectory() as d: out=run_single(mode='live',confirm_live=True,output_root=d,client_factory=lambda **k:fake)
        self.assertEqual(out['result'],'API_RESPONSE_INVALID'); self.assertEqual(out['http_status'],200); self.assertEqual(out['api_rcode'],500); self.assertEqual(fake.calls,1)
    def test_16_live_body_hash_and_bytes_recorded(self):
        fake=FakeClient(result())
        with tempfile.TemporaryDirectory() as d: out=run_single(mode='live',confirm_live=True,output_root=d,client_factory=lambda **k:fake)
        self.assertEqual(out['sha256'],hashlib.sha256(MSTR_RAW).hexdigest()); self.assertEqual(out['raw_bytes'],len(MSTR_RAW))
    def test_17_eod_remains_unverified(self):
        fake=FakeClient(result())
        with tempfile.TemporaryDirectory() as d:
            out=run_single(mode='live',confirm_live=True,output_root=d,client_factory=lambda **k:fake)
            self.assertEqual(out['eod_state'],'EOD_UNVERIFIED'); self.assertEqual(json.loads((Path(out['snapshot_path'])/'quality.json').read_text())['eod_freshness'],'EOD_UNVERIFIED')
    def test_18_partial_snapshot_failure_is_logged_and_not_retried(self):
        fake=FakeClient(result())
        with tempfile.TemporaryDirectory() as d:
            with patch('options_collector.single_run._verify_snapshot',side_effect=OSError('readback failed')):
                with self.assertRaisesRegex(OSError,'readback failed'):
                    run_single(mode='live',confirm_live=True,output_root=d,client_factory=lambda **k:fake)
            self.assertEqual(fake.calls,1)
            runs=list(Path(d).glob('naviopt04e-*')); events=[json.loads(x) for x in (runs[0]/'execution_manifest.jsonl').read_text().splitlines()]
            self.assertIn('RUN_ERROR',[x['event'] for x in events]); self.assertEqual(events[-1]['request_count'],1)
    def test_19_workflow_is_offline_by_default_and_has_no_schedule(self):
        workflow=(Path(__file__).parents[1]/'.github/workflows/options-mstr-single-probe.yml').read_text()
        self.assertIn('default: offline',workflow); self.assertNotIn('schedule:',workflow); self.assertIn('confirm_live_probe',workflow)
    def test_20_eod_indicator_gate_still_blocks_derived_metrics(self):
        from options_collector.status import Status, require_derived_indicators
        with self.assertRaisesRegex(RuntimeError,'DERIVED_INDICATORS_BLOCKED'):
            require_derived_indicators(Status(api='API_VERIFIED',data='QUALITY_LIMITED',freshness='EOD_UNVERIFIED'))
    def _blocked_status(self,status):
        fake=FakeClient(result(status=status,rcode=None,body=b'blocked'))
        with tempfile.TemporaryDirectory() as d:
            out=run_single(mode='live',confirm_live=True,output_root=d,client_factory=lambda **k:fake)
            self.assertEqual(out['result'],'HTTP_ACCESS_DENIED'); self.assertEqual(out['request_count'],1); self.assertEqual(fake.calls,1)
            self.assertEqual((Path(out['run_dir'])/'raw-response.bin').read_bytes(),b'blocked')
    def _transport_error(self,kind):
        fake=FakeClient(FetchResult('MSTR',None,None,None,kind,'offline simulation'))
        with tempfile.TemporaryDirectory() as d: out=run_single(mode='live',confirm_live=True,output_root=d,client_factory=lambda **k:fake)
        self.assertEqual(out['result'],'NETWORK_ERROR'); self.assertEqual(out['request_count'],1); self.assertEqual(out['retry_count'],0); self.assertEqual(fake.calls,1)
if __name__=='__main__': unittest.main()
