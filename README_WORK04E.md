# WORK 04-E — MSTR single-symbol live readiness

## Baseline and restrictions

- Repository: `1onlysm/seoungminlee`
- Frozen baseline: `work04d-real-response-quality-audit` at `336d63790145330d73170218b74a46bf022a274d`
- Target: `work04e-single-symbol-live-readiness`
- This branch is limited to a one-symbol MSTR runner, offline tests, workflow design, and evidence. It does not modify the baseline or protected branches.

## Execution contract

`options_collector/single_run.py` defaults to OFFLINE. Offline mode requires a local JSON input, does not construct the Nasdaq client, and does not call the network. LIVE requires `--mode live --confirm-live`; the symbol is fixed to MSTR; the client has a 30-second timeout, `build_opener(NoRedirect)`, and one `fetch_once` call maximum. The normal `NasdaqClient` retains urllib's default proxy behavior and has no retry or redirect-following behavior.

The live gate writes and fsyncs `REQUEST_INTENT_RECORDED`, then `REQUEST_DISPATCHED` immediately before the client call. Dispatch records invocation intent and is not proof of server receipt. Results include HTTP status, API rCode, bytes, SHA-256, contract/expiry counts, quality/EOD state, and snapshot path. Error response bodies are preserved separately. HTTP 403/429 and network errors end the run without retry. Snapshot output is immutable/versioned; raw JSON, CSV, quality, and snapshot manifest are reread and checked. EOD remains unverified and derived indicators remain blocked.

Example offline command using a preserved response:

```bash
python -m options_collector.single_run --mode offline --symbol MSTR \
  --input /path/to/MSTR.response --output runs
```

LIVE is implemented but was not invoked in WORK 04-E. A separate user authorization is still required before any real request.

## Offline E2E evidence

The preserved MSTR response from HF02 was used directly, not a synthetic replacement. It was read-only; the original SHA-256 remained `619151c5a3bdd73e763a61f06908f85e9afd2917ab5b364812beba2000e61c08`. The isolated run produced HTTP/API evidence `200/200` from the retained manifest/response, 1,335 contracts, 17 expiries, `QUALITY_LIMITED`, and `EOD_UNVERIFIED`. Snapshot raw, contracts CSV, quality JSON, manifest, summary CSV, and final report were saved and read back. Live request count was 0.

The run's local ID and output directory are recorded in the WORK 04-E handoff report. The original raw JSON is not included in this branch.

## GitHub Actions safety audit

The inherited `options-14-experimental.yml` is manual-only, defaults to offline, has no schedule, and its live branch exits before making requests. The new `.github/workflows/options-mstr-single-probe.yml` is also `workflow_dispatch` only, defaults to offline, and adds a required false-by-default `confirm_live_probe` input. Live mode is hard-coded to MSTR, runs the offline suite first, has a 5-minute timeout, `contents: read`, no secrets, and stores evidence artifacts for 14 days. No schedule was added.

A named GitHub Environment, `navi-options-live-probe`, is referenced in the live job. Required-reviewer protection for that environment was not verified or configured here. `workflow_dispatch` availability on a non-default branch remains unverified. Prior GitHub Actions HTTP 403 responses from Nasdaq remain an access risk; there is no bypass or retry path.

## Verification

The offline suite includes the WORK 04-C/D regressions plus 20 single-run safety tests. The preserved real MSTR response E2E was run separately from synthetic-fixture unit tests. No Actions workflow was run and no live Nasdaq request was made.
