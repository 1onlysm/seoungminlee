# WORK 04-Z — NVDA Price Reference Integration

## Price source audit

The preserved WORK 04-R Nasdaq options response contains `data.lastTrade`: `LAST TRADE: $156.14 (AS OF NOV 16, 2026)`. Its raw JSON SHA-256 matches the recorded digest. The response provides a date, not an intraday timestamp, and does not identify the value as a regular-session close. The snapshot manifest records collection at `2026-11-17T05:19:47.924836Z`; the option-chain timestamp and underlying quote time are absent. Therefore the value is classified as `HISTORICAL_REFERENCE_ONLY`, not a current/live quote, and its freshness and synchronization with the option chain are unverified.

No separate approved offline spot-price artifact or local price contract was present in the WORK 04-Y project files or the preserved WORK 04-R/T input set. No files were copied from another repository and no market data endpoint was called.

## UI behavior

- A compact top card labels `$156.14` as a historical reference, identifies its date and source, and shows its capture time separately.
- The gold dashed line in both strike charts uses the same strike-axis mapping. It is explicitly labelled as a historical reference; zooming and panning redraw it with the charts. When outside the visible range, the card says so.
- No strike-to-price distance or percentage is calculated because the price timestamp is date-only and the option chain has no verified data timestamp.
- No current price, regular close, IV, GEX, dealer position, or buy/sell inference is presented.
- If no valid reference exists, the card falls back to “NVDA 현재가 미확인” and no line is drawn.

## Data and tests

The original options JSON was not modified. Its SHA-256 remains `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce`. Offline verification retained 2,188 contracts, 444 strikes, 24 expirations and all four existing Volume/OI totals. The 24-test suite passed; Python compilation and the generated inline JavaScript syntax check passed.

Headless Chromium could not start in this execution environment: `socket() failed: Operation not permitted (1)` followed by a Chromium fatal process-singleton error. Browser layout, interaction rendering, and Galaxy device rendering are therefore unverified. No screenshot is claimed.

## Safety

- Live Nasdaq/Tiingo/other market requests: 0
- GitHub Actions runs: 0
- Main branch changes: 0
- New providers: 0
- Android APK changes: 0
