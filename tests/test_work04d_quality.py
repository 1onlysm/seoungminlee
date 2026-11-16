import hashlib, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from options_collector.parser import parse_payload, classify_root
from options_collector.quality import FIELDS, classify_value, inspect_quality
from options_collector.registry import get_symbol
from options_collector.snapshot import write_snapshot
from options_collector.status import Status, require_derived_indicators
from unittest.mock import patch
import tools.real_response_audit as real_audit

FIXTURE = Path(__file__).parent / 'fixtures' / 'synthetic_real_shape.json'
RAW = FIXTURE.read_bytes()
CAPTURE = '2026-11-16T19:29:25.707425+00:00'
class Work04DTests(unittest.TestCase):
    def test_real_nasdaq_schema_fields_and_rows(self):
        parsed = parse_payload(RAW, get_symbol('PLTR'))
        self.assertEqual(parsed.raw_row_count, 3)
        self.assertEqual(parsed.expiry_groups, 1)
        self.assertEqual(len(parsed.rows), 2)
        self.assertEqual(parsed.total_record_scope, 'raw_table_rows')
        self.assertTrue(parsed.schema_ok)
    def test_totalrecord_counts_headers_and_contracts_separately(self):
        q = inspect_quality(parse_payload(RAW, get_symbol('PLTR')), RAW, 200, 200, CAPTURE)
        self.assertEqual(q['totalRecord'], 3)
        self.assertEqual(q['raw_table_row_count'], 3)
        self.assertEqual(q['contract_rows'], 2)
        self.assertTrue(q['totalRecord_matches_expected_scope'])
    def test_contract_strike_and_expiration_normalized(self):
        p = parse_payload(RAW, get_symbol('PLTR'))
        self.assertEqual(p.rows[0]['_strike_value'], 160)
        self.assertEqual(p.rows[0]['_expiration'], '2026-11-20')
    def test_standard_root_extracted_from_real_url_shape(self):
        p = parse_payload(RAW, get_symbol('PLTR'))
        self.assertEqual([r['_root_class'] for r in p.rows], ['STANDARD', 'STANDARD'])
    def test_wrong_ticker_root_is_unknown_not_adjusted(self):
        self.assertEqual(classify_root("ABCD", "SPY"), "UNKNOWN")
        self.assertEqual(classify_root("SPY1", "SPY"), "ADJUSTED")
    def test_seven_missingness_classes(self):
        inputs = [({'x':'5'}, 'OBSERVED_POSITIVE'), ({'x':'0'}, 'EXPLICIT_ZERO'), ({'x':'--'}, 'DASH_PLACEHOLDER'), ({'x':''}, 'EMPTY_STRING'), ({'x':None}, 'JSON_NULL'), ({}, 'FIELD_ABSENT'), ({'x':'odd'}, 'NON_NUMERIC_INVALID')]
        self.assertEqual([classify_value(row,'x')[0] for row,_ in inputs], [want for _,want in inputs])
    def test_raw_tokens_and_zero_are_preserved(self):
        q=inspect_quality(parse_payload(RAW,get_symbol('PLTR')),RAW,200,200,CAPTURE)
        self.assertEqual(q['volume_oi']['c_Volume']['taxonomy_counts']['NON_NUMERIC_INVALID'],1)
        self.assertEqual(q['volume_oi']['p_Volume']['taxonomy_counts']['DASH_PLACEHOLDER'],1)
        self.assertEqual(q['volume_oi']['c_Openinterest']['explicit_zero_count'],1)
        self.assertEqual(q['per_contract_normalized_values'][0]['c_Volume']['raw'],'8')
        self.assertEqual(q['per_contract_normalized_values'][0]['c_Openinterest']['classification'],'EXPLICIT_ZERO')
    def test_call_put_and_expiration_distributions(self):
        q=inspect_quality(parse_payload(RAW,get_symbol('PLTR')),RAW,200,200,CAPTURE)
        self.assertIn('2026-11-20',q['distributions']['expiration'])
        self.assertEqual(q['distributions']['expiration']['2026-11-20']['contract_count'],2)
        self.assertNotEqual(q['volume_oi']['c_Volume']['taxonomy_counts']['DASH_PLACEHOLDER'],q['volume_oi']['p_Volume']['taxonomy_counts']['DASH_PLACEHOLDER'])
        self.assertIn('160',q['distributions']['strike'])
    def test_near_mid_far_buckets_use_capture_date(self):
        q=inspect_quality(parse_payload(RAW,get_symbol('PLTR')),RAW,200,200,CAPTURE)
        self.assertEqual(q['distributions']['horizon']['definition']['as_of_date'],'2026-11-16')
        self.assertEqual(q['distributions']['horizon']['near_term']['contract_count'],2)
        self.assertEqual(q['distributions']['horizon']['mid_term']['contract_count'],0)
    def test_atm_evaluable_only_with_near_timestamped_quote(self):
        q=inspect_quality(parse_payload(RAW,get_symbol('PLTR')),RAW,200,200,CAPTURE)
        self.assertTrue(q['underlying_quote_used_for_atm'])
        self.assertEqual(q['distributions']['atm']['contract_count'],1)
        q2=inspect_quality(parse_payload(RAW,get_symbol('PLTR')),RAW,200,200,'2026-11-16T20:00:00+00:00')
        self.assertFalse(q2['underlying_quote_used_for_atm'])
        self.assertEqual(q2['atm_volume_observation_rate'],'NOT_EVALUABLE')
    def test_atm_missing_price_not_evaluable(self):
        obj=json.loads(RAW); obj['data']['lastTrade']=None
        q=inspect_quality(parse_payload(obj,get_symbol('PLTR')),RAW,200,200,CAPTURE)
        self.assertEqual(q['atm_oi_observation_rate'],'NOT_EVALUABLE')
    def test_missing_raw_file_is_reported_not_synthesized(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(real_audit.EVIDENCE, {'PLTR': Path(d)}, clear=True):
                result=real_audit.discover()['PLTR']
            self.assertEqual(result['evidence_state'],'RAW_EVIDENCE_UNAVAILABLE')
            self.assertFalse(result['exists'])
    def test_snapshot_csv_quality_manifest_and_raw_hash_readback(self):
        p=parse_payload(RAW,get_symbol('PLTR')); q=inspect_quality(p,RAW,200,200,CAPTURE)
        with tempfile.TemporaryDirectory() as d:
            snap=write_snapshot(d,'PLTR','2026-11-16',RAW,p.rows,q,CAPTURE)
            self.assertEqual(hashlib.sha256((snap/'raw.json').read_bytes()).hexdigest(),hashlib.sha256(RAW).hexdigest())
            self.assertEqual(len((snap/'contracts.csv').read_text().splitlines()),3)
            self.assertEqual(json.loads((snap/'manifest.json').read_text())['freshness'],'EOD_UNVERIFIED')
            self.assertEqual(json.loads((snap/'quality.json').read_text())['raw_sha256'],hashlib.sha256(RAW).hexdigest())
    def test_eod_gate_blocks_derived_indicators(self):
        with self.assertRaisesRegex(RuntimeError,'DERIVED_INDICATORS_BLOCKED'):
            require_derived_indicators(Status(api='API_VERIFIED',data='DATA_OBSERVED',freshness='EOD_UNVERIFIED'))
    def test_quality_replay_does_not_open_network(self):
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden')) as opener:
            parse_payload(RAW,get_symbol('PLTR'))
            inspect_quality(parse_payload(RAW,get_symbol('PLTR')),RAW,200,200,CAPTURE)
            self.assertEqual(opener.call_count,0)
if __name__ == '__main__': unittest.main()
