# TV Market Identity Prototype v0.3.34



## v0.3.34 — exact reviewed Yahoo YHD venue artifact

UK full-market validation
-------------------------
TradingView rows: 3793
VERIFIED: 3792
REJECTED: 1
Coverage: 99.974%

Expected rejection:
LSE:CAGP — TradingView preferred vs Yahoo BOND

Warm-cache validation:
CACHE_HIT: 3793
cache_misses: 0
Yahoo quote refresh preserved

The four reviewed Yahoo `MUTUALFUND` taxonomy overrides now also tolerate one exact synthetic Yahoo venue tuple observed live for all four rows: `exchange=YHD`, `fullExchangeName=YHD`, `market=us_market`. This is **not** added to generic London venue compatibility. It is accepted only when the row is already in the exact reviewed registry, independent OpenFIGI identity is present, mapping is not target-provider-only, ticker/MIC/kind/name guards pass, Yahoo returns the exact bounded symbol, and any reported currency is compatible. Any other `YHD`, market, venue, type, symbol, or currency combination remains fail-closed.

Warm-cache refresh mirrors the same exact reviewed tuple so a cold-path binding is not immediately invalidated. Telemetry adds `reviewed_yahoo_mutualfund_yhd_venue_matches`. Resolver policy: `0.3.34-policy34`; existing bindings are revalidated automatically.

## v0.3.33 — reviewed Yahoo venue-observation diagnostics

The four exact reviewed `MUTUALFUND` candidates now expose the actual Yahoo `exchange`, `fullExchangeName`, and `market` values in bounded resolver telemetry whenever a reviewed candidate remains blocked. This release does **not** broaden admission or reinterpret a venue mismatch. It exists to distinguish a harmless Yahoo venue-code anomaly from a genuine explicit venue conflict before any policy change.

Telemetry keys are bounded to the four reviewed identities and normalized, for example `reviewed_yahoo_mutualfund_venue_LSE_KAKU_exchange_<VALUE>`, `..._full_exchange_<VALUE>`, and `..._market_<VALUE>`. Resolver policy: `0.3.33-policy33`; existing bindings are revalidated automatically.

## v0.3.32 — reviewed MUTUALFUND missing-currency alignment

The v0.3.31 UK-wide diagnostic isolated all four reviewed Yahoo `MUTUALFUND` candidates (`LSIN:BKM`, `LSIN:EFGD`, `LSE:KAKU`, `LSE:TGE`) to the same single guard: Yahoo returned the exact reviewed symbol/type/venue evidence but omitted `currency`. No OpenFIGI, mapping-strength, kind, MIC, issuer-name, or venue guard failed.

This release removes only that accidental over-constraint. For the exact reviewed taxonomy registry, missing Yahoo currency is now treated the same way as every ordinary OpenFIGI-backed non-US identity: **absence is not a contradiction**. If Yahoo reports a currency, it must still match TradingView (`GBX <-> GBp` remains the reviewed penny-unit equivalence); an explicitly conflicting currency is still rejected. Yahoo-only strict mappings remain excluded, and explicit London venue metadata is still mandatory for these reviewed taxonomy overrides.

The registry still cannot create identity and still does not generalize `MUTUALFUND` acceptance. All OpenFIGI/ticker/MIC/kind/name/symbol/venue guards are unchanged. `LSE:CAGP` remains fail-closed as Yahoo `BOND`. Warm-cache refresh already used this missing-currency semantics for independently proven non-US bindings, so cold and warm paths are now consistent.

Telemetry adds `reviewed_yahoo_mutualfund_currency_unreported_matches` to make this exact relaxation visible in live coverage. Resolver policy: `0.3.32-policy32`; existing bindings are revalidated automatically.

## v0.3.31 — reviewed MUTUALFUND guard diagnostics

This release does **not** broaden identity admission. It instruments the exact reviewed Yahoo `MUTUALFUND` registry so a live coverage run reports which guard blocks each reviewed candidate. Aggregate counters use names such as `reviewed_yahoo_mutualfund_block_no_openfigi_identity`, `..._strict_mapping`, `..._mic_mismatch`, `..._name_mismatch`, `..._currency_*`, and `..._venue_*`; per-instrument counters also include the normalized TradingView id (for example `reviewed_yahoo_mutualfund_block_LSE_KAKU_no_openfigi_identity`).

Resolver policy is bumped to `0.3.31-policy31` only to force a cold diagnostic pass; VERIFIED/REJECTED semantics are unchanged from v0.3.30.

## v0.3.30 — exact reviewed Yahoo MUTUALFUND taxonomy overrides

The v0.3.29 UK-wide run reached 3,799 VERIFIED / 5 REJECTED. Thirteen of fifteen LSIN depositary receipts passed the generic evidence-gated Yahoo `MUTUALFUND` anomaly rule; only `LSIN:BKM` and `LSIN:EFGD` remained because OpenFIGI exposed those exact ticker/MIC identities under coarse `Common Stock` taxonomy rather than an explicit DR label. The other two Yahoo `MUTUALFUND` rejects were `LSE:KAKU` and `LSE:TGE`.

This release does **not** generalize `MUTUALFUND` acceptance. It adds an exact reviewed registry for four identities whose London listing class is independently documented by authoritative sources:

- `LSIN:BKM` — Bank Muscat GDR, ISIN `US0637462005`, Primary MIC `XLON`; LSE listing category is certificates/depository receipts and Citi identifies the program as `GDR - Reg S`.
- `LSIN:EFGD` — EFG Holding GDR, ISIN `US2684254020`, London GDR/DR listing; Citi identifies the program as `GDR - Reg S`.
- `LSE:KAKU` — Kakuzi equity, ISIN `KE0000000281`, Primary MIC `XLON`, LSE equity-share listing.
- `LSE:TGE` — The Generation Essentials Group Class A ordinary equity/CDI, ISIN `KYG382681016`, Primary MIC `XLON`, LSE equity-share listing.

