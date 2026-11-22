# WORK 10-F — Nasdaq access, import contract, and analytics

## Audit boundary

No live Nasdaq, Tiingo, or other market-data requests were made. The checked-in fixture `tests/fixtures/nasdaq_cloud_options_chain_TEST_ONLY.json` is synthetic and is not market evidence. No user's Nasdaq account, subscription, exchange agreement, or retention rights were available for inspection. Permission status: `NASDAQ_ACQUISITION_PERMISSION_UNVERIFIED`.

Nasdaq Cloud Data Service documentation describes an authenticated options-chain endpoint and response fields. That does not establish this user's entitlement or permission to retain and analyze responses. The public Nasdaq SPY option-chain page is a separate surface; its visibility does not prove a permitted download or storage path. Until the specific account entitlement and permitted usage scope are evidenced, direct download stays disabled and manual import accepts only files the user is authorized to obtain, retain, and analyze.

### Permission-request checklist (not sent)

Ask Nasdaq or the account administrator to confirm, in writing:

1. Product and account entitlement for SPY options chains, and whether the feed is real-time or delayed.
2. Permitted acquisition mechanism and environments, including a personal Android application.
3. Whether local parsing and personal research are permitted.
4. Whether the user may retain raw files, normalized contracts, derived statistics, and historical snapshots; include the permitted retention period.
5. Whether an exported file may be imported into NAVI TECH NEXT and remain on-device.
6. Redistribution, backup, cloud-sync, and deletion requirements.
7. Applicable exchange agreements, user classifications, API key restrictions, and rate limits.

No credentials, cookies, request headers, or secrets are included in snapshots.

## Documented adapters

The importer supports only these explicit shapes:

- `navi-options-import/1.0.0` normalized CSV and JSON, with exact required contract keys and optional documented keys.
- Existing saved Nasdaq option-chain JSON shape handled by the WORK 10-D adapter.
- Nasdaq Cloud Data Service options-chain JSON response as a top-level array or an object with a `data` array. Contract keys are `identifier`, `symbol`, `expiration`, `strikePrice`, `optionType`, and optional `lastPrice`, `volume`, `askPrice`, `askSize`, `bidPrice`, `bidSize`, `openInterest`.

The Cloud Data Service adapter does not infer source-as-of, capture time, quote timestamps, contract multiplier, IV, Greeks, or underlying reference price when absent. An `identifier` may be retained as the supplied symbol/identifier but is not used to invent missing contract fields. Unsupported extra keys are rejected for schema-drift visibility. This adapter defines file compatibility, not a live endpoint client or user entitlement.

CSV support is schema-specific, not universal. CSV must carry `schema_version` and the normalized column names. JSON formats are not interchangeable unless they match one of the shapes above.

## Quality semantics and analytics

Availability states remain separate: source-not-provided, missing, null, explicit zero, valid positive, invalid negative, or invalid value. Null and absent records remain in coverage denominators; negative Volume/OI are excluded from observed sums and count as invalid. No missing-to-zero substitution occurs.

PCRs are observed-only and provisional. They require eligible Call and Put records, at least one valid observation on each side, and a positive Call denominator. Reports retain per-side eligible counts, valid counts, missing/null/zero/invalid counts, coverage, observed totals, and the gate reason. Per-expiration and selected strike-range PCRs use the same policy.

Call/Put wall candidates and top-volume strikes are observed concentrations, not dealer positions, direction, or support/resistance. Max Pain is blocked unless an eligible future expiration, both sides, complete nonnegative OI, consistent positive source multipliers, and sufficient strikes are available. No default multiplier is assumed.

Snapshot comparison is blocked unless retention is explicitly permitted, provider/endpoint/symbol/schema and contract universe match, source timestamps exist, and required comparable fields are present. Import time never substitutes for market-data time.

## Storage and provenance

The existing on-device append-only store remains the storage mechanism. Each import is independently identified and integrity checked. Raw source bytes are not retained in snapshots by default. The app does not upload snapshots. Users must confirm their source's retention restrictions before keeping data; the comparison engine defaults to blocked absent retention permission.

## Bounded future pilot (not authorized or executed)

If entitlement, retention, environment, schema, and user approvals are established, a separate authorization may permit one SPY request, zero retries, and no automatic polling. The request must identify the approved Nasdaq product/endpoint and approved execution environment, and preserve the exact response and source timestamps only if retention is permitted. Any 401/403 or other failure stops the pilot; no retries, proxy, or access-control workaround. A future pilot request must be separately authorized after preflight.
