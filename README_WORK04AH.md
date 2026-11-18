# WORK 04-AH — Tiingo EOD bridge gate

**Primary verdict: `TIINGO_EXPORT_OR_RIGHTS_BLOCKED`.** No Tiingo market-data request was made, no Galaxy device was operated, and no OHLCV or HV value was imported or generated.

## Frozen OPTIONS LAB baseline

- Repository: `1onlysm/seoungminlee`
- Source branch: `work04af-provisional-hv-research-lane`
- Verified HEAD: `695d531b78188cb39299dad0c76ecbfb0954af01`
- Parent: `adf1e4c5699388e4787bdcc5223ec4879ab7d4db`
- Target branch: `work04ah-galaxy-tiingo-nvda-bridge`, created from that exact source commit.
- The target changes only this readiness report and its machine-readable audit. The dashboard, options collector, raw options data, and production branches are untouched.
- The source worktree had no preserved raw NVDA options JSON in the tracked files. Prior committed audit reports record the protected raw hash and totals; this work did not independently rehash absent raw bytes.

Baseline offline command: `python -m unittest discover -s tests` — **122 passed, 0 failed**. This is the existing suite result, not a test of a new bridge.

## TECH NEXT source and auth audit

Read-only source examined at `1onlysm/navi-android-apk-build`:

- Latest relevant implementation branch: `work07c-hotfix01-provisional-registration`, HEAD `ad5004f0d048d00ae92531c95e71a1d51a7851d1`.
- Last Galaxy-confirmed reference supplied by the project: `work06ui-refinement04-safe-polish`, commit `c928a23d1f270e4545bf69e52dbd6630769517d2`. This is older than 07-C and is not assumed to be the installed app.
- The 07-C development package is `com.navi.s6.work07chf01`; the Galaxy-confirmed package is `com.navi.s6.work06uirefine04`. Android package-private credentials do not transfer between them; a development build would need the user to reauthenticate through its existing token UI.
- Existing Tiingo adapter supports NVDA. It uses the official EOD prices route and reads the token from the existing encrypted Android token store only after the existing personal-use acknowledgment. No token value was accessed, printed, or copied.
- The inspected code's `requestTechNextSymbol` calls the EOD price endpoint and then a separate split-coverage endpoint. That flow exceeds this pilot's one-request limit. A lower-level one-request `fetchPrices` method exists, but the current WORK 07-C page does not expose a completed HV-only callback for it.
- No existing raw OHLCV export is available. The checked-in `test_audit_export.js` explicitly asserts that the audit export bridge, Android document export, and browser persistence are absent.

## Rights and consent gate

The app's existing acknowledgement is personal/internal analysis and no saving or sharing of raw quotes. It does not authorize exporting raw OHLCV to another project. No export feature was enabled.

The current Tiingo terms distinguish Starter/Trial from eligible paid plans: Starter/Trial data and derived outputs may be processed transiently for the operation and must be removed before the session ends; paid-plan retention is plan-specific. A derived product may be retained/distributed only if it is not a substitute for Tiingo data and cannot reasonably be used to reconstruct it. Raw-data redistribution requires separate permission. The account plan, account entitlement, and any supplemental agreement are not visible from this work environment, so persistence or transfer rights are **UNKNOWN**. See [Tiingo Terms §1.6](https://www.tiingo.com/tos/) and [EOD field/adjustment documentation](https://www.tiingo.com/documentation/end-of-day).

Tiingo documents `adjClose` as adjusted and states that its adjustment method incorporates both splits and dividends. That field could support a clearly labeled adjusted-close return calculation if used transiently on-device, but it is not raw price volatility and must be labeled with its adjustment semantics. No actual response was obtained in this work.

### Route decision

| Route | Decision | Reason |
|---|---|---|
| Export raw OHLCV from Galaxy to OPTIONS LAB | Blocked | Existing app acknowledgement prohibits raw-data save/share; provider/account export rights are not verified. |
| Import data into OPTIONS LAB | Not implemented | No permitted export artifact exists. |
| Transient on-device HV display | Technically plausible, not implemented | Would need a one-EOD-request native path, an in-memory calculation/view, explicit session cleanup, focused tests, and an isolated Android build. Current environment has no Android SDK/Gradle/Kotlin compiler and cannot operate the Galaxy device. |
| Persistent/shareable HV output | Blocked pending plan/rights | Current account plan and derived-output permission are unknown. |

The prior Yahoo/Naver candidate was not used or re-audited.

## Data and safety

- LIVE market-data requests by this WORK: **0**
- Galaxy NVDA requests: **0**
- GitHub Actions runs: **0**
- Main changes: **0**
- New providers: **0**
- APK changes/builds: **0**
- Raw options snapshot changes: **0**
- HV10/HV20/HV30/HV60: **not calculated**
- IV status: unchanged; still unavailable

The prior options audit records the protected snapshot SHA-256 as `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce` and the expected 2,188 / 444 / 24 counts and aggregate totals. Since the raw bytes are not in this worktree, this report does not claim a fresh hash recomputation.

## Next step

Do not export the token or raw prices. If you want the fallback route, the next implementation should be a separate TECH NEXT development branch that reuses the existing token gate, makes one explicit EOD request, calculates HV from `adjClose` entirely in memory, clears the result at session end, and displays it only on-device. A development package will require reauthentication. Build and test that isolated APK before the user initiates the one Galaxy request. Obtain Tiingo confirmation before persisting or transferring any derived output.
