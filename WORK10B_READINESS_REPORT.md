# NAVI OPTIONS LAB — WORK 10-B Readiness Report

**Audit date:** 2026-11-21 (Asia/Seoul)  
**Scope:** read-only baseline review plus isolated code and offline regression only  
**Final verdict:** `NASDAQ_SPY_OFFLINE_REPAIR_PARTIAL`

## A. Executive verdict

| Question | Finding |
|---|---|
| Nasdaq retained as primary provider? | **YES.** The isolated implementation still targets Nasdaq's existing options-chain route. |
| HTTP 403 root cause confirmed? | **NO.** The 403 responses are confirmed; their cause is not. |
| SPY collector repaired offline? | **YES, offline only.** The isolated parser, data contract, quality gates, append-only local store and workflow now fail closed. Live operation remains unverified. |
| Contract and freshness gates implemented? | **PARTIAL.** UTC/ET capture, chain as-of, per-field provenance and fail-closed gates are implemented. Separate Volume/OI as-of timestamps are required for their metrics and are absent from the tested source example. The included market calendar covers 2026 only. |
| Historical storage implemented and tested offline? | **PARTIAL.** Append-only local snapshots and integrity checks are implemented and tested. No durable production storage has been activated. |
| Isolated workflow ready for a controlled pilot? | **NO.** The branch workflow is offline-only. Nasdaq access path, execution environment, data-retention terms and the separate explicit one-request authorization are still required. |
| Production daily collection restored? | **NO.** No production workflow or persistent store changed. |

**Main modifications: 0 · GitHub Actions runs started by WORK 10-B: 0 · Nasdaq/Tiingo requests: 0 · APK builds: 0.**

## B. Frozen baseline and repository state

- Repository: `1onlysm/seoungminlee`; default branch: `main`.
- Source branch and frozen source commit: `main` at `2f11407be204c0621e974663cfc3cd2e9de863b1`.
- Isolated target branch: `work10b-nasdaq-spy-quality-recovery`, created from that exact commit.
- Reference SHAs inspected: `work03-multi-ticker-options` `80399057f486905ddefc2703fe5b4d9bbc0000c3`; `work03-options-api-diagnostic` `7eb582115c4aa6803d0223d2cb7e5d6cda9e6451`; `work09-nvda-hv-import-integration` `cfce9c9ccd3f5b87d5598e9d93c21ecd2beee48b`.
- `work04f-mstr-first-live-probe` was not found in the accessible branch listing. The MSTR probe evidence was inspected from the run on `main` instead.
- `main` contains three workflows: scheduled SPY EOD, manual MSTR offline regression and manual one-shot MSTR live probe. No active default-branch 14-symbol daily workflow was found. Experimental multi-symbol code/workflows on other branches are not production deployment.
- Relevant files added/changed on the isolated branch: `.github/workflows/spy-options-eod.yml`, `collector.py`, `options_pipeline/{__init__,market_calendar,client,contract,freshness,pipeline,quality,registry,storage,workflow_gate,cli}.py`, `tests/test_options_pipeline.py`, `tests/fixtures/nasdaq_spy_valid_synthetic.json`, and this report.
- The branch workflow is `workflow_dispatch` only and runs the offline suite plus an explicitly synthetic fixture. It has no scheduled trigger and cannot issue live requests. It has not been executed in Actions.

## C. Existing production workflow and historical Actions evidence

### Schedule behavior

The frozen `main` workflow used cron `5 22 * * 1-5` UTC, targeting 22:05 UTC each weekday. That is 17:05 ET during EST and 18:05 ET during EDT; fixed UTC means its Eastern wall-clock time shifts with daylight saving time. The current implementation's run-time ET conversion handles the offset, but the cron is not a fixed local Eastern schedule. The old workflow only rejected weekends and pre-16:30 ET execution; it did not consult a US market holiday or early-close calendar. It could therefore run on market holidays and after early closes. GitHub's actual start could be delayed well beyond the cron time.

The latest 30 calendar days of accessible Actions history contain 31 total repository runs and 19 SPY scheduled attempts. The table below includes every scheduled SPY run returned by the accessible history. UTC and ET are the actual start times; the delayed 11/06 attempt began on 11/07 UTC/ET and missed its session window.

