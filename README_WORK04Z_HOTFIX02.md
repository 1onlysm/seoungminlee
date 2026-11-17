# WORK 04-Z HOTFIX 02 — Chart Zoom/Pan Recovery

## Baseline and scope

- Source branch: `work04z-hotfix01-galaxy-ux-refinement`
- Verified source commit: `ff4fb741f894094490918f6ce41df4cef806018f`
- Source parent: `0fa3718f3e36e57ba6f7cbf34985e7acc57e00b1`
- Target branch: `work04z-hotfix02-chart-zoom-pan-recovery`
- Only the NVDA dashboard renderer, its offline tests, and this README are changed.

## Root cause

The previous slider converted its value to `visible_span = full_domain_span / zoom`. Its lowest ordinary value (`zoom = 1`) therefore exposed the entire actual strike domain, about `$0.50–$2,500`; on mobile the slider could travel from the `$140–$220` focus view toward that whole domain. Because the conversion is reciprocal, each slider increment near the low end expands the domain disproportionately. Full range was not separated from ordinary zoom.

Axis labels were selected by row-index stride. Since the strikes are nonuniform, that does not guarantee minimum screen-space spacing. The source X coordinate itself was a linear dollar-price mapping and remains so.

The `$189` card persisting through zoom and pan is expected: selection is independent from viewport range. The old shared range already drove Volume and OI together. The historical reference line already used the same range transform and was conditionally hidden outside the view.

## New viewport contract

- Mobile initial range remains `$140–$220`; the desktop baseline initial range remains unchanged.
- Ordinary maximum span is `min(full-domain span, max(initial span, min(4 × initial span, $320)))`. Thus mobile ordinary zoom-out is capped at `$320`; the desktop view does not expand past its existing initial span.
- The logarithmic slider uses levels 1–8; its minimum useful span is computed around the viewport center from five actual adjacent strikes. The mapping is stable for identical active expiration, center, and data.
- Pan is measured from the gesture's starting range, clamped to the actual data domain, and cannot change selection. Vertical touch movement remains available to page scrolling (`touch-action: pan-y`). Pointer cancel/lost capture clears gesture state.
- `전체 행사가` is a separate overview. It assigns all 444 actual strikes to `$50` price bins across the `$0.50–$2,500` domain. Tooltip ranges identify bins; null-only fields remain unobserved; each observed Volume/OI sum reconciles to the source rows. The slider is disabled in overview; `기본 보기` returns to individual strikes.
- Both charts share the same dollar-axis range and `VM.x` transformation. The historical `$156.14` reference remains `과거 참고가격`, appears only inside the visible domain, and is never clamped to a chart edge.
- Zoom/pan do not change the selected actual strike. The detail card reports when the selection is outside the viewport; recentering moves to that strike. Expiration changes restore that expiration's initial view and retain the selection only if it exists there; otherwise the nearest actual strike is selected.

## Integrity and tests

The raw snapshot remains unchanged at SHA-256 `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce`: 2,188 contracts, 444 strikes, 24 expirations, and original Volume/OI totals. Missing values remain missing; `EOD_UNVERIFIED`, `MISSINGNESS_CAUSE_UNKNOWN`, and `FULL_VOLUME_COMPLETENESS_UNVERIFIED` remain present.

The HOTFIX 01 baseline suite passed 28/28. The updated offline suite and actual JavaScript viewport helper tests are reported in `test_results.json`. Python compilation and JavaScript syntax are checked separately. Chromium rendering and Galaxy interaction must remain pending if the browser process is blocked by this environment.

## Safety

No market-data requests, Actions runs, provider additions, `main` changes, APK changes, or raw snapshot edits are made. No pinch-to-zoom support is claimed.

See `GALAXY_MANUAL_CHECKLIST.md` in the output bundle for device verification steps.
