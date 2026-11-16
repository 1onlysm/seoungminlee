# WORK 04-C — 14-symbol options collector foundation

Experimental, non-operational foundation for the 14 previously API-verified symbols. Prior API access is historical evidence only. Current data remains `QUALITY_LIMITED` and `EOD_UNVERIFIED` unless future collection proves otherwise.

## Components

- `options_collector/registry.py`: explicit ETF/stocks registry and per-symbol expected root.
- `client.py`: Nasdaq URL/header contract, `build_opener(NoRedirect)`, default urllib proxy handling, timeout, one request per call, no retries or redirect following.
- `parser.py`: separates expiry headings from contract rows, retains raw row fields, counts rows, root classification and strike validation.
- `quality.py`: response digest, totalRecord comparison, roots, duplicates, strike validity, missing-value kinds, explicit zero counts, and separate API/data/freshness dimensions.
- `snapshot.py`: immutable daily/ET-date snapshots, atomic/fsync writes, read-back verification, identical-response deduplication, distinct response versions.
- `status.py`: indicator guard; no PCR, walls, Max Pain, GEX or trade signals are calculated.

Snapshot paths are `data/options/YYYY-MM-DD/SYMBOL/<collection-version>/` with `raw.json`, `contracts.csv`, `quality.json`, and `manifest.json`. The ET date denotes collection grouping only, not EOD confirmation. Manifest records both UTC and America/New_York collection timestamps. Neither timestamp proves an EOD snapshot.

Adjusted roots are classified separately and never silently merged into the expected standard root. Missing `null`, empty, `--`, and absent fields are preserved distinctly from explicit numeric zero.

## Workflow

`.github/workflows/options-14-experimental.yml` is separate from the existing SPY workflow, has no schedule, and is manual only. Default mode is offline. Live mode currently exits behind a deliberate gate pending separate review/authorization. No Actions run was performed. Non-default-branch `workflow_dispatch` availability is unverified. Prior Actions runs returning Nasdaq HTTP 403 remain a material access risk; no bypass or retry is designed.

## Evidence limits

`historical_evidence.json` records only the user-supplied historical symbol-level success summary. It contains no reconstructed raw responses, current snapshots, or EOD claims.
