# WORK 04-AD — NVDA OHLCV evidence recovery

**Primary verdict: `NVDA_OHLCV_PROVENANCE_OR_RIGHTS_BLOCKED`.** A Library execution bundle contains 90 actual NVDA-labeled OHLCV records. The embedded-record digest is reproducible, but the original provider response, provider/endpoint, adjustment and corporate-action contract, exchange-calendar validation, and permission to reuse the separate-project data in OPTIONS LAB are not established. No records were imported and no production HV was calculated or displayed.

## Frozen baseline

- Repository: `1onlysm/seoungminlee`
- Source branch / commit: `work04ac-nvda-historical-ohlc-acquisition` / `31cebeafe15901430958d5c0c9e70598b4a0b734`
- Target branch: `work04ad-nvda-ohlcv-evidence-recovery`
- Target branch was created from the exact source commit; this report-only work does not change the dashboard or calculation code.
- Baseline full suite: **112/112 passed**.

## Candidate evidence

The accessible Library bundle `NVDA_NAVI-BOOT-NVDA-20260829T074538284767Z_execution_bundle.json` was downloaded for read-only audit to scratch, not copied into this repository. Its actual bundle SHA-256 is `11afaf56361858216019ac95027262e858a7d13a006b7489b2ed159ea7d9c96e`. The embedded list contains 90 rows, 2026-04-21 through 2026-08-27. Re-serializing those rows as compact JSON with sorted keys reproduces the bundle's declared embedded digest `735c5e5dbb42b9697930373b5436c53bbfa2db143d8f59aaa6e4f853fc836f65`.

This verifies the embedded payload's bytes against its self-declared digest; it does **not** recover or authenticate the upstream provider response. The metadata names its source only as `OHLCV`, does not identify an endpoint, and does not document currency, raw/adjusted basis, splits, or data-use rights. The separate NAVI TECH NEXT source tree contains app code for Tiingo daily prices and a personal-use acknowledgment, but that does not establish the candidate's provenance or authorize cross-project reuse.

Structural checks on the embedded rows found 90 unique strictly ordered dates, finite positive OHLC values, valid OHLC relationships, nonnegative numeric volume, and no malformed rows. Three omitted weekdays (2026-05-25, 2026-06-19, 2026-07-03) were identified; an authoritative exchange calendar was not used, so session completeness remains unverified. Structural plausibility is not source validation.

## HV status

No production calculation was run. HV10, HV20, HV30, and HV60 are all blocked pending verified provenance, authorized reuse, a declared adjustment/corporate-action basis, and session-calendar validation. The existing WORK 04-AB contract remains unchanged: close-to-close log returns, sample standard deviation (`ddof=1`), annualized by `sqrt(252) * 100`, requiring 11/21/31/61 eligible closes. IV, IV Rank, IV Percentile, and IV Skew remain unavailable.

## OPTIONS LAB data integrity

The preserved options raw JSON remains unchanged at SHA-256 `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce`. Its 2,188 contracts, 444 strikes, 24 expirations, and observed totals (Call/Put Volume 1,457,430 / 953,110; Call/Put OI 9,839,124 / 8,636,754) were retained. The date-only `$156.14` historical reference was not treated as an OHLC close.

## Tests and artifacts

The existing offline suite was run before and after the report-only changes: **112/112 passed** each time. Python compilation and generated-dashboard JavaScript syntax checks passed. The dashboard was regenerated offline and still reports volatility unavailable; real browser rendering was not verified in this run, and Galaxy device verification is pending.

See `audit_reports/work04ad_candidate_inventory.json`, `work04ad_source_recovery.json`, `work04ad_provenance_rights.json`, `work04ad_ohlcv_quality.json`, `work04ad_hv_verification.json`, `work04ad_data_integrity.json`, `work04ad_test_report.json`, `work04ad_source_manifest.json`, and `work04ad_galaxy_checklist.md`.

## Next actionable step

Obtain a preserved original OHLCV response and source manifest from the authorized data owner, including provider/endpoint, exact retrieval record, adjustment and split basis, exchange-session interpretation, and explicit OPTIONS LAB reuse permission. Do not import or activate HV until those gates pass. No acquisition request is authorized by this work.

## Safety

- LIVE market-data requests: 0
- GitHub Actions runs: 0
- `main` modifications: 0
- New provider integrations: 0
- APK changes: 0
- Original options snapshot changes: 0
- Production HV values emitted: 0
