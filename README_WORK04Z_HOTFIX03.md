# NAVI OPTIONS LAB — WORK 04-Z HOTFIX 03

## Baseline and scope

- Frozen source: `work04z-hotfix02-chart-zoom-pan-recovery`
- Verified source HEAD: `3bd891b630112eae11f1886c2e6efc8ca31f3bc1`
- Target: `work04z-hotfix03-volatility-integrity`
- Changed implementation scope: NVDA dashboard, its offline tests, and this audit/handoff README.
- No live requests, Actions, provider changes, APK work, or raw snapshot edits.

## Volatility data audit

The preserved NVDA response SHA-256 is `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce` (2,188 contracts, 444 strikes, 24 expirations). No implied-volatility, historical-volatility, Delta, Gamma, Theta, Vega, or Rho field is present in the raw option rows. The response has Bid, Ask, Last, Change, Volume, Open Interest, Strike, and expiration fields. `data.lastTrade` contains `$156.14 as of 2026-11-16`; this remains a date-only historical reference, not a synchronized spot quote.

No verified underlying OHLC history or historical IV series is available in the preserved WORK 04-R input set. IV calculation is blocked: option quote timestamps and synchronized underlying price are absent, while rate, dividend, and American-exercise model assumptions are not validated. IV Rank, IV Percentile, IV Skew, and HV/RV therefore remain unavailable. The dashboard adds a compact, collapsed volatility status panel without invented numeric values.

## Bid/Ask integrity

For `2026-11-18`, `$160`, the raw row contains Call Bid `4.95`, Call Ask `4.85`, Put Bid `8.60`, Put Ask `8.65`. The normalized CSV preserves those exact values in `raw_row_json`; the mapping is `c_Bid → call_bid`, `c_Ask → call_ask`, `p_Bid → put_bid`, and `p_Ask → put_ask`. The renderer uses those same respective fields. This confirms `RAW_CROSSED_QUOTE`, not a parser or display swap. Per-option quote timestamps are absent, so timestamp mismatch is not established. Values are not changed; expanding a contract with Bid > Ask displays a warning that the original quote is preserved and is not guaranteed to be executable.

Across 2,188 contracts, 18 call pairs and 5 put pairs have Bid > Ask among pairs where both values are numeric. No negative or zero Bid/Ask values were observed. Missing quotes remain missing.

## Chart zoom/pan regression

HOTFIX 02 viewport behavior is retained without changes: mobile starts at `$140–$220`, ordinary zoom-out is capped separately from the explicit full-range overview, full-range binning preserves source totals, pan is domain-clamped, Volume/OI share the same strike axis, and the `$156.14` line stays labeled `과거 참고가격` and is hidden outside the visible range. Its offline regression tests were rerun as part of the full suite.

## UI changes

- Added a collapsed `변동성 분석 · 데이터 상태` panel explaining the unavailable inputs; no IV/HV/Greeks values are fabricated.
- Added an expanded-contract warning for raw Bid > Ask. Bid/Ask values are unchanged.
- Major observed strike-card values use thousands separators while mixed textual Call/Put summaries remain intact.
- Preserved option sums, expiration data, selection, coverage, EOD and missingness warnings.

## Verification

- HOTFIX 02 baseline: 33/33 offline tests passed before changes.
- HOTFIX 03: 37/37 offline tests passed, including actual JavaScript viewport math and quote-warning logic under Node.
- Python compile and JavaScript syntax check passed.
- Chromium headless could not launch in this environment (`socket() failed: Operation not permitted`; crashpad ptrace also prohibited). Browser rendering is unverified; Galaxy device verification is pending.

## Reproducible offline build

Run from the repository root with the preserved WORK 04-R contracts CSV, WORK 04-T aggregation CSV/JSON, manifest, raw JSON, and batch summary. Invoke `python -m options_collector.nvda_dashboard` with the seven required input paths and a new `--output-dir`; do not reuse an existing output directory. Example paths and the rendered standalone HTML are included in the accompanying audit bundle. No API is called by this command.

## Galaxy checklist

See the accompanying `GALAXY_CHECKLIST_WORK04Z_HOTFIX03.md` for the device steps.