Full main commit SHAs represented below: `2f11407be204c0621e974663cfc3cd2e9de863b1`; `228f99657f59e46f700c964b4f01f409ec39cf46`; `89fa18e26816e51c8c3e2db2c384171739ce18f2`; `5a5c39a6f62cf94bb39dbac9c4bc2db7eb556bc1`; `69b7c647a816c057021df0a0833635e2f2c4f85c`.

| Run ID | Event / branch / commit | Actual start UTC | Actual start ET | Conclusion | HTTP / symbols | Artifact / persistence | Classification |
|---:|---|---|---|---|---|---|---|
| 44831652592 | schedule / main / `2f11407…` | 11-20 22:46 | 11-20 17:46 | success | SPY; response parsed, HTTP code not persisted | Artifact present (30-day retention); no permanent store | WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 44631972854 | schedule / main / `2f11407…` | 11-19 22:48 | 11-19 17:48 | success | SPY; status not persisted in artifact | Artifact present; temporary | WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 44415486261 | schedule / main / `2f11407…` | 11-18 22:51 | 11-18 17:51 | success | SPY; status not persisted in artifact | Artifact present; temporary | WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 44194367191 | schedule / main / `2f11407…` | 11-17 22:53 | 11-17 17:53 | success | SPY; status not persisted in artifact | Artifact present; temporary | WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 43973214404 | schedule / main / `228f996…` | 11-16 22:46 | 11-16 17:46 | failure | SPY; HTTP 403 | No artifact | HTTP_403_BLOCKED |
| 43521453418 | schedule / main / `228f996…` | 11-13 22:42 | 11-13 17:42 | failure | SPY; HTTP 403 | No artifact | HTTP_403_BLOCKED |
| 43322757676 | schedule / main / `228f996…` | 11-12 22:45 | 11-12 17:45 | failure | SPY; HTTP 403 | No artifact | HTTP_403_BLOCKED |
| 43115021599 | schedule / main / `228f996…` | 11-11 22:50 | 11-11 17:50 | failure | SPY; HTTP 403 | No artifact | HTTP_403_BLOCKED |
| 42916648349 | schedule / main / `228f996…` | 11-10 22:40 | 11-10 17:40 | failure | SPY; HTTP 403 | No artifact | HTTP_403_BLOCKED |
| 42714359543 | schedule / main / `228f996…` | 11-09 22:43 | 11-09 17:43 | success | SPY; status not persisted in artifact | Artifact present; temporary | WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 42306284363 | schedule / main / `89fa18e…` | created 11-06 22:38; started 11-07 09:50 | 11-07 04:50 | failure | SPY; collection-window gate failed before request | No artifact | SCHEDULE_MISSED |
| 42126426232 | schedule / main / `5a5c39a…` | 11-05 23:02 | 11-05 18:02 | success | SPY; response status not retained | No artifact | WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 42116651785 | schedule / main / `5a5c39a…` | 11-05 21:53 | 11-05 16:53 | success | SPY; response status not retained | No artifact | WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 41930354139 | schedule / main / `5a5c39a…` | 11-04 23:01 | 11-04 18:01 | success | SPY; response status not retained | No artifact | WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 41920446146 | schedule / main / `5a5c39a…` | 11-04 21:54 | 11-04 16:54 | success | SPY; response status not retained | No artifact | WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 41735604051 | schedule / main / `5a5c39a…` | 11-03 23:00 | 11-03 18:00 | success | SPY; response status not retained | No artifact | WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 41725698818 | schedule / main / `5a5c39a…` | 11-03 21:52 | 11-03 16:52 | success | SPY; response status not retained | No artifact | WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 41541494644 | schedule / main / `5a5c39a…` | 11-02 22:57 | 11-02 17:57 | success | SPY; response status not retained | Artifact present; temporary | WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 41531929617 | schedule / main / `69b7c64…` | 11-02 21:50 | 11-02 16:50 | success | SPY; response status not retained | No artifact | WORKFLOW_SUCCESS_DATA_UNVERIFIED |

Other relevant manual/diagnostic runs in the accessible window:

