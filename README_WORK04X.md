# WORK 04-X — NVDA expiration filter and observed options chain

This is an offline extension of the WORK 04-W dashboard. It embeds the verified WORK 04-R NVDA snapshot and performs no network requests.

## Expiration filter

The selector is generated from the 24 normalized expiration dates in the preserved contracts CSV. **All Expirations** is the default. Selecting a date rebuilds the volume/OI sums, coverage, observed ratios, donuts, strike maps, TOP 5, key strikes, selected-strike values, interpretation text, and options-chain rows from that expiration’s real contracts. All-expiration data keeps the existing mobile $140–$220 initial range. Individual expirations use that range only when at least four observed strikes fall within it; otherwise the chart opens on that expiration’s actual strike extent.

The chain table includes strike, call/put Volume and OI, and Call/Put Bid/Ask. The source table headers label Bid and Ask. Implied Volatility is omitted because no IV field or header exists in the raw response. A dash or absent value is displayed as **Not observed**; numeric zero remains `0`.

## Evidence and limitations

- Raw SHA-256: `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce`
- Raw `totalRecord` and raw table rows: 2,212 each, consisting of 2,188 paired contract rows and 24 expiration header rows.
- The four all-expiration observed Volume/OI sums reconcile to WORK 04-W. Expiration-group sums are checked against those same totals.
- `EOD_UNVERIFIED`, `MISSINGNESS_CAUSE_UNKNOWN`, and `FULL_VOLUME_COMPLETENESS_UNVERIFIED` remain in force. This is an offline historical snapshot, not real-time data.

## Build and tests

```bash
python -m unittest discover -s tests -v
python -m options_collector.nvda_dashboard \
  --contracts-csv <WORK04-R-NVDA-contracts.csv> \
  --strike-summary <WORK04-T-summary.json> \
  --volume-csv <WORK04-T-volume.csv> \
  --oi-csv <WORK04-T-oi.csv> \
  --manifest <WORK04-R-manifest.json> \
  --raw-json <WORK04-R-raw.json> \
  --batch-summary <WORK04-R-batch-summary.json> \
  --output-dir <new-output-directory> \
  --no-png
```

Output is a standalone HTML file plus JSON data, validation, expiration aggregation, and raw-field audit files. A separate browser render and Galaxy device check remain pending where the local Chromium runtime is unavailable.
