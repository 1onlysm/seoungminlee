Warning: truncated output (original token count: 1983)
Total output lines: 100

# NAVI OPTIONS LAB — WORK 04-AA

## Verdict

**`VOLATILITY_CONTRACT_READY_DATA_BLOCKED`**

The preserved NVDA option snapshot is authentic and its existing dashboard totals remain reproducible. The available files do not support a verified production IV, IV Rank, IV Percentile, IV Skew, term structure, HV/RV, or intraday realized-volatility value. This work freezes the required input and methodology contracts and tests the existing unavailable-state behavior; it deliberately adds no volatility number or calculator.

## Baseline and scope

- Repository: `1onlysm/seoungminlee`
- Reference branch: `work04z-hotfix04-galaxy-ui-final-polish`
- Verified reference commit: `bc60c2078b1d4b536efb9c94feacf67482ac67d1`
- Target branch: `work04aa-verified-volatility-contract`
- The target branch was created from the verified reference commit. No dashboard aggregation, source snapshot, provider, collection path, or existing UI was changed.
- Baseline offline tests: **90 passed** before changes.

## Snapshot provenance and integrity

The preserved WORK 04-R NVDA response used for the audit is at:

`/workspace/scratch/navi-options-work04r-live/naviopt04r-20261117T051903Z-80a05c75/snapshots/data/options/2026-11-17/NVDA/2026-11-17T05-19-47.924836Z/raw.json`

- SHA-256: `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce`
- Bytes: `883552`
- Manifest capture time: `2026-11-17T05:19:47.924836Z` (`2026-11-17T00:19:47.924836-05:00`)
- Normalized contracts: 2,188
- Unique strikes: 444
- Expirations: 24
- Observed Call / Put Volume: 1,457,430 / 953,110
- Observed Call / Put OI: 9,839,124 / 8,636,754

The original response contains 2,212 table rows, including 24 expiration-group headings; it is not equivalent to the 2,188 normalized contract rows. The existing dashboard loader and source regression checks reconcile these representations. `data.lastTrade` is the date-only text `LAST TRADE: $156.14 (AS OF NOV 16, 2026)`. It remains a historical reference and is not synchronized…983 tokens truncated…ementation

No production volatility calculation was implemented because no indicator passed its input audit. Added artifacts freeze the source inventory, readiness matrix, and formula/missingness contract. New offline tests verify the raw digest and data contract, the absence of IV and quote timestamps, distinct missing-versus-zero treatment, and that the contract does not mark blocked metrics as production-calculable.

The existing dashboard volatility panel already reports the unavailable states. It was not changed.

## Reproduction

Run from the repository root:

```bash
python -m unittest discover -s tests -v
python -m py_compile options_collector/nvda_dashboard.py options_collector/nvda_strike_map.py tests/test_volatility_readiness.py
```

To regenerate the existing standalone dashboard from the preserved WORK 04-R and WORK 04-T artifacts, use the seven evidence inputs documented in `README_WORK04Z_HOTFIX03.md`, but choose a new output directory. This uses local files only. No live request is made.

## Browser and Galaxy status

`BROWSER_RENDER_UNVERIFIED`. Chromium UI automation could not attach because the environment's AT-SPI provider was unavailable. A normal headless Chromium launch also stopped with `socket() failed: Operation not permitted` and `ptrace: Operation not permitted`; sandbox protections were not relaxed. The dashboard source was unchanged, so there is no new browser or Galaxy interaction validation. The offline test run verifies source-derived status values, not rendering. A standalone HTML was generated at `/workspace/scratch/navi-options-work04aa-output/nvda_options_dashboard.html`. Use `audit_reports/work04aa_galaxy_checklist.md` for manual device review.

## Safety

- Nasdaq / Tiingo / other market-data API requests: **0**
- GitHub Actions runs or workflow changes: **0**
- `main` changes: **0**
- New providers: **0**
- NAVI TECH NEXT / APK changes: **0**
- Existing snapshot replacements: **0**
- Fabricated volatility observations: **0**
