# WORK 04-AC — Galaxy handoff checklist

The existing dashboard remains unchanged because no OHLC source passed the provenance and reuse gate. The offline artifact keeps HV unavailable; it contains no production HV values.

1. Open the standalone HTML in the Galaxy browser.
2. Confirm the volatility panel reports unavailable verified historical OHLC; no percentage placeholder appears.
3. Confirm IV, IV Rank, IV Percentile, and IV Skew remain unavailable.
4. Confirm the existing expiration selector, Volume/OI charts, strike selection, option chain, and provisional warnings remain present.
5. Confirm `$156.14` remains labeled as a historical reference, not current price.

No new HV rendering was added, and no Galaxy device test was performed in WORK 04-AC.
