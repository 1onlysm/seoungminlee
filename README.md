# SPY Nasdaq options EOD collector — experimental

Independent experimental collector in this repository. No NAVI canonical files, Android source, or APK workflows were modified.

GitHub Actions: `.github/workflows/spy-options-eod.yml` (weekdays 17:17 America/New_York; UTC/DST guard). Manual runs outside that hour skip collection.

Outputs: `summary.json` and `contracts.csv` in an Actions artifact retained for 30 days. This is a **public repository**: do not store proprietary or confidential data here. Raw Nasdaq response is **not** uploaded. Do not assume market-data redistribution is licensed.

The collector rejects intraday/stale quotes and malformed chains. Nasdaq post-close API access, data semantics, and GitHub runner execution are not yet validated. `approved_for_navi` is always false. No permanent historical archive is implemented.
