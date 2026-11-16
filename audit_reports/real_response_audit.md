# WORK 04-D — Real response compatibility and missingness audit

Historical preserved JSON only. No API client was invoked; live HTTP requests: 0. Synthetic fixtures are reported separately by the offline test suite.

## Raw evidence and replay

| Symbol | Bytes | SHA-256 vs historical / manifest | HTTP/API | Raw rows | totalRecord/match | Contracts | Expiries | 04-C parsed contracts / expiries | Root | Snapshot readback |
|---|---:|---|---|---:|---:|---:|---:|---:|---|---|
| MSTR | 539435 | True / True | 200/200 | 1352 | 1352 / True | 1335 | 17 | 17 / 1335 | STANDARD:1335 | True |
| PLTR | 461945 | True / True | 200/200 | 1159 | 1159 / True | 1140 | 19 | 19 / 1140 | STANDARD:1140 | True |
| MU | 2246303 | True / True | 200/200 | 5629 | 5629 / True | 5603 | 26 | 26 / 5603 | STANDARD:5603 | True |
| CRWV | 429249 | True / True | 200/200 | 1080 | 1080 / True | 1061 | 19 | 19 / 1061 | STANDARD:1061 | True |
| COIN | 527443 | True / True | 200/200 | 1328 | 1328 / True | 1309 | 19 | 19 / 1309 | STANDARD:1309 | True |
| MARA | 155653 | True / True | 200/200 | 393 | 393 / True | 377 | 16 | 16 / 377 | STANDARD:377 | True |

Nasdaq response shape observed in all six files: top-level `data/message/status`; `data.totalRecord`; `data.table.rows`; expiry headers use `expirygroup`; contract rows use `strike` and `expiryDate`; paired call/put values are `c_*` and `p_*`; route root is encoded in lowercase `drillDownURL`. `data.table.asOf` was absent/null, so option-chain EOD freshness remains unverified.

## Field-level missingness

Counts per row contract: observed-positive / explicit-zero / `--` / JSON null / empty / field absent / invalid numeric. Header rows are excluded from denominators.

| Symbol | c_Volume | p_Volume | c_Openinterest | p_Openinterest |
|---|---:|---:|---:|---:|
| MSTR | 834/0/501/0/0/0/0 | 617/0/718/0/0/0/0 | 1250/0/85/0/0/0/0 | 879/0/456/0/0/0/0 |
| PLTR | 601/0/539/0/0/0/0 | 467/0/673/0/0/0/0 | 1102/0/38/0/0/0/0 | 853/0/287/0/0/0/0 |
| MU | 2551/0/3052/0/0/0/0 | 2036/0/3567/0/0/0/0 | 4905/0/698/0/0/0/0 | 3920/0/1683/0/0/0/0 |
| CRWV | 647/0/414/0/0/0/0 | 549/0/512/0/0/0/0 | 1017/0/44/0/0/0/0 | 903/0/158/0/0/0/0 |
| COIN | 644/0/665/0/0/0/0 | 546/0/763/0/0/0/0 | 1145/0/164/0/0/0/0 | 861/0/448/0/0/0/0 |
| MARA | 244/0/133/0/0/0/0 | 172/0/205/0/0/0/0 | 360/0/17/0/0/0/0 | 295/0/82/0/0/0/0 |

## Observation rates and distributions

Rates count positive numeric values and explicit zeros as observed. No threshold-based PASS is declared.

| Symbol | Overall volume | Overall OI | Near volume / OI | Mid volume / OI | Far volume / OI | ATM volume / OI | ATM basis |
|---|---:|---:|---:|---:|---:|---:|---|
| MSTR | 54.3% | 79.7% | 67.6% / 73.7% | 46.5% / 73.0% | 52.0% / 85.7% | 98.3% / 72.4% | absolute strike moneyness within 5% of Nasdaq lastTrade spot |
| PLTR | 46.8% | 85.7% | 48.6% / 77.5% | 50.7% / 80.1% | 44.7% / 91.5% | 88.6% / 95.5% | absolute strike moneyness within 5% of Nasdaq lastTrade spot |
| MU | 40.9% | 78.8% | 54.1% / 70.1% | 59.1% / 75.5% | 28.8% / 84.6% | 90.5% / 94.2% | absolute strike moneyness within 5% of Nasdaq lastTrade spot |
| CRWV | 56.4% | 90.5% | 66.7% / 90.6% | 61.7% / 81.6% | 46.5% / 94.5% | 92.6% / 93.4% | absolute strike moneyness within 5% of Nasdaq lastTrade spot |
| COIN | 45.5% | 76.6% | 51.4% / 64.9% | 41.9% / 69.7% | 44.2% / 84.4% | 91.1% / 78.0% | absolute strike moneyness within 5% of Nasdaq lastTrade spot |
| MARA | 55.2% | 86.9% | 56.5% / 88.3% | 51.4% / 78.8% | 57.0% / 91.7% | 100.0% / 100.0% | absolute strike moneyness within 5% of Nasdaq lastTrade spot |

Horizon buckets use 0–30, 31–90, and >90 calendar days from the preserved request-intent date. ATM-near uses ±5% of the raw Nasdaq `lastTrade` underlying quote only when that quote timestamp is within five minutes of request-intent time. This is not an option-chain timestamp.

Full per-expiration and per-strike distributions are in the companion offline `real_response_audit.json` artifact; per-contract raw and normalized values are in each isolated replay `quality.json`.

## Root-cause assessment

- **H1 — Inactive contracts:** partial association only. The >15%-from-spot group has lower volume observation than the ±5% ATM group in all six symbols; far-term volume observation is lower than near-term in five of six. This does not prove that `--` means no trading or that inactivity caused the display.
- **H2 — Nasdaq placeholder:** the literal `--` appears as a string value in all four fields and is never counted as zero. No numeric zero was present in these six contract-row sets. The response alone does not establish the vendor's semantic definition of `--`.
- **H3 — Expiration concentration:** missingness varies substantially by expiration within symbols, but the worst expiry differs by symbol and field; no single expiration explains the pattern globally.
- **H4 — Call/put asymmetry:** call observation rates exceed put rates for both volume and OI in all six symbols. This is an observed pattern, not proof of why the API displays it.
- **H5 — Parser error:** confirmed in WORK 04-C. Its `strikePrice`/`expiryDate`/`table.totalRecord` assumptions treat most contract rows as expiry headers, count headers as contracts, and fail to parse lowercase URL roots. The corrected replay matches raw totals and the six prior contract/expiry summaries. Missingness remains in raw values after this fix.

## Quality-gate proposal

1. Gate parser integrity separately: JSON parses; raw `rows` equals `data.totalRecord`; all contract rows have valid strike and expiration; root/duplicate counts are explicit.
2. Gate snapshot integrity separately: original SHA-256 unchanged; raw, CSV, quality, and manifest are readable after writing.
3. Report each field's observed rate and placeholder taxonomy by expiry, strike, horizon, ATM, and call/put. No universal completeness threshold is supported by this single snapshot set; propose thresholds only after a multi-date baseline is collected.
4. Keep `eod_freshness=EOD_UNVERIFIED`; block PCR, Max Pain, walls, GEX, and trade signals until option-chain EOD time and data completeness are independently validated.

## Safety

- Live API requests: 0. GitHub Actions runs: 0. Existing raw response files were read only; replay output was written under a separate scratch directory.
- All six original hashes matched historical/manifest evidence. Synthetic fixtures were used only by unit tests, not substituted for any missing raw response.