The registry is **taxonomy evidence only**. It cannot create an identity. Admission still requires an independently resolved OpenFIGI exact ticker/MIC identity, the exact bounded Yahoo symbol, explicit matching currency, explicit compatible London venue, the expected TradingView kind, the reviewed MIC, and an issuer-name token guard. Yahoo chart-only evidence does not receive the exception. Yahoo-only `TARGET_PROVIDER_STRICT_FALLBACK` is explicitly excluded.

`LSE:CAGP` remains rejected: the provider conflict is not a Yahoo taxonomy defect; the London instrument is a perpetual/subordinated bond while TradingView labels it preferred stock.

Telemetry: `reviewed_yahoo_mutualfund_taxonomy_candidates` / `reviewed_yahoo_mutualfund_taxonomy_matches`. Resolver policy: `0.3.30-policy30`; existing bindings are revalidated automatically. The warm-cache rule already preserves an exact Yahoo type admitted during stronger cold-path discovery.

## v0.3.29 — evidence-gated Yahoo MUTUALFUND taxonomy exception for LSIN DRs

The v0.3.28 UK-wide run reached 3,786 VERIFIED / 18 REJECTED and exposed one uniform provider taxonomy defect: all 15 remaining `LSIN` depositary receipts reached an exact Yahoo `.L` row, but Yahoo classified every row as `MUTUALFUND`. Currency/venue were not the reported contradiction. Official LSE data independently identifies representative lines such as CFHS/FEDS as depositary receipts on XLOM and SDIC/TEEG as GDR/GDS lines on XLON; LSE's International Order Book is specifically a GDR venue.

This release adds a deliberately narrow compatibility exception. Yahoo `quoteType=MUTUALFUND` may corroborate an `LSIN` depositary receipt only when **all** of the following hold:

- TradingView prefix is exactly `LSIN` and instrument kind is DR/ADR.
- The mapping is **not** `TARGET_PROVIDER_STRICT_FALLBACK` or another Yahoo-only strict path.
- OpenFIGI independently and explicitly classifies the resolved identity as `Depositary Receipt`/ADR/GDR; coarse `Common Stock` compatibility is insufficient.
- Resolved MIC is exactly `XLON` or `XLOM`.
- Yahoo returns the exact bounded symbol, an explicit currency matching TradingView, and explicit London venue metadata compatible with the resolved MIC.
- The exception is currently applied only to the normal Yahoo bulk alternate row; chart-only `MUTUALFUND` evidence does not gain this relaxation.

The exception changes only Yahoo's type corroboration. OpenFIGI remains the identity authority and Yahoo still has to corroborate exact symbol, currency, and venue. `LSE:KAKU` and `LSE:TGE` remain rejected because they are TradingView common stocks rather than LSIN DRs; `LSE:CAGP` remains rejected as Yahoo `BOND`.

Telemetry: `yahoo_lsin_dr_mutualfund_taxonomy_candidates` and `yahoo_lsin_dr_mutualfund_taxonomy_matches`. Resolver policy: `0.3.29-policy29`; existing bindings are revalidated automatically. Warm-cache quote refresh preserves the exact Yahoo type admitted under this stronger cold-path proof, so an accepted DR is not invalidated merely because Yahoo continues to publish `MUTUALFUND`. Regression suite: 75 tests.

## v0.3.28 — preserve incompatible Yahoo chart evidence

- No admission rule is relaxed in this release.
- When Yahoo v7/quote omits an exact non-US symbol but v8/chart returns that exact symbol with conflicting metadata, the resolver now preserves the concrete contradiction instead of flattening it to `YAHOO_NO_MATCH`.
- Diagnostic rejection reasons are source-qualified, e.g. `YAHOO_CHART_CURRENCY_MISMATCH:GBP`, `YAHOO_CHART_TYPE_MISMATCH:MUTUALFUND`, or `YAHOO_CHART_VENUE_MISMATCH:...`.
- Adds bounded telemetry: `yahoo_incompatible_evidence_rows`, `yahoo_incompatible_currency_rows`, `yahoo_incompatible_type_rows`, `yahoo_incompatible_venue_rows`, and `yahoo_incompatible_symbol_rows`.
- This is intentionally diagnostic: the same Yahoo/OpenFIGI compatibility contract still determines VERIFIED vs REJECTED.
- Resolver policy: `0.3.28-policy28`. Existing bindings are revalidated automatically.

## v0.3.27 — LSIN XLOM currency-omitted proof + evidence-gated DR `.L` + MNTL transition alias

The 3,805-row UK coverage run on v0.3.26 reached 3,786 VERIFIED / 19 REJECTED. The reviewed BVS security-level fallback succeeded, while 15 LSIN depositary receipts still ended at `YAHOO_NO_MATCH`. The run also exposed the same-day `TM1 -> MNTL` exchange ticker transition.

