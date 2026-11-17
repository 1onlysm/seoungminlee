# NAVI OPTIONS LAB — WORK 04-Z HOTFIX 01

## Baseline

- Frozen source: `work04z-nvda-spot-price-integration`
- Full source SHA: `0fa3718f3e36e57ba6f7cbf34985e7acc57e00b1`
- Target branch: `work04z-hotfix01-galaxy-ux-refinement`
- Changes are limited to the NVDA dashboard, its offline tests, and this handoff note.

## Coverage formula audit

Coverage is calculated independently for each normalized field as:

`numeric observations for field / eligible normalized expiration×strike rows × 100`

For expiration `2026-11-18`, the eligible population is 90 normalized expiration/strike rows:

| Field | Raw API field | Observed | Eligible rows | Coverage |
|---|---|---:|---:|---:|
| Call Volume | `c_Volume` | 85 | 90 | 94.44% |
| Put Volume | `p_Volume` | 73 | 90 | 81.11% |
| Call OI | `c_Openinterest` | 85 | 90 | 94.44% |
| Put OI | `p_Openinterest` | 73 | 90 | 81.11% |

The matching percentages are correct. Equal percentages only mean equal observation counts; they do not mean that missing strikes are identical. For the same expiration, Call Volume and Call OI have different missing strike sets; Put Volume and Put OI also differ. All-expiration coverage uses the separate 2,188-row population and is 73.58%, 59.10%, 93.64%, and 72.44%, respectively. Numerators, denominators, and missing-field distributions are recorded in the generated coverage audit JSON.

## UX changes

- Added `참고가격 부근`, `선택 행사가`, and `처음으로` controls above the options chain.
- The reference-price control navigates to the nearest actual strike in the active expiration, only when the historical price-reference contract is valid. It does not alter expiration or present the price as live.
- Chart and chain selection continue to share the existing selected-strike state. The selected-strike navigation control is disabled when that strike is absent from the active expiration.
- Coverage cards now show observed numerator / eligible row denominator as well as the percentage.
- Translated `Center selected strike` to `선택 행사가로 이동`; tightened mobile navigation controls and numeric alignment.
- Existing TOP 5 formatting already uses grouped thousands. It is preserved.

## Data and safety

- Raw SHA-256 remains `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce`.
- Contracts: 2,188; strikes: 444; expirations: 24.
- Volume/OI totals and missing-value semantics are unchanged.
- `$156.14` remains `과거 참고가격` from `data.lastTrade`, dated 2026-11-16. It is not a live price or verified regular-session close.
- `EOD_UNVERIFIED`, `MISSINGNESS_CAUSE_UNKNOWN`, and `FULL_VOLUME_COMPLETENESS_UNVERIFIED` remain in the dashboard.
- No live market requests, GitHub Actions, provider additions, main changes, APK changes, or raw snapshot changes were made.

## Verification and Galaxy handoff

The baseline offline suite passed 24/24 tests; after the hotfix, 28/28 tests passed. Python compilation and the extracted dashboard JavaScript syntax check passed. Chromium was present but could not launch: `FATAL ... socket() failed: Operation not permitted (1)` and `ptrace: Operation not permitted (1)`. Therefore the generated HTML has not been visually verified in a browser in this environment, and the new behavior remains pending confirmation on the user's Galaxy device.

Use the generated standalone HTML and follow `GALAXY_MANUAL_CHECKLIST.md` in the output bundle.
