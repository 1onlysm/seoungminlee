# WORK 04-U — NVDA real-data dashboard

This offline module builds a standalone NAVI OPTIONS LAB HTML dashboard and a PNG preview from the verified WORK 04-R NVDA snapshot and WORK 04-T strike aggregates. It checks the source SHA-256, contract count, all 444 strike rows, four aggregate totals, and all four TOP 5 lists before writing output.

```bash
python -m options_collector.nvda_dashboard \
  --contracts-csv /path/to/WORK04R/NVDA/contracts.csv \
  --strike-summary /path/to/WORK04T/nvda_strike_summary.json \
  --volume-csv /path/to/WORK04T/nvda_strike_volume.csv \
  --oi-csv /path/to/WORK04T/nvda_strike_oi.csv \
  --manifest /path/to/WORK04R/NVDA/manifest.json \
  --raw-json /path/to/WORK04R/NVDA/raw.json \
  --batch-summary /path/to/WORK04R/batch_summary.json \
  --output-dir /path/to/new-dashboard-output
```

The HTML embeds the verified dataset and uses no external scripts, fonts, APIs, or CDN resources. The PNG is rendered by Matplotlib from the same validated values. Opening the HTML in Chromium could not be verified in this environment because the browser policy blocked local `file:`/`data:` pages and the browser session could not reach the isolated loopback server; see `nvda_dashboard_validation.json` in the generated output.

All values are observed contract sums. Puts are drawn below zero only to distinguish the series. The data remains `PROVISIONAL`, with `EOD_UNVERIFIED`, `MISSINGNESS_CAUSE_UNKNOWN`, and `FULL_VOLUME_COMPLETENESS_UNVERIFIED` limitations. This dashboard does not claim support/resistance, trade direction, GEX, or a trading signal.
