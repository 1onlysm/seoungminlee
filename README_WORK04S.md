# WORK 04-S — Manual provisional refresh

The refresh is manual only. It reuses `options_collector.live_provisional`, including its fixed 14-symbol registry order, single request per symbol, zero retries, raw snapshot writer, and provisional analytics pipeline. It does not add a scheduler or workflow.

From the repository root, start one explicitly confirmed run with:

```bash
python -m options_collector.manual_refresh \
  --mode live \
  --confirm-live \
  --output-root /workspace/scratch/navi-options-manual-refresh
```

The command creates a unique run-ID directory under the output root. It does not overwrite existing run directories. Completion output lists successful and failed symbols and the run, raw snapshot, manifest, analytics JSON, and analytics CSV paths. The durable batch summary and execution manifest remain in that run directory.

`--help` is offline. Omitting `--confirm-live` exits before the live runner is called. The command is intentionally not invoked during WORK 04-S.

Analytics remain `PROVISIONAL`, with `EOD_UNVERIFIED`, `MISSINGNESS_CAUSE_UNKNOWN`, and `FULL_VOLUME_COMPLETENESS_UNVERIFIED` limitations. Observed PCR is not a confirmed full-market measure.
