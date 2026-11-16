# WORK 04-D — Real response compatibility and missingness forensics

## Baseline and scope

- Repository: `1onlysm/seoungminlee`
- Baseline branch/commit: `work04c-fourteen-symbol-collector` / `47c7f0c883c62eedf4d04c4e12370fbbe379fd88`
- Target: `work04d-real-response-quality-audit`
- This branch contains offline parser/quality changes, tests, and derived audit summaries only. It does not include the preserved raw JSON files.

## What the preserved responses showed

Six original responses were available in the WORK 04-B HF02/HF03 execution directories: MSTR, PLTR, MU, CRWV, COIN, and MARA. Each JSON parsed, reported `rCode=200`, and its SHA-256 and byte count matched both prior execution evidence and its manifest. The source paths and digest checks are in `audit_reports/raw_evidence_inventory.csv`; the readable findings are in `audit_reports/real_response_audit.md`. The complete replay JSON with full expiration/strike distributions is an offline companion artifact and is not committed; original response files are not in the repository.

The raw response shape differs from the assumptions in WORK 04-C:

- `totalRecord` is at `data.totalRecord` and counts every `data.table.rows` entry, including expiry headings.
- Expiry headings use `expirygroup`; option rows use `strike` and a short `expiryDate`.
- Call/put metrics are paired as `c_*` and `p_*` fields.
- Contract roots are encoded in lowercase `drillDownURL` route slugs, e.g. a root plus the padded OCC date/side/strike slug.

The old parser read `strikePrice`, treated contract `expiryDate` values as headings, missed the actual heading field, looked for `table.totalRecord`, and did not recognize lowercase route roots. The six actual responses therefore appeared inverted: the old parser's contract count equaled the expiry-header count, while its expiry count equaled the actual contract count. The new parser separates header rows from strike rows and validates `data.totalRecord` against raw table rows.

## Missingness and interpretation

Contract rows preserved positive numbers, numeric zero, `--`, empty strings, JSON nulls, absent fields, and invalid numeric strings as separate categories. Across these six actual responses, contract rows contained positive numeric values and `--`; explicit zero, JSON null, empty, absent, and invalid values were all zero. Nulls in expiry-heading rows are structural and are excluded from contract denominators. `--` is retained as a placeholder string and is never coerced to zero. Its exact vendor meaning remains unverified.

Calls had higher observation rates than puts for volume and OI in all six files. Far-from-spot strikes had lower volume observation than the ATM-near group for all six; far-term volume observation was lower than near-term in five of six. These are associations in one snapshot per symbol, not evidence that inactivity causes `--` or a stable market rule. Full per-expiration, per-strike, horizon, moneyness, and call/put statistics are included in the audit JSON.

ATM-near uses the response's underlying `lastTrade` only when its stated quote timestamp is within five minutes of the preserved request-intent time. It is never used as an option-chain freshness timestamp. All six `data.table.asOf` values are absent/null, so every chain remains `EOD_UNVERIFIED` and derived indicators remain blocked.

## Offline replay and regression

The real replay tool reads only the prior files and writes snapshots to a separate output directory. It does not import or call the HTTP client.

```bash
python -m unittest discover -s tests -v
python tools/real_response_audit.py --output /workspace/scratch/navi-options-work04d-replay-final
```

The unit suite uses synthetic fixtures separately from the six real response replays. It validates the real Nasdaq row shape, seven missingness categories, raw token retention, count/expiry parsing, root classification, distributions, ATM gating, snapshot round trips, EOD gating, and that offline quality processing makes no network call.

Quality gates remain multidimensional: parser integrity, snapshot integrity, per-field observation rates, distributions, and freshness are separate. This audit proposes no universal observation-rate threshold from one snapshot date. No PCR, Max Pain, call/put walls, GEX, or trading signal is calculated or approved.