- `LSIN` secondary-MIC resolution keeps `XLOM` exact. If `ticker + XLOM + currency` returns no OpenFIGI match, the resolver now retries **the same exact ticker + the same exact XLOM MIC with only the currency filter omitted**. This ADR-only relaxation is intended for thin IOB / Professional Securities Market DR lines where OpenFIGI currency metadata may be absent or modeled differently; ordinary LSIN stocks do not gain a currency-agnostic XLOM path. A match is recorded as `LSIN_SECONDARY_MIC_CURRENCY_OMITTED_FALLBACK`; ticker, MIC and security-type checks are unchanged.
- After an independently OpenFIGI-proven LSIN identity, Yahoo may use exactly one reviewed alternative representation: `.L` after the primary `.IL`. This now applies to depositary receipts as well as stocks. It remains forbidden for ADR rows that reached `TARGET_PROVIDER_STRICT_FALLBACK`, because Yahoo alone is not allowed to distinguish `XLON` from `XLOM`. No generic suffix search was added.
- Added dedicated LSIN DR telemetry: `yahoo_lsin_dr_alt_fallback_jobs/matches`. Generic LSIN alternative counters contain only LSIN alternatives and no longer include unrelated reviewed aliases.
- Added a temporary reviewed Yahoo transition alias for `LSE:MNTL -> TM1.L`. The alias is attempted only after OpenFIGI has already proven the current `MNTL`/`XLON` identity, only after canonical `MNTL.L` fails, and Yahoo must still satisfy currency/type/venue validation plus an issuer-name token check. The alias is provider lag handling, never identity proof. Stats: `reviewed_yahoo_symbol_alias_jobs/rows/matches`.
- Added stats `openfigi_secondary_mic_currency_omitted_jobs/matches`.
- The three explicit type conflicts (`KAKU`, `TGE`, `CAGP`) remain fail-closed; v0.3.27 does not reinterpret Yahoo `MUTUALFUND`/`BOND` as equity.
- Resolver policy: `0.3.27-policy27`. Existing bindings are revalidated automatically.
- Regression suite: 70 tests.

## v0.3.26 — LSIN secondary London MIC + reviewed ISIN security fallback

The 3,806-row UK coverage run exposed two distinct provider-model gaps without requiring any broad policy relaxation.

- `LSIN` is a TradingView provider namespace, not a single ISO MIC. `XLON` remains the primary exact OpenFIGI probe, but after an exact `XLON` no-match the resolver now tries the reviewed secondary London MIC `XLOM`. This covers Professional Securities Market / ATT International Order Book lines such as `CFHS`, `OTPD`, `FEDS`, and `UBLS`. A successful secondary match is recorded as `LSIN_SECONDARY_MIC_TYPE_FALLBACK`; source/target/resolved MIC are preserved as `XLOM` rather than silently rewritten to `XLON`.
- Yahoo representation for `XLOM` is bounded to `.IL`; venue validation accepts Yahoo IOB/London evidence and `gb_market`, mirroring the provider-level representation without claiming that Yahoo's `IOB` code itself is an ISO MIC.
- Reviewed ISIN ambiguities now have one additional fail-closed step. If `ID_ISIN + reviewed MIC` returns no OpenFIGI row, the resolver may submit the same reviewed `ID_ISIN` without a MIC. That response is used only as **security-level** evidence: venue FIGI and composite FIGI are discarded, only the compatible ticker/type/share-class identity may survive, and the reviewed MIC still comes from the authoritative listing record.
- The unscoped reviewed-ISIN path uses `REVIEWED_ISIN_SECURITY_FALLBACK` and requires Yahoo to explicitly report compatible currency, equity type, and venue. Missing metadata is not accepted on this path. This is intended for newly admitted lines such as `LSE:BVS`, where the LSE already reports `ISIN AU000000BVS9` and `MIC AIMX` but OpenFIGI's AIM mapping may lag the new listing.
- Added stats `openfigi_secondary_mic_jobs/matches`, `openfigi_isin_unscoped_fallback_jobs/matches`, and `reviewed_isin_security_fallback_matches`.
- Resolver policy: `0.3.26-policy26`. Existing bindings are revalidated automatically.
- Regression suite: 65 tests.

## v0.3.25 — LSIN instrument-aware Yahoo targets + reviewed ISIN ambiguity fallback

- Refined Yahoo target policy for TradingView `LSIN` without over-generalizing the suffix. Wide-universe evidence shows Yahoo can expose LSIN equities through IOB `.IL` even when TradingView's broad type is `stock`, so `.IL` remains the primary LSIN candidate. For non-ADR LSIN rows only, resolver tries one bounded `.L` alternative when `.IL` fails the same strict Yahoo contract. This covers lines such as `0QRL.L`/`0Q0Y.L` without regressing valid `.IL` equities. Deposit receipts stay `.IL` only. OpenFIGI source identity still resolves against `XLON`, and Yahoo venue validation accepts both LSE and IOB as London evidence.
- Added a narrow `REVIEWED_ISIN_FALLBACK` for exact TradingView identities that remain ambiguous under `ID_EXCH_SYMBOL + MIC` but have an authoritative reviewed ISIN. Current reviewed cases are `LSE:ROSE -> JE00BSBJ5M88 @ XLON` and `LSE:BVS -> AU000000BVS9 @ AIMX`. The ISIN is not accepted directly: resolver submits `ID_ISIN + reviewed listing MIC` to OpenFIGI and still requires normal Yahoo symbol/currency/type/venue validation. This also avoids treating TradingView's generic `LSE` provider prefix as proof that every London line is on `XLON`; AIM securities can use `AIMX`.
- Added stats `openfigi_isin_fallback_jobs` and `openfigi_isin_fallback_matches`.
- `diagnose-lsin` accepts `--kind STOCK|ADR|ETF|PREFERRED` and prints both reviewed Yahoo candidates when applicable (`.IL` primary plus bounded `.L` alternative for non-ADR rows), mirroring production resolution.
- Resolver policy: `0.3.25-policy25`.
- Regression suite: 62 tests.

## v0.3.24 — Yahoo chart metadata fallback

The primary Yahoo preflight remains the bulk `/v7/finance/quote` endpoint. For non-US symbols only, rows that are missing or contradict the expected OpenFIGI-backed symbol/currency/type/venue contract are re-checked through Yahoo `/v8/finance/chart/{symbol}` metadata. The chart endpoint reports its own exact symbol, currency, exchange and `instrumentType`; it is accepted only when that complete metadata satisfies the same resolver policy. This fixes provider-side thin-listing failures without weakening OpenFIGI identity proof.

