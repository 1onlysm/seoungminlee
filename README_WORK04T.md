# WORK 04-T — NVDA strike flow map

This is an offline-only analysis of the preserved WORK 04-R NVDA `contracts.csv` and `manifest.json`. It groups all expirations by strike, sums only numeric observed Volume/OI values, keeps missing-only sums as JSON `null`, and records explicit observed zero separately through the observed counts. It does not make network requests.

Example:

```bash
python -m options_collector.nvda_strike_map \
  --contracts-csv /path/to/NVDA/contracts.csv \
  --manifest /path/to/NVDA/manifest.json \
  --output-dir /workspace/scratch/navi-options-work04t-output
```

The output directory must be new or empty. The module writes strike-level Volume and OI CSVs, a JSON summary with all strikes and four TOP 5 rankings, and two PNG charts. Matplotlib is needed for PNG generation.

All results are marked `PROVISIONAL`; the source snapshot is `EOD_UNVERIFIED`, missingness cause is unknown, and full Volume completeness is unverified. Strike concentration is descriptive only: it is not a directional signal, a confirmed support/resistance level, dealer positioning, or GEX.
