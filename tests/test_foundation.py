import csv, hashlib, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from options_collector.registry import REGISTRY, get_symbol
from options_collector.parser import parse_payload
from options_collector.quality import inspect_quality
from options_collector.status import Status, require_derived_indicators
from options_collector.snapshot import write_snapshot
from options_collector.client import NasdaqClient, HEADERS, BASE

FIXTURE=Path(__file__).parent/'fixtures'/'synthetic_chain.json'
RAW=FIXTURE.read_bytes()
class FakeResponse:
    status=200
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def read(self): return b'{"status":{"rCode":200}}'
class FakeOpener:
    def __init__(self,result): self.result=result; self.calls=0; self.request=None
    def open(self,request,timeout):
        self.calls+=1; self.request=request
        if isinstance(self.result,BaseException): raise self.result
        return self.result
class FoundationTests(unittest.TestCase):
    def test_01_registry_has_fourteen_unique_symbols(self): self.assertEqual(len(REGISTRY),14); self.assertEqual(len(set(REGISTRY)),14)
    def test_02_assetclass_split(self):
        self.assertTrue(all(REGISTRY[s].assetclass=='etf' for s in ['SPY','QQQ','SOXX','IWM','IBIT']))
        self.assertTrue(all(REGISTRY[s].assetclass=='stocks' for s in ['NVDA','AMD','TSLA','MSTR','PLTR','MU','CRWV','COIN','MARA']))
    def test_03_per_symbol_expected_roots(self): self.assertTrue(all(v.expected_root==k for k,v in REGISTRY.items()))
    def test_04_unknown_symbol_rejected(self):
        with self.assertRaises(ValueError): get_symbol('NOPE')
    def test_05_expiry_headings_excluded(self):
        parsed=parse_payload(RAW,get_symbol('SPY')); self.assertEqual(len(parsed.rows),2); self.assertEqual(parsed.expiry_groups,2)
    def test_06_total_record_matches(self): self.assertTrue(parse_payload(RAW,get_symbol('SPY')).schema_ok)
    def test_07_missing_kinds_and_explicit_zero_separate(self):
        q=inspect_quality(parse_payload(RAW,get_symbol('SPY')),RAW,200,200)
        self.assertEqual(q['volume_oi']['c_Volume']['explicit_zero_count'],1)
        self.assertEqual(q['volume_oi']['c_Volume']['missing_types']['empty_string'],1)
        self.assertEqual(q['volume_oi']['c_Openinterest']['missing_types']['dash'],1)
        self.assertEqual(q['volume_oi']['p_Volume']['missing_types']['null'],1)
    def test_08_absent_field_is_not_zero(self):
        p=parse_payload({"data":{"table":{"rows":[{"strikePrice":"100"}],"totalRecord":1}}},get_symbol('SPY'))
        q=inspect_quality(p,b'{}',200,200); self.assertEqual(q['volume_oi']['c_Volume']['missing_types']['field_absent'],1); self.assertEqual(q['volume_oi']['c_Volume']['explicit_zero_count'],0)
    def test_09_adjusted_root_separated(self):
        p=parse_payload({"data":{"table":{"rows":[{"expiryDate":"2026-01-01"},{"strikePrice":"1","c_Option":"SPY1  260101C00001000"}],"totalRecord":1}}},get_symbol('SPY'))
        self.assertEqual(p.rows[0]['_root_class'],'ADJUSTED')
    def test_10_duplicate_contracts_detected(self):
        row={"strikePrice":"100","c_Option":"SPY261218C00100000"}
        p=parse_payload({"data":{"table":{"rows":[{"expiryDate":"2026-12-18"},row,row],"totalRecord":2}}},get_symbol('SPY'))
        self.assertEqual(inspect_quality(p,b'{}',200,200)['duplicate_contract_keys'],1)
    def test_11_sha256_matches_raw(self): self.assertEqual(inspect_quality(parse_payload(RAW,get_symbol('SPY')),RAW,200,200)['raw_sha256'],hashlib.sha256(RAW).hexdigest())
    def test_12_snapshot_csv_json_readback(self):
        with tempfile.TemporaryDirectory() as d:
            p=parse_payload(RAW,get_symbol('SPY')); q=inspect_quality(p,RAW,200,200); dest=write_snapshot(d,'SPY','2026-11-16',RAW,p.rows,q,'2026-11-16T20:00:00+00:00')
            self.assertTrue((dest/'raw.json').is_file()); self.assertEqual(json.loads((dest/'manifest.json').read_text())['raw_sha256'],hashlib.sha256(RAW).hexdigest())
            with (dest/'contracts.csv').open() as f: self.assertEqual(len(list(csv.DictReader(f))),2)
    def test_13_identical_response_deduplicated(self):
        with tempfile.TemporaryDirectory() as d:
            p=parse_payload(RAW,get_symbol('SPY')); q=inspect_quality(p,RAW,200,200)
            a=write_snapshot(d,'SPY','2026-11-16',RAW,p.rows,q,'2026-11-16T20:00:00+00:00'); b=write_snapshot(d,'SPY','2026-11-16',RAW,p.rows,q,'2026-11-16T20:01:00+00:00'); self.assertEqual(a,b)
    def test_14_different_response_versions_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            p=parse_payload(RAW,get_symbol('SPY')); q=inspect_quality(p,RAW,200,200)
            a=write_snapshot(d,'SPY','2026-11-16',RAW,p.rows,q,'2026-11-16T20:00:00+00:00'); raw2=RAW+b' '; b=write_snapshot(d,'SPY','2026-11-16',raw2,p.rows,q,'2026-11-16T20:01:00+00:00'); self.assertNotEqual(a,b); self.assertTrue(a.exists())
    def test_15_write_failure_does_not_destroy_prior_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            p=parse_payload(RAW,get_symbol('SPY')); q=inspect_quality(p,RAW,200,200); a=write_snapshot(d,'SPY','2026-11-16',RAW,p.rows,q,'2026-11-16T20:00:00+00:00')
            with patch('options_collector.snapshot._atomic_text',side_effect=OSError('disk')):
                with self.assertRaises(OSError): write_snapshot(d,'SPY','2026-11-16',b'other',p.rows,q,'2026-11-16T20:01:00+00:00')
            self.assertEqual((a/'raw.json').read_bytes(),RAW)
    def test_16_http_403_classified_without_retry(self): self._client_error(HTTPError('https://api.nasdaq.com',403,'Forbidden',{},None),403,'HTTP_ERROR')
    def test_17_http_429_classified_without_retry(self): self._client_error(HTTPError('https://api.nasdaq.com',429,'Too Many',{},None),429,'HTTP_ERROR')
    def test_18_dns_error_classified_without_retry(self): self._client_error(URLError(OSError(-3,'Temporary failure in name resolution')),None,'OSError')
    def test_19_timeout_classified_without_retry(self): self._client_error(TimeoutError('timed out'),None,'TimeoutError')
    def test_20_api_rcode_error_separate(self):
        opener=FakeOpener(FakeResponse())
        class R(FakeResponse):
            def read(self): return b'{"status":{"rCode":500}}'
        opener.result=R(); c=NasdaqClient(); c.opener=opener; r=c.fetch_once('SPY'); self.assertEqual(r.http_status,200); self.assertEqual(r.api_rcode,500); self.assertEqual(opener.calls,1)
    def test_21_invalid_json_rejected(self):
        with self.assertRaisesRegex(ValueError,'INVALID_JSON'): parse_payload(b'{bad',get_symbol('SPY'))
    def test_22_empty_rows_schema_flagged(self):
        p=parse_payload({"data":{"table":{"rows":[],"totalRecord":0}}},get_symbol('SPY')); self.assertIn('EMPTY_CHAIN',p.issues)
    def test_23_eod_gate_blocks_indicators(self):
        with self.assertRaisesRegex(RuntimeError,'DERIVED_INDICATORS_BLOCKED'): require_derived_indicators(Status(api='API_VERIFIED',data='DATA_OBSERVED',freshness='EOD_UNVERIFIED'))
    def test_24_client_contract_no_redirect_and_headers(self):
        opener=FakeOpener(FakeResponse()); c=NasdaqClient(); c.opener=opener; r=c.fetch_once('IWM')
        self.assertEqual(opener.calls,1); self.assertIn('assetclass=etf',opener.request.full_url); self.assertEqual(opener.request.get_header('Accept'),'application/json'); self.assertEqual(r.http_status,200)
    def _client_error(self,error,status,kind):
        opener=FakeOpener(error); c=NasdaqClient(); c.opener=opener; r=c.fetch_once('SPY'); self.assertEqual(r.http_status,status); self.assertEqual(r.error_type,kind); self.assertEqual(opener.calls,1)
if __name__=='__main__': unittest.main()