New stats: `yahoo_chart_fallback_jobs`, `yahoo_chart_fallback_rows`, `yahoo_chart_fallback_matches`, plus equivalent `yahoo_chart_refresh_*` counters on warm-cache quote refresh. `OPENFIGI_AMBIGUOUS` is still fail-closed and a genuine source-type conflict such as a TradingView preferred row that Yahoo/LSE prove is a bond remains rejected.


## v0.3.23 — UK IOB/AQSE target-symbol correction

- **Refined in v0.3.25:** v0.3.23 mapped all `LSIN` rows to Yahoo `.IL`. v0.3.25 keeps `.IL` as the primary LSIN representation but adds exactly one `.L` fallback for non-ADR rows when `.IL` does not validate; no generic suffix search is performed.
- Aquis provider decoration `.GB` is stripped before Yahoo AQSE suffixing: `QED.GB -> QED.AQ`.
- TradingView `type=fund` with `typespecs=[reit]` is treated as REIT/equity identity, not ETF identity.
- Resolver policy bumped to `0.3.23-policy23`, so old bindings are revalidated under the corrected Yahoo target-symbol contract.
- Wide `identity_coverage_*` profiles use `Limit = 4000` (single request; no pagination).
- Explicit Yahoo type contradictions remain fail-closed. In particular, bonds mislabelled by TradingView as preferred stock are not admitted as equities.


- Removed `FetchAll` and automatic offset pagination.
- Coverage presets now use `Limit = 2000` and issue one deterministic TradingView request.
- The CLI prints a warning when `totalCount` exceeds the returned row count / configured limit.
- Package metadata and `tv_market_identity.__version__` are synchronized with the current release.
- Resolver identity policy is unchanged at `0.3.21-policy21`; existing v0.3.21 bindings remain cache-compatible.

# TV Market Identity Prototype v0.3.19

## v0.3.19 — optional TradingView screening filters

Identity-coverage presets may now contain only `market=...`. `market_cap_basic`, `average_volume_90d_calc`, `price_earnings_ttm`, and `sector` are optional and are added to the TradingView query only when present. Existing GARP presets are unchanged.

This is a screening/config-layer change only; resolver identity policy remains `0.3.18-policy18`, so existing verified bindings stay cache-compatible.

Included diagnostic preset: `config/identity_coverage_switzerland.ini`.


## v0.3.18 — strict Swiss secondary-listing fallback

The Switzerland live run reached 12/14 with only `SIX:ISP` (Intesa Sanpaolo) and `SIX:T` (AT&T) left as `OPENFIGI_NO_MATCH`. Both are real SIX secondary listings, but OpenFIGI may not expose them through `ID_EXCH_SYMBOL + XSWX`. After the normal exact OpenFIGI attempts fail, the reviewed `SIX` namespace can use `TARGET_PROVIDER_STRICT_FALLBACK`.

Admission still requires Yahoo to return the exact `.SW` symbol and explicitly match CHF quote currency, `EQUITY` type, and Swiss venue (`EBS`/SIX). FIGI fields stay empty, so this lower evidence tier is visible rather than disguised as an OpenFIGI proof. The same strict contract is enforced on warm-cache refresh.

Resolver policy: `0.3.18-policy18`.


## v0.3.18 — SIX Swiss Exchange support

The UK live run remained at 90/93 and showed two final provider edge cases.

- Some thin LSIN Yahoo rows return the exact requested `.L` symbol and a real price but omit **all** of `exchange`, `fullExchangeName`, `market`, `currency`, and `quoteType`. For non-US bindings only, this is admitted when OpenFIGI has already proven the exact target listing and Yahoo returns the exact requested symbol with a non-null quote value. Any explicit Yahoo metadata that is present must still agree. The same rule is used on warm-cache quote refresh. Such rows are marked `FRESH_METADATA_UNREPORTED`.
- Some London GBX instruments (observed with `LSE:SGRO`) can fail OpenFIGI mapping with both `GBp` and reviewed `GBP` currency filters. After those strict attempts fail, the resolver performs one final London-only mapping job with **exact local ticker + exact `XLON` MIC and no currency filter**. The returned OpenFIGI row must still be equity-compatible, and Yahoo must later confirm the exact `.L` symbol and `GBp` quote unit. This drops only a descriptive OpenFIGI filter; symbol and venue remain exact.
- Added stats `openfigi_currency_omitted_jobs` / `openfigi_currency_omitted_matches`.
- Resolver policy: `0.3.18-policy18`.
- Regression suite: 39 tests.



### v0.3.17 changes

- Added reviewed TradingView provider-prefix mapping `SIX -> XSWX`.
- Added Yahoo Swiss target validation: `XSWX -> .SW`, Yahoo exchange code `EBS`, Swiss venue-name hints, and `ch_market` fallback.
- Kept `SIX` and `XSWX` conceptually separate: `SIX` is the TradingView data-source prefix; `XSWX` is the ISO MIC used for OpenFIGI identity proof.
- Added `config/garp_largecap_switzerland.ini`.
- Resolver policy: `0.3.17-policy17`.

### v0.3.16 changes

- A Yahoo quote row returned for the exact requested non-US symbol can corroborate an already OpenFIGI-proven identity even when current price and all Yahoo metadata are absent. Missing price is represented as `quote_status=UNAVAILABLE`; it no longer invalidates identity.
- After all exact OpenFIGI attempts return no match for a reviewed London same-venue symbol, a narrow `TARGET_PROVIDER_STRICT_FALLBACK` is allowed. It requires explicit Yahoo symbol, currency/unit, equity type and venue agreement. FIGI fields remain empty so the weaker evidence level is visible.
- The same rules are enforced during warm-cache quote refresh.

## v0.3.14 — thin Yahoo venue metadata + London GBP/GBp OpenFIGI fallback

The latest UK live run reached 90/93 VERIFIED. The remaining cases exposed two narrow provider-model gaps.