| Run ID | Workflow / branch / commit | Start UTC / ET | Conclusion | Requests / output | Artifact and classification |
|---:|---|---|---|---|---|
| 43978844572 | MSTR one-shot / main / `2f11407be204c0621e974663cfc3cd2e9de863b1` | 11-16 23:23 / 18:23 | failure | MSTR one request, HTTP 403, zero contracts | Failure evidence artifact 14281976731; HTTP_403_BLOCKED |
| 43977568138 | MSTR offline regression / main / `8575b7c8112da4889f6caf75fa05838175e97d50` | 11-16 23:14 / 18:14 | success | No provider request | Offline test artifact 14282705241; not collection |
| 43977546287 | MSTR offline regression / main / `8575b7c8112da4889f6caf75fa05838175e97d50` | 11-16 23:14 / 18:14 | success | No provider request | Offline test artifact 14281003625; not collection |
| 43149945561 | API diagnostic / `work03-options-api-diagnostic` / `7eb582115c4aa6803d0223d2cb7e5d6cda9e6451` | 11-12 03:42 / 11-11 22:42 | success | 10 symbols attempted; 10 HTTP 403; zero succeeded | Diagnostic artifact 13913361333; diagnostic execution only |
| 43149767198 | SPY manual dispatch / main / `228f99657f59e46f700c964b4f01f409ec39cf46` | 11-12 03:40 / 11-11 22:40 | failure | SPY attempted, HTTP 403 | No artifact; HTTP_403_BLOCKED |
| 42474293742 | SPY manual dispatch / main / `89fa18e26816e51c8c3e2db2c384171739ce18f2` | 11-08 11:06 / 06:06 | failure | ET window gate failed before request | No artifact; no collection |
| 41540296080 | SPY manual dispatch / main / `5a5c39a6f62cf94bb39dbac9c4bc2db7eb556bc1` | 11-02 22:48 / 17:48 | success | SPY response parsed; HTTP status not saved | Artifact 13185681628; WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 41539846686 | SPY manual dispatch / main / `e9d1c94040c93c01b4281ae5d521f252f5ee29f0` | 11-02 22:44 / 17:44 | success | SPY response parsed; HTTP status not saved | Artifact 13185466994; WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 41539396722 | SPY manual dispatch / main / `106cb61123a9e77f54d3aac07f98d720e4b4ff2c` | 11-02 22:41 / 17:41 | success | SPY response parsed; HTTP status not saved | Artifact 13185293418; WORKFLOW_SUCCESS_DATA_UNVERIFIED |
| 41538651364 | SPY manual dispatch / main / `120b4b5c8159ef4d698a34abad335abc21d981d0` | 11-02 22:36 / 17:36 | failure | SPY data failed timestamp gate; HTTP status not retained | No artifact; INSUFFICIENT_EVIDENCE |
| 41538214224 | SPY manual dispatch / main / `69b7c647a816c057021df0a0833635e2f2c4f85c` | 11-02 22:33 / 17:33 | failure | SPY data failed timestamp gate; HTTP status not retained | No artifact; INSUFFICIENT_EVIDENCE |
| 41527527903 | SPY manual dispatch / main / `69b7c647a816c057021df0a0833635e2f2c4f85c` | 11-02 21:20 / 16:20 | success | Request/output status not established from saved artifacts | No artifact; INSUFFICIENT_EVIDENCE |

The manual-run list above captures the market-data diagnostic/probe/offline runs. Two additional unrelated repository workflow runs in the 31-run window are outside the options pipeline.

### Latest real artifact inspection

Artifact `spy-options-44831652592` (artifact ID `14675784719`, created 2026-11-20 22:46 UTC, 58,641 bytes, not expired at audit time) contained only `summary.json`, `contracts.csv`, and `experimental_metrics.json` (259,397 uncompressed bytes). It did not contain raw Nasdaq JSON. The summary marked the data `UNVERIFIED` and `approved_for_navi=false`; the collector log showed `max_pain_computed=0`.

The run had 6,250 paired strike rows and 31 expirations, 491 distinct strike values across expiration dates, from 2026-11-20 to 2029-01-19. The CSV contained only `root, expiry, strike, c_Volume, p_Volume, c_Openinterest, p_Openinterest`; it did not preserve option identifiers, explicit contract-side rows, Bid, Ask, Last, or quote timestamps. The capture was 17:46 ET, while `lastTrade` only said `$690.43 (AS OF NOV 19, 2026)`; the chain as-of, Volume as-of, and OI reporting date were absent. Collection time is not source freshness.

## D. 20-session coverage matrix

The 20 completed US trading sessions are 2026-10-26 through 2026-11-20, excluding weekends. There was no exchange holiday in this interval. The target denominator is **20 × 14 = 280 symbol-days**. Only SPY is scheduled on `main`; other 13 targets are `NO_RUN` on every date. The six retained SPY artifacts are still `UNVERIFIED` because chain/field timestamps and raw provenance are insufficient; no cell qualifies as `VALID_SNAPSHOT`.

