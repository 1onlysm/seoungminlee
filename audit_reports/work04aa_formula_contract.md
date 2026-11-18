# Volatility formula and readiness contract

## Readiness states

Report these separately for every metric:

- `FORMULA_SPECIFIED`: the mathematical target is written down.
- `DATA_READY`: all observations, provenance, timestamps, conventions, and required inputs are verified.
- `IMPLEMENTATION_READY`: code has been implemented and tested against the frozen contract.
- `PRODUCTION_DISPLAY_READY`: the metric's data freshness, calculation, missingness, and UI limitations are all validated.

A formula alone never implies any of the latter three states.

## Per-contract implied volatility

Define implied volatility as a nonnegative volatility parameter `sigma` solving:

`contract_appropriate_model_price(S, K, T, r, q, sigma, exercise_style) = validated_observed_option_price`

This is a generic inverse-pricing definition, not an instruction to use Black–Scholes. The source must establish option price quality and time, synchronized underlying price and time, expiration instant, rates, dividends, exercise style/model, arbitrage bounds, and numerical convergence. Those requirements are not met in the preserved snapshot. Production IV remains blocked.

## IV Rank

`IV Rank = (current IV - historical minimum IV) / (historical maximum IV - historical minimum IV) × 100`

The current IV and historical series must use a comparable, frozen tenor/maturity methodology and declared lookback. If historical maximum equals minimum, the result is undefined and unavailable. No historical IV series exists.

## IV Percentile

`IV Percentile = count(historical IV < current IV) / count(valid historical IV) × 100`

Tie policy: strict less-than; equal observations are not counted below current IV. The historical series, frequency, lookback, minimum sample, and methodology must be declared and consistent. No such series exists.

## Historical volatility

For close-to-close log returns:

`r_t = ln(C_t / C_(t-1))`

`HV_N = sample_stddev(r over N consecutive returns) × sqrt(252)`

`252` is a conventional annualization assumption, not a measured property of this snapshot. Require `N+1` positive, provenance-verified closes and every expected trading session under the declared calendar. Do not bridge missing sessions. Candidate windows are HV10/20/30/60; no verified NVDA OHLC history is available, so none is calculated.

## Intraday realized volatility

Intraday RV must use a declared sampling cadence, session boundary, overnight treatment, missing-observation policy, and appropriate annualization. It is distinct from close-to-close HV. No intraday underlying series is available.

## Skew and term structure

No skew metric is frozen. A later contract must choose strike-based or delta-based skew, ATM/moneyness selection, same-expiration alignment, and quote/coverage policy using verified contract IV. Term structure similarly requires a consistent expiration-level IV summary and comparable-tenor methodology. Volume imbalance or OI concentration cannot substitute for IV.

## Observation semantics

`null`, empty strings, and `--` mean unobserved. Explicit numeric `0` is an observed zero. Never convert missing option fields to zero. Preserve `PROVISIONAL`, `EOD_UNVERIFIED`, `MISSINGNESS_CAUSE_UNKNOWN`, and `FULL_VOLUME_COMPLETENESS_UNVERIFIED`.