- Thin LSIN Yahoo rows may omit `exchange` and `fullExchangeName` as well as `quoteType`. For non-US bindings only, missing venue metadata is accepted when OpenFIGI has already proven the exact target MIC, Yahoo returns the exact requested symbol, and Yahoo still reports the reviewed market bucket for that MIC (`XLON -> gb_market`). Explicit venue/market conflicts remain rejected. Cold resolution and warm cached quote refresh use the same rule. Such rows are marked `FRESH_VENUE_UNREPORTED` or `FRESH_METADATA_UNREPORTED`.
- Some London penny-quoted instruments can be represented by OpenFIGI with major-unit currency `GBP` even though TradingView/Yahoo quote them in `GBX`/`GBp`. After the strict `GBp + securityType2` job and the no-type `GBp` fallback both fail, `LSE`/`LSIN` rows with TV currency `GBX` get one additional exact `ticker + XLON + GBP` OpenFIGI lookup. Yahoo price validation remains `GBX <-> GBp`, so no 100x unit conversion is hidden.
- `yahoo_market` is included in the identity fingerprint when it is used as evidence for a thin Yahoo row.
- Resolver policy: `0.3.14-policy14`.

The expected UK result after upgrading is 93/93 if `SGRO` is the observed GBP-modeled OpenFIGI edge case and the two LSIN rows continue to return `market=gb_market`.

## v0.3.13 — London share-class collapse + missing Yahoo type

The second UK live run still returned 23 `OPENFIGI_AMBIGUOUS:2`, two Yahoo `quoteType=null` cases, and one `SGRO` OpenFIGI miss. This version tightens the model around the evidence rather than adding fuzzy matching.

- Multiple exact OpenFIGI rows are security-level unambiguous when **every row has the same non-null `shareClassFIGI`**, even if their `compositeFIGI` values differ. OpenFIGI defines share-class FIGI specifically to link multiple composite FIGIs for the same class of the same equity. The resolver therefore collapses such rows at share-class level.
- A common `compositeFIGI` is retained only when all rows agree. If composites differ, `composite_figi` is left null; venue FIGI is always left null for a collapsed result.
- For non-US rows only, Yahoo `quoteType=null` is treated like missing metadata rather than a contradiction when OpenFIGI has already proven the exact listing/type and Yahoo still confirms exact symbol + venue. The quote is marked `FRESH_TYPE_UNREPORTED` (or `FRESH_METADATA_UNREPORTED` when currency is also missing). Explicitly incompatible Yahoo types still reject.
- Added `diagnose-openfigi` to inspect one exact listing across currency/type combinations. This is intended for the remaining `LSE:SGRO` case instead of guessing its OpenFIGI currency/taxonomy.
- Resolver policy bumped to `0.3.12-policy12`.

Run the UK screen again, then if `SGRO` is the only reject:

```powershell
tv-market-id --cache .\cache\identity.sqlite3 diagnose-openfigi `
  --symbol SGRO `
  --mic XLON `
  --currencies "GBp,GBP" `
  --security-types "Common Stock,"
```

`securityType2=<none>` in the output is the no-type diagnostic job.

## v0.3.11 — UK ambiguity collapse, REIT fallback, missing Yahoo currency

The live UK run reached 67/93 VERIFIED and exposed three remaining provider-model differences.

- OpenFIGI duplicate rows are collapsed only when all exact ticker/MIC/type-compatible rows have the same non-null `shareClassFIGI` and at most one `compositeFIGI`. The binding records a security-level identity and deliberately leaves the venue FIGI unset instead of choosing one arbitrary row.
- If a strict OpenFIGI job with `securityType2` returns no result, that row alone is retried without `securityType2`; the response still must match exact ticker + MIC + currency and an equity-compatible type. This covers provider subtypes such as REIT while preserving fail-closed identity checks.
- Yahoo occasionally returns an exact non-US symbol/venue/type with `currency=null`. When OpenFIGI has already proven the currency-constrained listing, this is admitted as `FRESH_CURRENCY_UNREPORTED`; an explicit conflicting Yahoo currency is still rejected. US/Finnhub bindings continue to require Yahoo currency.

Resolver policy version is bumped, so identity bindings revalidate automatically while provider caches remain reusable.

## v0.3.10 — corrected UK/OpenFIGI semantics

The live UK diagnostic exposed two incorrect assumptions in v0.3.9.

### LSE penny sterling

TradingView reports penny-quoted London equities as `GBX`, Yahoo reports the same quote unit as `GBp`, and OpenFIGI accepts `GBp` as a distinct currency enum. Mapping jobs therefore use:

`TV GBX -> OpenFIGI GBp -> Yahoo GBp`

`GBP` remains distinct. This prevents a silent 100x pound/pence error.

### LSIN

TradingView `LSIN` is its London Stock Exchange (International Companies) data-source namespace. The live `0Q0Y` diagnostic showed no OpenFIGI `exchCode=LI` result, but an exact `micCode=XLON` result plus Yahoo `0Q0Y.L`. v0.3.10 therefore treats both `LSE` and `LSIN` as TradingView prefixes that resolve to the actual London MIC `XLON`; OpenFIGI and Yahoo still independently validate each instrument.

### Depositary receipts and London ticker punctuation

OpenFIGI mapping jobs now use `securityType2=Depositary Receipt` for TradingView `type=dr`. Yahoo candidate generation for `XLON` is bounded to known provider punctuation differences, for example:

- `BT.A` / `BT/A` -> `BT-A.L`
- `AV.` -> `AV.L`
- `BA.` -> `BA.L`
- `RR.` -> `RR.L`

These are candidates only; Yahoo symbol/currency/type/venue checks remain mandatory before `VERIFIED`.

UK smoke-test preset remains `config/garp_largecap_uk.ini`.

Diagnostic example:

```powershell
tv-market-id --cache .\cache\identity.sqlite3 diagnose-lsin `
  --symbol 0Q0Y `
  --currency EUR `
  --yahoo-symbol 0Q0Y.L
```

## v0.3.8 — strict Tradegate → Xetra security-level bridge

Evidence from the live `DTE` diagnostic showed different venue FIGIs on XGAT/XETR but the same `shareClassFIGI`. The resolver therefore supports Tradegate only through an explicit security-level share-class bridge, preserving source and target venues separately.

## v0.3.7

- Accepts Finnhub `OOTC` as a provider-level OTC umbrella when Yahoo returns an exact-symbol OTC tier (`PNK`/OTCPK, `OQX`/OTCQX, `OQB`/OTCQB, `OID`/OTCID, or `OEM`/Other OTC).
- This is **not** an `OOTC -> one exact segment MIC` assertion: Yahoo's more specific tier is preserved as Yahoo venue metadata.
- Admission still requires exact Yahoo symbol plus matching currency and security type before venue compatibility is checked.
- Resolver policy version bumped to force revalidation of old identity bindings while retaining the Finnhub universe cache.


## v0.3.5

- Treats `OTCM` as the ISO operating MIC for the OTC Markets family; Yahoo OTCQX/OTCQB/OTCPK venues are accepted only after exact symbol, USD and security-type checks have already passed.
- Adds current `OTCD` (OTCID) tier compatibility.
- Accepts Finnhub `PUBLIC` only for an explicitly preferred TradingView instrument whose ticker matches the bounded preferred-series grammar.
- Splits generic `YAHOO_NO_MATCH` into symbol/currency/type/venue-specific rejection reasons.
- Resolver policy version bumped; existing identity rows are revalidated while the Finnhub universe cache is reused.
# TV Market Identity Prototype v0.3.4

Batch/fail-closed prototype for a large TradingView screener result set (~700-1000 rows):

`TradingView -> persistent cache -> Finnhub (US) / OpenFIGI (non-US) -> Yahoo raw preflight`.

SnapTrade and IBKR are intentionally not in the mandatory path.

## Why this version is designed for ~700 rows

It does **not** call every provider once per instrument:

- TradingView: one screener request (limit 1000).
- Finnhub US: one `stock_symbols('US')` universe download, persisted in SQLite for 24h; all ticker/MIC/type/FIGI matching after that is local SQL/dict work.
- OpenFIGI non-US: batched mapping jobs (100/request with API key; conservative 5/request without key).
- Yahoo: bulk `/v7/finance/quote` preflight, 75 symbols/request by default.
- Verified TV->Yahoo bindings: persisted for 60 days by default; rejected bindings for 6 hours.

On a warm run, unchanged identities are returned from SQLite without Finnhub/OpenFIGI resolution. Yahoo prices are **not** reused from the identity cache: cached VERIFIED symbols are refreshed in Yahoo bulk quote batches on every run.

## Default screener

`config/garp_largecap.ini` implements the supplied V2 filters:

- `market=america`
- `market_cap_basic > 10B`
- `average_volume_90d_calc > 500,000`
- `price_earnings_ttm > 0.1`
- GARP sector allowlist
- `Limit=1000`
- `OrderBy=market_cap_basic`
- `Ascending=true`
- `MinScore=0` (stored in config; identity prototype itself does not score)

The existing GARP preset that this prototype follows contains **15** allowed sectors (including Finance), not 14. Edit the single `sector|isin` line if you want a different list.

## Install (Windows / PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
```

Set Finnhub key (required when the US-universe cache is empty/stale):

```powershell
$env:FINNHUB_API_KEY = "..."
```

OpenFIGI key is optional but strongly recommended for bulk non-US resolution:

```powershell
$env:OPENFIGI_API_KEY = "..."
```

## Run TradingView only

```powershell
tv-market-id screen --config config/garp_largecap.ini --output out\screen.csv
```

## Full batch resolution

```powershell
tv-market-id run --config config/garp_largecap.ini --output out\resolved.csv
```

Default persistent cache:

```text
~/.cache/tv-market-identity/identity.sqlite3
```

Windows can override it explicitly:

```powershell
tv-market-id --cache .\cache\identity.sqlite3 run --config config\garp_largecap.ini --output out\resolved.csv
```

Second run should show a high `CACHE_HIT` count and normally avoid Finnhub/OpenFIGI identity calls. It still performs batched Yahoo quote refreshes so prices are not served from a 60-day identity cache.

Force binding revalidation:

```powershell
tv-market-id --cache .\cache\identity.sqlite3 run --config config\garp_largecap.ini --output out\resolved.csv --refresh
```

Cache diagnostics:

```powershell
tv-market-id --cache .\cache\identity.sqlite3 cache-stats
```

Clear cache:

```powershell
tv-market-id --cache .\cache\identity.sqlite3 cache-clear
```

## Resolution policy

### US TradingView rows

1. Refresh/load Finnhub `stock_symbols('US')` once.
2. Resolve locally by bounded symbol spelling + currency + security type + compatible MIC.
3. `NASDAQ` must resolve to `XNAS`; `NYSE` to `XNYS`.
4. `AMEX` is deliberately allowed to resolve only to reviewed `{XASE, ARCX}`; there is **no** global `AMEX -> XASE` rule because e.g. TradingView `AMEX:SPY` resolves to primary MIC `ARCX`.
5. Finnhub `figi` is stored as **composite FIGI**; `shareClassFIGI` separately.
6. Generate only bounded Yahoo candidates (`BRK.B -> {BRK.B, BRK-B}`), then require raw Yahoo metadata to match currency/type/venue.
7. Exactly one admitted Yahoo candidate -> `VERIFIED`; otherwise `REJECTED`.

### non-US TradingView rows