| Session | SPY | Other 13 symbols |
|---|---|---|
| 2026-10-26 | NO_RUN | NO_RUN |
| 2026-10-27 | NO_RUN | NO_RUN |
| 2026-10-28 | NO_RUN | NO_RUN |
| 2026-10-29 | NO_RUN | NO_RUN |
| 2026-10-30 | NO_RUN | NO_RUN |
| 2026-11-02 | UNVERIFIED | NO_RUN |
| 2026-11-03 | MISSING_ARTIFACT | NO_RUN |
| 2026-11-04 | MISSING_ARTIFACT | NO_RUN |
| 2026-11-05 | MISSING_ARTIFACT | NO_RUN |
| 2026-11-06 | NO_RUN (schedule started outside window) | NO_RUN |
| 2026-11-09 | UNVERIFIED | NO_RUN |
| 2026-11-10 | HTTP_FAILURE (403) | NO_RUN |
| 2026-11-11 | HTTP_FAILURE (403) | NO_RUN |
| 2026-11-12 | HTTP_FAILURE (403) | NO_RUN |
| 2026-11-13 | HTTP_FAILURE (403) | NO_RUN |
| 2026-11-16 | HTTP_FAILURE (403) | NO_RUN |
| 2026-11-17 | UNVERIFIED | NO_RUN |
| 2026-11-18 | UNVERIFIED | NO_RUN |
| 2026-11-19 | UNVERIFIED | NO_RUN |
| 2026-11-20 | UNVERIFIED | NO_RUN |

Coverage totals, based only on inspected logs and saved artifacts:

- Expected: **280 symbol-days**.
- Verified valid: **0**; partial snapshots: **0**; verified collection coverage: **0%**.
- Failed: **5** (five SPY HTTP 403 days).
- Unverified: **6** (SPY artifacts on 11/02, 11/09, 11/17–20).
- Missing artifact: **3** (SPY runs succeeded on 11/03–05 but no artifact was available).
- No run: **266** (260 days for the 13 non-SPY symbols plus six SPY dates without an in-window capture).

## E. Nasdaq HTTP 403 diagnosis

### Confirmed

- The main SPY collector uses `GET https://api.nasdaq.com/api/quote/SPY/option-chain?assetclass=etf&limit=20000&fromdate=all`, timeout 30 seconds, and no retry loop. It sent a browser-like User-Agent and Nasdaq Referer. A non-2xx `urlopen` exception bubbles up and fails the collector.
- Saved Actions logs directly show `HTTP Error 403: Forbidden` for SPY runs `42916648349`, `43115021599`, `43322757676`, `43521453418`, and `43973214404`; saved diagnostic log `43149945561` records HTTP 403 for each of its 10 symbols. The MSTR one-shot log also records HTTP 403.
- The failed 403 SPY runs had no data artifact. No retry occurred in the one-shot MSTR run.
- Other SPY runs returned a parseable payload and uploaded artifacts, but those artifacts did not record HTTP status or preserve raw payloads. A green job alone does not prove provider response status or chain freshness.
- The actual access-denied response body/root cause was not preserved for the SPY 403 runs. No log proves rate-limit headers, a specific DNS failure, endpoint contract change or IP/network policy.

### Strongly supported, hypothesis, and unresolved

- **Strongly supported:** responses differ by execution context: GitHub-hosted Actions repeatedly received 403 while earlier work reported local HTTP 200. That is consistent with environment-dependent access, but does not identify the provider's decision rule.
- **Hypotheses only:** runner egress/IP reputation or Nasdaq edge policy; undocumented access/automation restrictions on this web endpoint; changed endpoint behavior; header/User-Agent handling; or rate limiting. The logs do not distinguish these.
- **Unverified:** whether the current public web route is a supported API for this use, its applicable terms/access policy, the correct required headers, rate limits, and whether Nasdaq offers an explicitly authorized alternative route for this account.
- Nasdaq's published Cloud Data Service documentation describes a separate authenticated data product. It is not documentation for the `/api/quote/{symbol}/option-chain` web route and therefore does not confirm a fix or required authentication for the route used here: [Nasdaq Cloud Data Service API documentation](https://data.nasdaq.com/docs/api).

