# WORK 04-AF — Provisional HV Research Lane

**Primary verdict: `PROVISIONAL_HV_RIGHTS_GATE_BLOCKED`.** The preserved bundle and its embedded 90-row payload were recovered and both declared hashes were independently reproduced. The payload is structurally usable as a candidate, but the exact upstream provider is not bound to the records, the original provider response is absent, and local processing permission is not established. No candidate-derived HV value was calculated or emitted.

## Baseline

- Repository: `1onlysm/seoungminlee`
- Frozen source: `work04ae-nvda-hv-source-authentication`
- Verified source HEAD: `adf1e4c5699388e4787bdcc5223ec4879ab7d4db`
- Target: `work04af-provisional-hv-research-lane`
- Target was created from the frozen source HEAD. The production dashboard, options collector, and verified HV contract were not changed.

## Candidate and gates

The candidate is `NVDA_NAVI-BOOT-NVDA-20260829T074538284767Z_execution_bundle.json`, embedded at `execution_bundle.producer_attendance[5].output.raw_ohlcv_90d`. It contains 90 NVDA-labeled daily OHLCV records from 2026-04-21 through 2026-08-27. Bundle SHA-256 is `11afaf56361858216019ac95027262e858a7d13a006b7489b2ed159ea7d9c96e`; the canonical embedded payload SHA-256 is `735c5e5dbb42b9697930373b5436c53bbfa2db143d8f59aaa6e4f853fc836f65`.

The structure, date ordering, OHLC relationships, positive finite prices, and nonnegative finite volume passed the offline candidate audit. Prior exchange-calendar evidence found 90 consecutive expected sessions, with 2026-05-25, 2026-06-19, and 2026-07-03 treated as market holidays. These checks do not authenticate market origin, price adjustment, or data rights.

The frozen WORK 04-AE trace leaves Yahoo and Naver as possible acquisition routes and does not bind either one to this payload. Its original provider response, selected-provider execution record, adjustment basis, and entitlement evidence are absent. Official terms reviewed for both possible routes restrict automated access absent applicable permission; the audit does not establish an exception or account entitlement. Accordingly, user authorization for this isolated research task is not treated as provider permission. Local processing and redistribution both remain unverified, so the real candidate is not passed to the calculator. Yahoo's terms prohibit automated data collection without express prior permission; NAVER's official service terms likewise restrict automated access absent prior permission. These terms are risk evidence, not proof of which source generated this payload.

Official terms reviewed: [Yahoo Terms of Service](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html), [NAVER disclaimer](https://policy.naver.com/policy/disclaimer.html), and [NAVER English Terms of Service](https://policy.naver.com/rules/service_en.html).

## Research-lane behavior

`options_collector/provisional_hv_research.py` is isolated from the verified engine and dashboard. It can verify an actual bundle and canonical embedded payload digest, applies a separate rights gate, validates expected sessions and OHLC, and labels any allowed result as provisional, historical, not current, not IV, not production, and not publication eligible. Its writer refuses repository paths. The HV formula follows WORK 04-AB: close-to-close log returns, sample standard deviation (`ddof=1`), and `sqrt(252) * 100`, using exactly N returns and N+1 closes.

The candidate calculation was blocked before calculation because `local_research_permission` is not verified and corporate-action treatment is unresolved. HV10/HV20/HV30/HV60 are therefore **not calculated**. The production/VERIFIED dashboard remains unchanged and continues to report the existing unavailable states. No populated research HTML or candidate-derived values were created or committed.

All synthetic numerical examples are isolated in `tests/test_provisional_hv_research.py` and explicitly marked `TEST_ONLY`; they test the math and safeguards only, not NVDA market history.

## Validation and handoff

Run from the repository root:

```bash
python -m unittest tests.test_provisional_hv_research -v
python -m unittest discover -s tests -v
python -m compileall -q options_collector tests
```

The full test suite and compile results are recorded in `audit_reports/work04af_test_report.json`. No production dashboard regeneration was needed because no verified metric became available. Browser rendering and Galaxy verification remain pending; the existing dashboard was not changed.

### Galaxy review checklist

1. Open the existing production NVDA dashboard.
2. Confirm its volatility panel still shows unavailable states, not provisional numbers.
3. Confirm IV, IV Rank, IV Percentile, IV Skew, GEX, and directional predictions remain unavailable.
4. Confirm the existing options charts, expiration selector, chain, and provenance warnings are unchanged.

Do not use this candidate as current volatility or as an implied-volatility substitute. Do not distribute the bundle or candidate-derived results until source-specific terms and rights are established.

## Safety

- LIVE market-data requests: 0
- GitHub Actions runs: 0
- Main changes: 0
- New providers: 0
- APK changes: 0
- Original options snapshot: unchanged; SHA-256 remains `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce`

Next action: obtain source-specific execution/provenance evidence and written or otherwise applicable provider permission covering local processing. Re-run the isolated candidate gate only after those facts are documented; do not alter the production dashboard until verified-data gates independently pass.