1. Require reviewed TV-prefix -> ISO MIC mapping.
2. Batch OpenFIGI `ID_EXCH_SYMBOL + micCode + currency + securityType2`.
3. Require exactly one matching OpenFIGI result.
4. Generate Yahoo suffix from an explicit MIC->Yahoo suffix table.
5. Raw Yahoo preflight must match exact symbol/currency/type/venue.

The non-US path is mostly irrelevant for the default `market=america` preset but is included for extension/testing (for example `TSX:SHOP`).

## Fail-closed examples

The resolver rejects rather than guesses on:

- missing/ambiguous Finnhub match;
- incompatible MIC/currency/type;
- missing/ambiguous OpenFIGI mapping;
- unknown Yahoo suffix;
- Yahoo symbol/currency/type/venue mismatch;
- provider outage when no still-valid cached binding exists.

No fallback converts a rejected identity into a live subscription automatically.

## Output

`resolved.csv` contains original TradingView columns plus:

- `identity_status`
- `cache_hit`
- `resolved_mic`, `source_mic`, `target_mic`, `mapping_method`
- `source_venue_figi`, `target_venue_figi`
- `yahoo_symbol`
- `yahoo_exchange`, `yahoo_market`, `yahoo_quote_type`, `yahoo_currency`
- `yahoo_price`, `yahoo_delayed_by`, `quote_status`
- `finnhub_symbol`, `finnhub_type`
- `composite_figi`, `share_class_figi`, `venue_figi`
- `rejection_reason`
- `identity_fingerprint`

`yahoo_price` is the REST preflight price and may be delayed. It is **not** treated as proof of real-time entitlement.

## Tests

```powershell
pytest -q
```

The test suite is network-free and checks persistent binding cache, `BRK.B -> BRK-B`, and `AMEX:SPY -> ARCX` behavior.

## Prototype limitations

- Yahoo Finance endpoints used by yfinance are unofficial and have no stable public SLA/rate contract.
- Finnhub international entitlements depend on plan; this prototype uses Finnhub as the fast US resolver and OpenFIGI as the non-US resolver.
- TradingView real-time access may require cookies; without them scanner values can be delayed. Identity fields are still usable separately from live-price semantics.
- MIC/Yahoo suffix and Yahoo exchange-code crosswalks are explicit policy tables and should be versioned/reviewed before production use.


## .env

`v0.3.4` automatically loads `.env` from the current working directory (or a parent directory) via `python-dotenv`.

```env
FINNHUB_API_KEY=your_key
OPENFIGI_API_KEY=optional_key
```

Check configuration before a full run:

```powershell
tv-market-id --cache .\cache\identity.sqlite3 doctor
```

Transient provider failures (`FINNHUB_UNAVAILABLE`, `OPENFIGI_UNAVAILABLE`, `YAHOO_UNAVAILABLE`) are no longer persisted as rejected identity bindings. If upgrading from v0.3.0 after such a failed run, clear the old cache once:

```powershell
tv-market-id --cache .\cache\identity.sqlite3 cache-clear
```


## v0.3.3 diagnostics and safer US matching

- Finnhub matching now builds a local normalized-symbol index from the cached US universe.
  Punctuation differences such as `BRK.B`, `BRK-B`, `BRK/B`, and `BRK B` are candidate generation only;
  a binding is still admitted only when exactly one candidate survives currency, type, and MIC checks.
- TradingView `type=dr` is recognized as ADR.
- `FINNHUB_NO_MATCH` is split into actionable failure codes:
  `FINNHUB_NO_SYMBOL`, `FINNHUB_CURRENCY_MISMATCH:*`, `FINNHUB_TYPE_MISMATCH:*`,
  `FINNHUB_MIC_MISMATCH:*`, and `FINNHUB_AMBIGUOUS:*`.
- `MIC_UNKNOWN` now prints a TV-prefix histogram in the CLI.
- Resolver policy version was bumped. Existing v0.3.1 bindings are ignored automatically, while the Finnhub universe cache is retained/reused.

Recommended rerun:

```powershell
pip install -e ".[dev]" --upgrade
tv-market-id --cache .\cache\identity.sqlite3 run `
  --config .\config\garp_largecap.ini `
  --output .\out\resolved.csv
```

Do **not** clear the cache before this rerun unless you specifically want to force a new Finnhub universe download.


## v0.3.3 policy note

Finnhub security types `REIT`, `MLP`, `NY Reg Shrs`, and `Tracking Stk` are treated as equity-like for **identity resolution** when TradingView reports `type=stock`. Their exact subtype is retained in `finnhub_type`; this does not make them eligible for an investment strategy.

TradingView prefixes `OTC` and `CBOE` remain fail-closed (`MIC_UNKNOWN`) until an explicit venue policy is configured. The CLI now exits 0 after a successfully completed batch even if individual instruments are rejected. Use `--strict-exit` to restore exit code 3 when any row is rejected.


## v0.3.4 — OTC/CBOE discovery and preferred-series symbology

This version addresses the remaining classes observed in the 669-row `market=america` run.

### OTC

`OTC` is now routed through the cached Finnhub US universe, but **there is still no `OTC -> MIC` mapping**.
The resolver:

1. finds only bounded exact-symbol candidates in the local Finnhub universe;
2. requires compatible USD/security type;
3. requires exactly one surviving provider identity;
4. takes `resolved_mic` from that Finnhub identity;
5. requires Yahoo to return the exact symbol with a compatible OTC venue code.

OTC venue checks remain fail-closed, but provider granularity is explicit: exact segment MICs use narrow Yahoo-tier mappings, while Finnhub `OTCM`/`OOTC` may act as umbrella venue evidence only after symbol/currency/type identity has already been established. The Yahoo tier remains stored separately and is not rewritten into a fabricated MIC.

### CBOE