**Root cause conclusion:** HTTP 403 is confirmed; the root cause is **unresolved**. The approved path is to verify the current endpoint and its access terms with Nasdaq or use an explicitly authorized Nasdaq-provided access path, then authorize one bounded SPY pilot in an approved environment. Do not retry 403, rotate IPs, proxy around restrictions, spoof browser fingerprints, or bypass access controls.

## F. SPY contract, freshness, and quality controls

### New versioned contract

- Normalization schema: `navi-options-chain/1.0.0`; quality schema: `navi-options-quality/1.0.0`.
- Snapshot metadata records provider, endpoint identifier, requested symbol, HTTP status, UTC/ET capture, scheduled-start placeholder, session date, market context, source schema version, normalization version, raw SHA-256, parser status and quality status.
- Each normalized call/put record preserves source option symbol/contract identifier when supplied; root/root class; expiration; strike; side; Volume, OI, Bid, Ask, Last and quote timestamp; and per-field source availability.
- Numeric source state is kept distinct: `MISSING`, `NULL`, `EXPLICIT_ZERO`, `VALID_POSITIVE`, `INVALID_NEGATIVE`, `INVALID_VALUE`, `NOT_PROVIDED_BY_SOURCE`. Null/missing values remain `null`; no null-to-zero conversion or fake IV.
- Option identifiers are checked against available side, expiration and strike information; adjusted roots are labeled separately. Duplicate contract keys, unknown sides, invalid expirations/strikes, root mismatch and expired-at-session issues are reported.
- The 14-symbol registry is retained with ETF/equity endpoint parameter mapping, and processing/storage are per-symbol. No multi-symbol network loop or daily activation was added.

### Freshness and market calendar

Freshness statuses implemented: `CURRENT_VERIFIED`, `RECENT_NOT_CURRENT`, `STALE`, `SOURCE_TIME_UNAVAILABLE`, `HTTP_FAILURE`, `UNVERIFIED`. A timezone-aware chain as-of timestamp must be present, no later than capture, and match the verified session after that session's official close to reach `CURRENT_VERIFIED`. Capture time and underlying `lastTrade` are explicitly not chain freshness proof. Separate Volume and OI as-of timestamps are preserved if supplied; Volume/OI metrics are blocked when their own as-of evidence is unavailable. Per-contract quote timestamps are separately preserved.

