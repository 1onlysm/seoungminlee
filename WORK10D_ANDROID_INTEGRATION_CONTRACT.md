# WORK 10-D — Android OPTIONS LAB Integration Contract

Status: design contract only. No Android source, APK, network client, or production workflow is changed by WORK 10-D.

## User supplied files

The first on-device adapter should accept only UTF-8 `.csv` and `.json` documents selected through Android Storage Access Framework (`ACTION_OPEN_DOCUMENT`, MIME filters `text/csv` and `application/json`). It must operate on the selected content URI using `ContentResolver`; do not turn a URI into a filesystem path. The file is read-only. The app must display the selected filename, declared source, import time, source as-of time, and a persistent “user-supplied, not independently verified” notice.

### JSON schema `navi-options-import/1.0.0`

```json
{
  "schema_version": "navi-options-import/1.0.0",
  "source": "user label, optional",
  "source_asof_timestamp": "ISO-8601 timestamp with offset, optional",
  "capture_timestamp_utc": "ISO-8601 timestamp with offset, optional",
  "session_date": "YYYY-MM-DD, optional",
  "contracts": [
    {
      "underlying_symbol": "SPY",
      "expiration": "YYYY-MM-DD",
      "strike": "500.00",
      "side": "CALL",
      "option_symbol": "source value, optional",
      "contract_identifier": "source value, optional",
      "root": "source value, optional",
      "volume": "10 or null, optional",
      "open_interest": "100 or null, optional",
      "bid": "1.00, optional",
      "ask": "1.10, optional",
      "last_price": "1.05, optional",
      "quote_timestamp": "ISO-8601 timestamp with offset, optional",
      "source_asof_timestamp": "ISO-8601 timestamp with offset, optional",
      "implied_volatility": "source value, optional",
      "delta": "source value, optional",
      "gamma": "source value, optional",
      "theta": "source value, optional",
      "vega": "source value, optional",
      "rho": "source value, optional",
      "contract_multiplier": "source value, optional"
    }
  ]
}
```

Unknown envelope or contract keys are rejected. Exactly one underlying is allowed per file. `side` accepts `CALL`/`C` and `PUT`/`P`. Expiration accepts ISO date, `MM/DD/YYYY`, or `YYYYMMDD`. A saved Nasdaq response is accepted only through the explicit Nasdaq payload adapter and its existing parser; no request is made.

### CSV schema `navi-options-import/1.0.0`

UTF-8 (optional UTF-8 BOM), header row with exact column names, one `schema_version` column, and one contract per row. Required columns: `schema_version,underlying_symbol,expiration,strike,side`. Optional columns use the same names and meanings as JSON contract fields. Every nonblank row must carry `schema_version=navi-options-import/1.0.0`. No alias guessing or universal CSV compatibility is promised.

## Limits and result contract

- Maximum input size: 10 MiB; maximum 100,000 contracts; maximum JSON nesting depth: 32.
- Strict UTF-8 decoding; no archive, workbook, URL, or directory import.
- Normalized schema remains `navi-options-chain/1.0.0`; every field retains source availability (`NOT_PROVIDED_BY_SOURCE`, `NULL`, `MISSING`, `EXPLICIT_ZERO`, `VALID_POSITIVE`, `VALID_SIGNED` for Greeks, `INVALID_NEGATIVE`, `INVALID_VALUE`). Signed Greeks are preserved because negative delta/theta/rho values can be valid.
- Snapshot envelope records import ID/time, source filename/type, source hash, schema versions, declared session date, source time, structural/freshness/research statuses, quality and error reports. Imported source bytes are not retained by this implementation.
- A local import timestamp is never substituted for source capture/as-of time. When original capture time is absent, freshness is `UNVERIFIED` (if source as-of exists) or `SOURCE_TIME_UNAVAILABLE` (if it does not).
- Error code examples: `UNSUPPORTED_FILE_FORMAT`, `FILE_SIZE_LIMIT_EXCEEDED`, `INVALID_ENCODING_UTF8_REQUIRED`, `MALFORMED_JSON`, `UNSUPPORTED_SCHEMA_VERSION`, `REQUIRED_COLUMNS_MISSING`, `REQUIRED_FIELD_MISSING`, `INVALID_EXPIRATION`, `INVALID_STRIKE`, `INVALID_CALL_PUT_SIDE`, `DUPLICATE_CONTRACT_KEY`, `MIXED_UNDERLYING_SYMBOLS_UNSUPPORTED`, `SNAPSHOT_OVERWRITE_BLOCKED`, and `INVALID_SCHEMA_VERSION`.
- Structural status: `VALID`, `PARTIAL`, `INVALID`. Freshness: `CURRENT_VERIFIED`, `RECENT_NOT_CURRENT`, `STALE`, `SOURCE_TIME_UNAVAILABLE`, `HTTP_FAILURE`, `UNVERIFIED`. Research usability: `PROVISIONAL_AVAILABLE`, `LIMITED`, `BLOCKED`.
- Analytics are observed-only and provisional. Missing-value denominators and percentages are shown. Volume/OI PCR is blocked if either side is absent or its observed call denominator is zero. Max Pain is blocked unless both sides exist, all OI values are valid, structural quality passes and a consistent source-provided contract multiplier is present. Even then, output is provisional and does not establish complete-market coverage.

## Android work still required

1. Implement SAF picker and stream-size enforcement before allocation; do not load a full file into a second in-memory copy.
2. Port or share the dependency-free parser/normalizer and decimal calculations, then verify parity against this Python implementation using the same labeled synthetic fixtures.
3. Use app-private storage with create-new semantics, independent import IDs, atomic writes and hash verification. Add explicit user-facing retention controls; do not upload snapshots.
4. Render missingness/freshness/provenance beside every metric, and allow drill-down by expiration, strike, and side.
5. Run Android unit/instrumented tests and measure memory on supported Galaxy devices in WORK 10-E. None of those checks are claimed as completed here.