TradingView `CBOE` listings are admitted only against Finnhub MIC `BATS` (Cboe BZX) and Yahoo's Cboe venue (`BTS` / `Cboe US`). This is an explicit reviewed rule, not discovery across all Cboe exchanges.

### Preferred series

TradingView preferred spelling such as `BA/PA` and `ORCL/PD` does not normalize correctly with generic punctuation stripping because NYSE/SIP/provider conventions may include `PR` (`BA-PRA`) while Yahoo may use `-P` (`BA-PA`).

v0.3.4 adds a bounded preferred-series canonicalizer. Only the explicit pattern `ROOT + separator + P/PR + one series letter` is normalized. Examples considered equivalent for candidate lookup:

```text
BA/PA   BA-PA   BA-PRA   BA.PA   BA.PRA
ORCL/PD ORCL-PD ORCL-PRD
```

The binding is still admitted only after unique Finnhub currency/type/MIC matching and Yahoo raw quote validation.

Finnhub `Preferred Stock` is now a separate identity kind from common stock.

### Upgrade

No cache clear is required. The resolver policy version changed, so bindings are revalidated while the cached Finnhub US universe is reused.

```powershell
pip install -e ".[dev]" --upgrade

tv-market-id --cache .\cache\identity.sqlite3 run `
  --config .\config\garp_largecap.ini `
  --output .\out\resolved.csv
```


## Germany / non-US validation

`v0.3.7` fixes OpenFIGI taxonomy for preferred shares. TradingView preferred rows such as `XETR:VOW3` are mapped with `securityType2=Preference` rather than `Common Stock`.

Tradegate is intentionally not aliased directly to Xetra. Use the evidence command:

```powershell
tv-market-id --cache .\cache\identity.sqlite3 diagnose-tradegate `
  --symbol DTE `
  --currency EUR `
  --security-type2 "Common Stock" `
  --yahoo-symbol DTE.DE
```

The command queries OpenFIGI for `TGAT`, `XGAT`, `XGRM` and `XETR`, prints venue/composite/share-class FIGIs, then checks Yahoo `DTE.DE`. `CROSS_VENUE_SECURITY_MATCH` is emitted only when a Tradegate result and the Xetra result share the same non-empty `shareClassFIGI` and Yahoo returns a compatible EUR equity. This is diagnostic evidence only; the production resolver remains fail-closed for `TRADEGATE:*` until that bridge is validated.


## v0.3.13 UK fixes

- Yahoo metadata sentinels such as `"NONE"`, `"NULL"`, empty string, and `"N/A"` are normalized to missing metadata before strict validation. This fixes thin LSIN quotes where Yahoo returns a textual `NONE` instead of JSON `null`.
- OpenFIGI `securityType2="Equity"` is accepted for TradingView `stock` only after the mapping query already constrains exact local ticker, MIC and currency. This supports broad provider taxonomy such as SGRO without weakening symbol matching.
- Resolver policy version is bumped, so identity bindings are revalidated while the persistent Finnhub universe remains reusable.


## v0.3.18 — Swiss secondary-listing fallback

`SIX:ISP` (Intesa Sanpaolo) and `SIX:T` (AT&T) are real SIX secondary listings,
but OpenFIGI may return no `ID_EXCH_SYMBOL + XSWX` mapping for them. After both
strict OpenFIGI attempts fail, the resolver may use `TARGET_PROVIDER_STRICT_FALLBACK`
for the reviewed `SIX` namespace. Admission still requires Yahoo to explicitly
confirm the exact `.SW` symbol, CHF quote currency, `EQUITY` type, and Swiss venue
(`EBS`/SIX). No FIGI is fabricated; FIGI fields remain empty for that binding.


## v0.3.20 — primary-listing coverage screens

`[TradingView] PrimaryOnly = true` adds TradingView's `is_primary == true` filter.
This is useful for market coverage tests because `market=switzerland` without it also includes large numbers of BX Swiss secondary/Worldcaps listings.
The resolver policy version is unchanged (`0.3.18-policy18`), so existing identity cache entries remain valid.

Example:

```powershell
tv-market-id --cache .\cache\identity.sqlite3 run `
  --config .\config\identity_coverage_switzerland_primary.ini `
  --output .\out\resolved_switzerland_primary.csv
```

## v0.3.21 venue coverage expansion

Reviewed direct venue mappings added from wide UK/Germany coverage tests:

- TradingView `AQUIS` -> ISO operating MIC `AQSE` -> Yahoo `.AQ`.
- TradingView `FWB` -> `XFRA` -> Yahoo `.F`.
- TradingView `DUS` -> `XDUS` -> Yahoo `.DU`.
- TradingView `HAM` -> `XHAM` -> Yahoo `.HM`.
- `XETR` is now eligible for the existing `TARGET_PROVIDER_STRICT_FALLBACK` after exhaustive OpenFIGI no-match; Yahoo must explicitly confirm exact `.DE` symbol, EUR, EQUITY and Xetra venue.
- The same strict fallback is available for the reviewed direct `AQUIS/FWB/DUS/HAM` namespaces if OpenFIGI has a coverage gap. No FIGI is invented in that path.

At v0.3.21, `LSE:ROSE` remained fail-closed because OpenFIGI returned two incompatible identities and it was not silently forced through the target-only fallback. v0.3.25 supersedes that state with the reviewed `ID_ISIN + MIC` fallback documented above.

Coverage profiles use one TradingView request with `Limit = 2000`. If `totalCount` exceeds the returned row count, the CLI warns that the result is truncated. `PrimaryOnly` semantics are explicit: `false` clears the library's implicit `is_primary=true` default; `true` adds it intentionally.

For apples-to-apples comparison with v0.3.20 market-only runs (which inherited the library's implicit `is_primary=true`), use `identity_coverage_uk_primary.ini` and `identity_coverage_germany_primary.ini`. The non-primary coverage files now intentionally clear that implicit restriction and therefore may return a larger universe.