The offline calendar is explicit for 2026, including US market holidays and known early closes, and fails closed outside that year. It converts UTC with `America/New_York`, so DST is handled in timestamp conversion; expanding calendar coverage is required before later-year operation. The calendar reference is the [NYSE 2026 holiday and early-close calendar](https://www.nyse.com/markets/hours-calendars).

### Latest SPY field evidence (real saved artifact 2026-11-20)

Denominator is 6,250 paired strike rows per c/p field. The archived output exposed zero explicit zeros for the four reported quantity columns. These are not complete contract counts; each row stores both sides in columns.

| Field | Missing | Missing % | Explicit zero | Positive | Observed valid aggregate |
|---|---:|---:|---:|---:|---:|
| Call Volume | 2,346 | 37.54% | 0 | 3,904 | 7,500,658 |
| Put Volume | 2,721 | 43.54% | 0 | 3,529 | 11,113,607 |
| Call OI | 865 | 13.84% | 0 | 5,385 | 7,192,783 |
| Put OI | 2,113 | 33.81% | 0 | 4,137 | 11,799,813 |

The old output contains no Bid/Ask, Last, option IDs, explicit side records or per-contract quote times, so Bid/Ask and quote-time missingness in the saved artifact is **100% unavailable**. It does not provide HTTP status in its summary; the run and parser logs are available. Source response bytes are not in the artifact, so its logged/stored raw hash cannot be recomputed from the retained files. No volume or OI reporting timestamp is recorded. Negative/invalid counts are not separately archived; no zero count is claimed for invalids.

### Quality and metric thresholds

- Side-specific Volume/OI coverage denominator includes every eligible record on that side; missing/null/invalid entries remain in the denominator.
- At least **95% valid field coverage on both sides**, valid structure, and current field-specific freshness are required before a ratio/concentration input gate can pass.
- Max Pain requires **100% OI coverage on both sides**.
- Crossed/locked/zero/negative quote counts and spread statistics are available when quotes exist; missing Bid/Ask and quote time are separately counted.
- Formula implementation is not approved in this work. The new engine classifies gates and records observed aggregates but does not mark derived ratios/OI wall/Max Pain as NAVI-approved. All derived indicators remain blocked/restricted until formula review, source freshness, input coverage and structure pass independently.
- From the real 2026-11-20 artifact, Volume and OI fail the 95% gate on at least one side. All related metrics are therefore blocked. Max Pain is further blocked because OI is incomplete and no source OI as-of was recorded.

## G. Historical storage and retention

- Implemented local append-only path: `data/options/<session-date>/<symbol>/<capture-id>/`.
- Each snapshot includes `manifest.json`, `normalized_records.json`, `quality_report.json`, and `error_report.json`; optional `raw_payload.json` is written only when raw bytes are provided and retention permission is explicitly true.
- Different capture IDs are preserved independently. Existing targets fail with `SNAPSHOT_OVERWRITE_BLOCKED`; writes stage in a temporary directory and atomically rename; manifest hashes are verified by readback. Missing output/files/schema mismatch/hash mismatch fail validation.
- HTTP failures can be stored as zero-record error snapshots with explicit failure classification and cannot pass collection validation.
- The public repository's historical artifacts retained summary/CSV/metrics for 30 days, not an append-only multi-year dataset. The local storage code has no activated persistent remote backend or retention policy. Production storage requires a separately authorized, access-controlled destination and an explicit Nasdaq raw-payload retention review. Until then, historical volume/OI changes, put/call history, strike/expiration concentration trends and reliable cross-day comparisons are **not supported**.

## H. Failure-path matrix

| Existing main component | Condition | Observed behavior / gap | Isolated correction |
|---|---|---|---|
| `.github/workflows/spy-options-eod.yml`, collector step | HTTP error such as 403 | `urlopen` raises; collector exits nonzero. Failure is not tagged with a structured 403 classification by the old workflow. | Single-attempt client labels 403 explicitly and stores bounded error-body bytes only in memory for an authorized pilot; no retry. |
| `collector.py:parse` | non-200 API rCode, empty/short/truncated rows, malformed row | Raises and fails collection; no empty-chain-as-success behavior in this version. | Strict parser rejects missing/empty structures, total mismatch and malformed records with explicit reason. |
| `collector.py:parse` | valid paired strike row | Normalizes root/expiry/strike and c/p Volume/OI only; discards contract IDs, explicit call/put records, Bid/Ask/Last and quote timestamps. | Versioned side-specific record schema retains source fields and field provenance, without fabrication. |
| `collector.py:main` | capture after close | Uses underlying `lastTrade` only as a diagnostic; writes chain-as-of as unavailable and `UNVERIFIED`. | Dedicated chain/Volume/OI freshness classifiers. Each metric needs its own timestamp evidence. |
| `collector.py:main` | weekday holiday / early close | Old guard checks weekday and minimum 16:30 ET only; no market holiday or early-close calendar. | 2026 calendar, ET conversion and market-context classification; unsupported years fail closed. |
| `.github/workflows/spy-options-eod.yml`, output verification/upload | output missing / artifact absent | 11/03–05 runs concluded green but have no accessible artifacts; successful workflow did not establish persistent evidence. | Offline workflow validates files/schema before success and is manual-only; missing output is a hard failure in its gate. |
| artifact storage | artifact retention expiry | Old workflow used a 30-day artifact retention; no durable data store. | Local append-only snapshots with manifests/hashes; remote deployment remains unconfigured. |
| source timestamp handling | stale underlying lastTrade or absent chain as-of | Latest real artifact captured 11/20 but underlying lastTrade says 11/19; chain/Volume/OI timestamps absent. | Missing source time returns `SOURCE_TIME_UNAVAILABLE`; no freshness guess from capture/underlying data. |

## I. Offline regression results

`python3 -m unittest discover -s tests -q`: **38 tests passed, 0 failed**. `py_compile` passed. Offline CLI processed four records from the clearly labeled `SYNTHETIC_TEST_FIXTURE_NOT_LIVE_NASDAQ_DATA`, wrote a temporary snapshot, and read back its manifest and file hashes. The fixture result was tagged `SYNTHETIC_OFFLINE_FIXTURE`; it is not live-data evidence.

Cases covered include valid paired structure, HTTP 403/429/500 classification, timeout without retry (fake opener), empty body, malformed JSON, missing call/put sides, missing/null/zero/negative Volume/OI, duplicates, missing expiration, invalid strike, missing/stale source as-of, adjusted roots, missing output/artifact, overwrite attempts, schema mismatch, holiday, DST transition, unsupported calendar year, coverage gating, 403 error snapshot, 14-symbol registry isolation, and raw-retention disabled. Live-mode CLI is hard-blocked in WORK 10-B. No network request occurred during tests.

Limitations: fixtures are synthetic; there is no offline test that validates the provider's current live schema or endpoint entitlement. Calendar data is only covered through 2026. The suite does not establish GitHub Actions behavior because the new workflow was not run.

## J. Pilot readiness gates

| Gate | Status | Evidence / requirement |
|---|---|---|
| Nasdaq retained; exact SPY route encoded | PASS (implementation only) | Existing route retained; no provider replacement. |
| 403 resolved with authorized provider access | BLOCKED | Cause and route terms unresolved; must be verified with Nasdaq/authorized access path. |
| Approved execution environment | BLOCKED | Actions runner has repeated 403; an allowed environment must be established before the pilot. |
| Offline parser/schema/quality tests | PASS | 38/38 offline tests. |
| Source timestamp/freshness fields | BLOCKED | Chain as-of must be supplied; Volume and OI as-of evidence needed for those metrics. |
| Data retention permission and destination | BLOCKED | Raw retention not authorized; durable destination not configured. |
| Pilot workflow/live request authorization | BLOCKED | No live route in the branch workflow; the next work requires new explicit authorization for exactly one request. |
| Production storage/schedule | NOT ACTIVATED | No Actions run, production edit, or deployment in WORK 10-B. |

### Proposed next WORK (exactly one)

**WORK 10-C — AUTHORIZED SINGLE-REQUEST NASDAQ SPY LIVE PILOT**: only after Nasdaq route/access terms, execution environment and retention policy are approved; maximum one SPY request, zero automatic retries, preserve bounded error evidence and write one append-only snapshot; no 14-symbol batch and no production activation. The pilot must verify response schema, current chain/Volume/OI timestamps, 95% side coverage (100% for Max Pain inputs), identifiers/quotes, raw-hash integrity where retention is allowed, and explicit failure status. This work does not execute that request.

Pilot parameters to freeze in WORK 10-C:

- Endpoint: `https://api.nasdaq.com/api/quote/SPY/option-chain?assetclass=etf&limit=20000&fromdate=all`; symbol: `SPY`; maximum: one bounded GET; retries: zero.
- Execution environment: only an environment explicitly approved for this Nasdaq endpoint after the repeated Actions 403 is resolved; no environment was approved during WORK 10-B.
- Expected output: versioned manifest, normalized records, quality report, error report, source hash. Output destination: append-only `data/options/<session-date>/SPY/<capture-id>/` in an approved private/durable store, not a public repo. Raw body retention only after terms/security review permits it.
- Pass conditions: HTTP 200 alone is insufficient; chain as-of and field-specific Volume/OI as-of present and current; parser/identifier/side checks pass; at least 95% Volume/OI valid coverage on both sides; Bid/Ask and quote-time missingness disclosed; no invalid negatives, duplicate keys, unsupported expirations or underlying mismatch. Max Pain remains blocked below 100% OI coverage.
- Failure: preserve an explicit HTTP/transport/parser/storage error record if permitted, execute no retry, and fail the pilot gate. Rollback: discard the isolated pilot execution configuration and leave production `main` untouched; the branch's offline workflow remains non-scheduled.
- Required authorization: a new explicit user authorization for the single live Nasdaq request after the access path, runner, and retention gates pass.

### Remaining blocker priorities

- **P0 —** obtain Nasdaq-confirmed access terms/path and an approved execution environment; collect source chain as-of plus separate Volume/OI reporting timestamps; do not send a pilot until all gates pass.
- **P1 —** approve a durable private append-only storage destination and retention policy; update calendar coverage from authoritative exchange data; retain sanitized failure evidence and request/response status for each attempt.
- **P2 —** complete formula review for derived indicators, then run a separately approved SPY pilot and observe multiple trading sessions before proposing a 14-symbol rollout.

## K. Final classification

`NASDAQ_SPY_OFFLINE_REPAIR_PARTIAL`

The offline pipeline is repaired and regression-tested on an isolated branch. Production daily collection is not restored: the live access cause is unresolved, scheduled Actions have repeated 403s and missing artifacts, source freshness is incomplete, and no permanent historical store exists.
