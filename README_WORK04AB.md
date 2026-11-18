# WORK 04-AB — Verified NVDA OHLC history and historical volatility

## Result

**Primary verdict: `NVDA_HV_HISTORY_SOURCE_ABSENT`.** The reference branch was verified and the target branch was created from its exact HEAD. The preserved OPTIONS LAB evidence contains no eligible NVDA daily OHLC history. Consequently, this work emits no production HV10/HV20/HV30/HV60 values and does not change the dashboard. It adds a guarded offline calculation contract/helper, deterministic `TEST_ONLY` numerical tests, source/quality audits, and a separately approvable acquisition proposal.

## Frozen baseline

- Repository: `1onlysm/seoungminlee`
- Reference branch: `work04aa-verified-volatility-contract`
- Verified remote HEAD: `e21da589658fb2ef658ad7d8f63d10a75cd3ed6b`
- Target branch: `work04ab-verified-nvda-hv`
- Parent: the verified WORK 04-AA HEAD above

WORK 04-AA baseline suite before this work: 94 tests passed. The final full repository suite after adding the guarded helper completed **112 tests, all passed** (18 new volatility helper tests; 0 failures). Python compile and generated-dashboard JavaScript syntax checks passed. Exact commands and statuses are recorded in `audit_reports/work04ab_test_report.json`.

## Source discovery and integrity

The preserved WORK 04-R raw options response is at:

`/workspace/scratch/navi-options-work04r-live/naviopt04r-20261117T051903Z-80a05c75/snapshots/data/options/2026-11-17/NVDA/2026-11-17T05-19-47.924836Z/raw.json`

Its SHA-256 remains `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce`. The source loader revalidated 2,188 options contracts, 444 strikes, 24 expirations, and observed totals: call volume 1,457,430; put volume 953,110; call OI 9,839,124; put OI 8,636,754. The original `$156.14` is a date-only November 16 historical reference and is not an OHLC series or synchronized spot price.

The repo's `historical_evidence.json` is metadata only. Workspace history files inspected were for other instruments (including SOXL, VOO, VEXC, and Nikkei); the uploaded zip was CDI ETF material. Library search surfaced other-symbol artifacts, not an NVDA OHLC source. No separate-project data was copied.

See `audit_reports/work04ab_source_inventory.json` and `audit_reports/work04ab_data_integrity.json` for paths and classification.

## Calculation contract

For exactly N valid daily close-to-close returns:

`r_t = ln(C_t / C_(t-1))`

`HV_N (%) = sample_stddev(r_t, ddof=1) × sqrt(252) × 100`

HV10/20/30/60 require 11/21/31/61 verified closes, respectively. Dates must be unique and strictly ordered; expected exchange sessions must match exactly; prices must be finite and positive; OHLC bounds must be valid; and the adjustment convention must be known and consistent. Missing sessions are not filled or bridged. The annualization factor 252 is a conventional assumption. This is close-to-close historical volatility, not implied volatility or intraday realized volatility.

The helper in `options_collector/historical_volatility.py` refuses to calculate unless the caller supplies a verified-source verdict, NVDA identity, SHA-256, declared adjustment convention, adjustment-consistency result, and exact expected-session list. It has no market-data acquisition or dashboard-output path. Tests use synthetic values marked `TEST_ONLY`; none are included in market-data artifacts.

## Feasibility

HV10, HV20, HV30, and HV60 are formula-specified but **data-not-ready** and **not production-display-ready**. IV, IV Rank, IV Percentile, IV Skew, and the existing PROVISIONAL safeguards remain unchanged. See `audit_reports/work04ab_hv_contract.json` and `audit_reports/work04ab_hv_feasibility.json`.

## Run offline tests

```bash
python -m unittest discover -s tests -v
python -m py_compile options_collector/historical_volatility.py tests/test_historical_volatility.py
```

The exact executed test counts are in `audit_reports/work04ab_test_report.json`. No market-data API was called. Browser rendering and Galaxy device validation are not claimed.

## Dashboard artifact

The existing dashboard code and blocked-volatility UI were not changed. A fresh standalone HTML was generated offline from the preserved WORK 04-R/04-T files at:

`/workspace/scratch/navi-options-work04ab-output/nvda_options_dashboard.html`

The output is options-only; it contains no calculated HV number. Its inline JavaScript passed `node --check`. A real browser render was attempted with local Chromium but the environment denied its process socket (`socket() failed: Operation not permitted`, exit 134); browser rendering is therefore unverified. Galaxy device validation is pending. The local generation command is captured in `audit_reports/work04ab_dashboard_build.log`.

## Acquisition proposal

`audit_reports/work04ab_acquisition_proposal.md` describes the required fields, provenance, adjustment contract, 61-close minimum, storage, quality gates, and approval boundary. It makes no acquisition request and does not authorize a provider.

## Safety

- LIVE market-data requests: 0
- GitHub Actions: 0
- Main changes: 0
- New provider integrations: 0
- APK changes: 0
- Options raw snapshot changes: 0
- Production HV values emitted: 0
