# WORK 04-AB — NVDA OHLC acquisition proposal (not executed)

## Current gap

The accessible OPTIONS LAB snapshot contains options contracts and a date-only `$156.14` `data.lastTrade` reference, not an underlying daily OHLC history. No eligible NVDA OHLC file was found in the repository, preserved WORK 04-R/04-T/04-AA artifacts, workspace upload folder, or the Library search results inspected for NVDA OHLC. The separate NAVI TECH NEXT project was not accessed for data and no cross-repository copy was made.

## Separately approvable proposal

- **Candidate source:** a historical daily OHLC export from a user-authorized market-data account. Tiingo is only a candidate to review because it has been used in a separate project; OPTIONS LAB has no verified reuse authorization or entitlement in this task. No provider is selected or connected here.
- **Fields:** NVDA common-stock symbol/instrument ID, session date and timezone/calendar, Open/High/Low/Close, currency, raw-vs-adjusted convention, split/dividend adjustment metadata, source/retrieval timestamp, provider/source identifier, and documented export/reuse rights.
- **Lookback:** at least 61 eligible closes to support HV60, plus enough surrounding date/session information to detect gaps. A longer period is useful only if separately authorized.
- **Corporate actions:** provide one consistent adjustment series and split/dividend event treatment; do not splice conventions.
- **Authentication:** user-authorized credentials and provider entitlement must be confirmed outside this task. Do not place secrets in the repository.
- **Storage:** immutable source export in a new, run-ID-specific evidence directory; record SHA-256 and a manifest. Do not overwrite the options snapshot.
- **Validation gates:** instrument identity; provenance and rights; unique strictly ordered session dates; verified exchange calendar; no future dates; finite positive OHLC with `Low <= Open/Close <= High`; adjustment consistency; no unexplained gaps; enough rows; reproducible parser; independent numerical checks.
- **Expected request count:** **0 in this task**. A future request count cannot be fixed until the approved source/export mechanism and entitlement are selected; if a single bounded bulk-history request is supported, request only the required date range once. No request is authorized by this proposal.
- **Approval:** a separate user authorization is required before any source acquisition, provider connection, or API request.
