# TV Market Identity Prototype v0.3.63

## v0.3.63 — stale-listing / corporate-action diagnostics

Diagnostic-only release. Admission remains `0.3.62-policy62`; no resolver policy
is relaxed and the existing VERIFIED cache remains valid.

The v0.3.62 residual audit showed that both targeted home-market OpenFIGI proof
paths (`ID_ISIN + micCode` and `ID_EXCH_SYMBOL + micCode`) return no mapping for
the remaining ARX/OPTT/DAL candidates. More importantly, several
`SHARE_CLASS_MISSING` rejects carry identifiers that became stale after recent
reverse splits/share consolidations. Such rows must not be admitted merely
because the issuer/ticker looks familiar.

v0.3.63 therefore adds evidence only:

- `active_symbol` is included in the ordinary TradingView snapshot and `TvRow`;
- `--rejection-audit` records that value for every rejected row;
- the audit performs a separate exact-ticker TradingView probe for current
  reference data and records `active_symbol`, `isin`, and, when the endpoint
  supports them, `cusip` and `figi`;
- CUSIP/FIGI probing is isolated from the production universe query and fails
  soft into diagnostic `errors`, so an undocumented/authorization-dependent
  field can never break acquisition or affect admission.

The purpose is to distinguish a genuine unresolved current listing from a
retired/stale source symbol after a corporate action. A later policy release may
exclude proven inactive predecessor listings or bridge a successor only when a
machine-readable stable identifier supports it. No name matching, successor
allowlist, or old-ISIN admission is introduced here.


## v0.3.62 — exact ISIN + home-MIC listing confirmation

Policy release `0.3.62-policy62`. Existing VERIFIED bindings from policy61,
policy59, policy58, and the previous policy56/55/54/53/49/44 chain remain
cache-compatible; rejected rows are re-evaluated.

The v0.3.61 live Germany run proved that `ID_EXCH_SYMBOL + micCode` is not a
reliable primary confirmation primitive for the remaining Yahoo home-market
candidates: all three targeted jobs (`ARX/XTSE`, `OPTT/XASE`, `DAL/XMIL`)
returned no usable mapping even though Yahoo exact-ISIN search and quote
metadata were internally consistent.

v0.3.62 moves the independent OpenFIGI confirmation one level closer to the
actual identity model. For a Yahoo candidate whose ticker is absent from the
unscoped OpenFIGI `ID_ISIN` rows, the resolver now asks OpenFIGI whether the
**same exact ISIN** exists on the reviewed Yahoo home MIC and requires the
**same independently established shareClassFIGI**:

```text
TradingView exact ISIN
  -> OpenFIGI ID_ISIN (unscoped)
  -> exactly one observed non-null shareClassFIGI
  -> Yahoo Search by exact ISIN only
  -> reviewed Yahoo exchange code -> ISO MIC
  -> bounded Yahoo symbol/suffix contract for that MIC
  -> OpenFIGI ID_ISIN + micCode
  -> require the same shareClassFIGI
  -> strict Yahoo symbol + exchange + currency + EQUITY quote contract
```

This proves **security identity + home listing identity** without requiring
Yahoo and OpenFIGI to use identical ticker syntax. `ID_EXCH_SYMBOL + micCode`
remains only as a secondary fallback when the exact-ISIN+MIC mapping is absent.
A conflicting share class is a hard fail and does not fall through to symbol
proof. Unknown Yahoo exchanges, malformed/incorrect Yahoo suffixes, multiple
valid Yahoo routes, missing share-class evidence, and quote-contract
contradictions remain fail-closed. No name matching or suffix guessing is used.

`--rejection-audit` now also records `home_mic`, the exact targeted
`ID_ISIN+micCode` OpenFIGI rows, whether the expected share class was confirmed,
and any conflicting share classes. This evidence is diagnostic only.

## v0.3.61 — exact home-venue exchange-symbol confirmation

Policy release `0.3.61-policy61`. Existing VERIFIED bindings from policy59,
policy58, and the previous policy56/55/54/53/49/44 chain remain
cache-compatible; rejected rows are re-evaluated.

The v0.3.60 candidate-level audit isolated a narrow provider-coverage gap: Yahoo
exact-ISIN search can return a single valid home-market `EQUITY` symbol even
when OpenFIGI's *unscoped* `ID_ISIN` response omits that local ticker. Rather
than trust Yahoo Search or introduce ticker/name heuristics, v0.3.61 adds a
second independent OpenFIGI proof for reviewed Yahoo venues:

```text
TradingView exact ISIN
  -> OpenFIGI ID_ISIN (unscoped)
  -> exactly one observed non-null shareClassFIGI
  -> Yahoo Search by exact ISIN only
  -> if the Yahoo ticker is absent from unscoped OpenFIGI rows:
       Yahoo exchange code -> reviewed ISO MIC
       Yahoo symbol -> exact local exchange symbol
       OpenFIGI ID_EXCH_SYMBOL + micCode
       require the same shareClassFIGI
  -> strict Yahoo symbol + exchange + currency + EQUITY quote contract
```

The initial reviewed venue bridge is intentionally limited to the exchanges
actually exposed by the v0.3.60 residual audit: `TOR -> XTSE`, `ASE -> XASE`,
and `MIL -> XMIL`. These are venue mappings, not security allowlists. Unknown
Yahoo exchange codes are not guessed. A conflicting or missing share class, an
unresolved local symbol, multiple valid Yahoo routes, or any Yahoo contract
contradiction remains fail-closed. No fuzzy-name matching is introduced.

## v0.3.60 — home-market rejection audit expansion

Diagnostic-only release. Admission remains `0.3.59-policy59`; no resolver
policy is relaxed. The Germany v0.3.59 residual set is small enough that the
next bottleneck must be diagnosed at Yahoo-candidate level rather than inferred
from aggregate counters.

`--rejection-audit` now records, for each rejected exact-ISIN row with a usable
observed share class:

```text
Yahoo exact-ISIN search candidate
  -> search symbol / exchange / quoteType / names
  -> bounded Yahoo ticker identity keys
  -> exact-ISIN OpenFIGI ticker/shareClass confirmation
  -> Yahoo quote metadata and strict contract blocks
  -> chart fallback metadata and strict contract blocks
  -> final per-candidate admission_blocks
```

The new JSONL fields are `home_market_audit_status` and
`home_market_search_candidates`. They are evidence-only and are never consumed
by resolver admission. This release exists to distinguish ticker-proof gaps
from Yahoo quote-contract failures before any further policy change.

## v0.3.59 — observed-unique shareClassFIGI home-market rescue

Policy release `0.3.59-policy59`. VERIFIED bindings from policy58 and the
previous policy56/55/54/53/49/44 chain remain cache-compatible; rejected rows
are re-evaluated.

The v0.3.58 full-Germany audit showed a provider-completeness edge case: for
many exact ISINs OpenFIGI reports one consistent non-null `shareClassFIGI` on
some venue rows while omitting `shareClassFIGI` on other rows. v0.3.58 treated
any omission as a hard block. v0.3.59 changes only that completeness guard:

```text
exact TradingView ISIN
  -> compatible OpenFIGI rows
  -> exactly one observed non-null shareClassFIGI
  -> rows with shareClassFIGI=null are non-evidence
  -> Yahoo exact-ISIN search candidate must match an OpenFIGI ticker
     on a row that explicitly carries that same shareClassFIGI
  -> same strict Yahoo symbol/exchange/currency/EQUITY quote contract
```

This does **not** infer a share class for rows where OpenFIGI omitted it. A
missing-share row cannot confirm a Yahoo ticker. Zero observed share classes,
more than one observed share class, ticker mismatch, multiple valid Yahoo
routes, or quote-contract contradictions remain fail-closed. `GETTEX:PEQ` and
other taxonomy conflicts are unchanged.

## v0.3.58 — exact-ISIN Yahoo home-market discovery

Policy release `0.3.58-policy58`. Existing VERIFIED bindings from policy56,
policy55, policy54, policy53, policy49, and policy44 remain cache-compatible;
older rejects are re-evaluated.

For rejected German `stock/common` rows with an exact TradingView ISIN, the
resolver now has one final fail-closed quote-routing path after all German
listing rescues are exhausted:

```text
TradingView exact ISIN
  -> OpenFIGI ID_ISIN (unscoped)
  -> exactly one non-null shareClassFIGI across compatible equity rows
  -> Yahoo Search with the exact ISIN only (fuzzy disabled)
  -> candidate ticker must occur in the same OpenFIGI exact-ISIN evidence
  -> Yahoo quote/chart must explicitly confirm symbol + exchange + currency + EQUITY
  -> VERIFIED as YAHOO_EXACT_ISIN_HOME_MARKET
```

This is a **quote-routing** rescue, not a German listing proof. Therefore Yahoo
home-market currency may differ from TradingView Germany `EUR`. The persisted
refresh contract is correspondingly strict and independent of the German quote
contract: the same Yahoo symbol, same Yahoo exchange, same currency, and
`quoteType=EQUITY` must remain true. Multiple simultaneously valid Yahoo routes
remain rejected rather than being ranked heuristically. No fuzzy-name search,
suffix guessing, or generic taxonomy relaxation is used.

## v0.3.57 — rejection-audit unscoped exact-ISIN diagnostics

Diagnostic-only release; resolver policy remains `0.3.56-policy56`.

`--rejection-audit` records the result of an unscoped OpenFIGI `ID_ISIN` lookup
for every rejected row with an ISIN. This evidence is **not used for admission**.
It exposes home/global ticker and exchange-code candidates (`unscoped_openfigi`)
plus a compact status/share-class summary so the home-market Yahoo fallback can
be designed from exact-ISIN evidence instead of fuzzy name search.

The lookup is batched and reuses the provider run memo, so jobs already executed
by resolver diagnostics do not cause duplicate network calls.

## v0.3.56 — exact-ISIN equity-like + Yahoo ETF taxonomy reconciliation

Policy release `0.3.56-policy56`. Existing VERIFIED bindings from policy55,
policy54, policy53, policy49, and policy44 remain cache-compatible; older rejects
are re-evaluated.

The final Germany exact-ISIN rescue now tolerates one additional provider-only
classification disagreement: OpenFIGI may classify the exact share class as a
reviewed exchange-traded equity-like form (`Unit / Unit`, `Stapled Security /
Unit`, `Dutch Cert / Depositary Receipt`, or `Savings Share / Common Stock`)
while Yahoo labels the *same exact German listing* as `ETF`. This rule is
identity-only and requires all of the following simultaneously:

- exact TradingView ISIN and one non-null OpenFIGI `shareClassFIGI`;
- the existing reviewed equity-like OpenFIGI taxonomy;
- exact expected Yahoo symbol;
- explicit matching EUR currency;
- explicit compatible German regional venue;
- Yahoo quote type exactly `ETF`.

`MUTUALFUND`, synthetic `YHD`, missing currency/venue, wrong currency/venue, and
mixed fund taxonomy remain fail-closed. Successful mappings use
`GERMANY_FINAL_EXACT_ISIN_RESCUE_EQUITY_LIKE_YAHOO_ETF_TAXONOMY`.

Offline replay over the real v0.3.55 residual audit rescued exactly 3 of 92 rows
(`FWB:3IJ0`, `LS:577633`, `GETTEX:5VC`) and no others. Expected Germany residual
after policy56 is therefore about 89 rows, subject to live provider/universe
drift.


## v0.3.55 — exact-ISIN listed closed-end fund identity rescue

Policy release `0.3.55-policy55`. Existing VERIFIED bindings from policy54,
policy53, policy49, and policy44 remain cache-compatible; older rejects are
re-evaluated.

The bounded final Germany rescue now treats a pure OpenFIGI
`Closed-End Fund / Mutual Fund` classification as identity-compatible with a
TradingView `stock/common` row only when the existing exact-ISIN contract is
fully satisfied: one non-null `shareClassFIGI`, source-side corroboration when
present, and Yahoo's ordinary EUR/EQUITY/German-venue contract. These mappings
use `GERMANY_FINAL_EXACT_ISIN_RESCUE_LISTED_FUND`.

This is an identity-routing decision only; downstream GARP eligibility remains a
separate concern. Mixed/private-equity fund taxonomy is still fail-closed. In
particular, an ISIN/share class that is also returned as `Pvt Eqty Fund / Mutual
Fund` is not admitted by this rule.

Offline replay over the real v0.3.54 residual audit rescued exactly 10 of 102
rows, while the mixed Private Equity Holding case remained rejected. Expected
Germany residual after policy55 is therefore about 92 rows, subject to live
provider/universe drift.


## v0.3.54 — exact-ISIN share-subtype reconciliation

Policy release `0.3.54-policy54`. Existing VERIFIED bindings from policy53,
policy49, and policy44 remain cache-compatible; older rejects are re-evaluated.

The bounded final Germany rescue now also reconciles provider naming differences
for the same exact-ISIN share class when TradingView and OpenFIGI disagree only
on the listed-equity subtype:

- TradingView `preferred` -> OpenFIGI `Common Stock / Common Stock`;
- TradingView `preferred` -> OpenFIGI `Savings Share / Common Stock`;
- TradingView `stock/common` -> OpenFIGI `Preference / Preference`.

Admission still requires exact TradingView ISIN, one non-null shareClassFIGI,
source-side corroboration when present, and Yahoo's ordinary EUR/EQUITY/venue
contract.  These cases use mapping method
`GERMANY_FINAL_EXACT_ISIN_RESCUE_SHARE_SUBTYPE`.

Fund taxonomies remain intentionally excluded: `Closed-End Fund` and
`Pvt Eqty Fund` are still fail-closed.  A replay over the v0.3.53 Germany audit
rescued exactly 8 of 110 residual rows and did not admit any fund row.


## v0.3.53 — final exact-ISIN Germany rescue for alias/taxonomy gaps

Policy release `0.3.53-policy53`. Existing VERIFIED bindings from policy49 and
policy44 remain cache-compatible; prior rejects are re-evaluated.

After the normal resolver finishes, only already-rejected German `stock/common`
rows with an exact TradingView ISIN and one of the reviewed residual reasons are
re-probed across the bounded German regional MIC set. Admission still requires:

- exact `ID_ISIN + MIC` OpenFIGI evidence;
- exactly one non-null `shareClassFIGI` across Yahoo-valid targets;
- any available source-side exact-ISIN evidence to corroborate that same share
  class;
- Yahoo to pass the ordinary EUR/type/venue contract, except for the pre-existing
  bounded German Yahoo ETF/MUTUALFUND anomaly on ordinary common-equity/REIT
  identities.

The rescue deliberately permits multiple OpenFIGI ticker aliases on the same MIC
when they all identify the same share class; Yahoo chooses the usable quote alias
only after identity is fixed.  A narrow exact-ISIN-only taxonomy extension covers
`Unit/Unit`, `Stapled Security/Unit`, `Dutch Cert/Depositary Receipt`, and
`Savings Share/Common Stock` when Yahoo independently confirms a normal EQUITY
quote. `Closed-End Fund`, `Pvt Eqty Fund`, and TradingView preferred rows remain
fail-closed.

New telemetry is prefixed with `germany_final_exact_isin_rescue_`,
`openfigi_germany_final_rescue_`, and `yahoo_germany_final_rescue_`.


## v0.3.49 — exact-ISIN German regional source-gap bridge + bounded Yahoo retry

This release changes resolver admission only for German bridge rows that already carry an exact
TradingView ISIN.  It does **not** broaden OpenFIGI type compatibility: `Unit`, `Stapled Security`,
`Closed-End Fund`, `Dutch Cert`, and other taxonomy disagreements remain fail-closed for now.

Two evidence-gated improvements are added:

- GETTEX/TRADEGATE/LS/LSX rows with no compatible source listing may use a one-sided German
  regional target only when the target is independently proven by `ID_ISIN + exact MIC`, has a
  non-null and unambiguous `shareClassFIGI`, and Yahoo passes the ordinary German
  currency/type/venue contract.  Multi-MIC source namespaces preserve the source venue code
  rather than inventing a source MIC or source FIGI.
- German regional Yahoo probing performs one bounded second bulk request only for rows that got
  no valid candidate on the first response.  The retry uses the exact same admission contract.

Resolver policy is now `0.3.49-policy49`.  Because this change is monotonic (it only admits
previously-rejected exact-ISIN cases), VERIFIED bindings created under `0.3.44-policy44` are
explicitly cache-compatible and remain reusable.  Old policy44 REJECTED bindings are ignored and
re-resolved under policy49.

Recommended full-Germany upgrade run:

```powershell
tv-market-id --cache .\cache\identity.sqlite3 run `
  --config .\config\identity_coverage_germany_full.ini `
  --output .\out\identity_coverage_germany_full_v049.csv
```

Use `--rejection-audit` if you want the new residual evidence set.

## v0.3.47 — single-shot full-universe TradingView acquisition

This release changes only the TradingView acquisition layer. Resolver/admission policy remains
`0.3.44-policy44`, so all v0.3.44+ validated bindings remain cache-compatible.

The previous offset-pagination experiments (`v0.3.45`/`v0.3.46`) correctly failed closed when
TradingView's live Germany universe changed during the multi-request scan. The installed
`tradingview-screener` API does not require pagination for this scale: `Query.limit()` sets the
upper range boundary and supports large values. The Germany full preset now requests up to
100,000 rows in one POST (`range=[0,100000)`).

`RequireCompleteUniverse=true` makes this fail closed unless the same response satisfies:

- returned row count == TradingView `totalCount`;
- every returned `EXCHANGE:SYMBOL` is unique;
- the response includes the `ticker` column.

This removes both equal-sort-key boundary instability and cross-request `totalCount` drift.

Recommended preflight:

```powershell
tv-market-id screen `
  --config .\config\identity_coverage_germany_full.ini `
  --output .\out\identity_coverage_germany_full_screen.csv
```

Expected shape is one request with `returned == unique_rows == totalCount`.

## v0.3.46 — overlap + confirmed full-universe TradingView pagination

This release changes only TradingView acquisition. Resolver admission remains
`0.3.44-policy44`, so the validated v0.3.44 Germany bindings stay cache-compatible.

v0.3.45 correctly failed closed on the first live full-Germany preflight:
`totalCount=33389`, but ordinary non-overlapping `name ASC` pages contained five
repeated TradingView tickers and therefore only 33384 unique rows. The cause is
that TradingView exposes only one server-side sort key while `name` is the short
symbol, not the unique `EXCHANGE:SYMBOL`; equal-name venue listings can therefore
change tie order at offset boundaries.

- Pagination now uses intentional overlapping windows. With the default
  `Limit=4000` and `PaginationOverlap=256`, offsets advance by 3744 rows.
- Duplicate observations inside overlap are expected and are no longer treated
  as an error by themselves. The pass succeeds only when the union contains
  exactly `totalCount` unique canonical `EXCHANGE:SYMBOL` tickers.
- Returned rows are client-side sorted by canonical ticker after union/dedup;
  server tie order is never used as an identity key.
- `PaginationConfirmPasses=2` performs two independent complete scans and
  requires the exact ticker membership set to be identical. This detects
  count-stable constituent drift that a simple `totalCount` check cannot see.
- `PaginationRetries=1` retries the whole confirmation cycle. On retry the
  overlap doubles (256 -> 512) to protect against a larger equal-name tie group.
- Every individual page must still report the same totalCount and expected row
  count. Incomplete union, membership drift, page-size mismatch, or totalCount
  drift remains fail-closed with exit code 4.
- CLI telemetry now includes page size, effective overlap, confirmation passes,
  attempts, raw observations, unique rows, duplicate observations, and totalCount.
- Existing non-paginated top-N configs and resolver policy are unchanged.
- Package version: `0.3.46`; resolver policy remains `0.3.44-policy44`.
  Regression suite: 129 tests.

Recommended full-Germany preflight (TradingView only):

```powershell
tv-market-id screen `
  --config .\config\identity_coverage_germany_full.ini `
  --output .\out\identity_coverage_germany_full_screen.csv
```

A successful pass should report `unique_rows == totalCount`; duplicate
observations will be non-zero by design because windows overlap. Only after the
preflight succeeds should the full identity run be started without `--refresh`:

```powershell
tv-market-id --cache .\cache\identity.sqlite3 run `
  --config .\config\identity_coverage_germany_full.ini `
  --output .\out\identity_coverage_germany_full.csv
```

## v0.3.44 — Germany final evidence-gated regional rerouting

The v0.3.43 rejection audit reduced the Germany top-4000 residual set to 22
rows and showed that every residual security has at least one bounded German
regional target where exact TradingView ISIN + MIC resolves in OpenFIGI and
Yahoo passes the ordinary equity/currency/venue contract.  v0.3.44 promotes
only those already-measured evidence paths.

- Final Yahoo failures (`YAHOO_NO_MATCH` and German `MUTUALFUND`/`ETF`
  taxonomy mismatches) may reroute to another reviewed German regional MIC
  only when `ID_ISIN + target MIC` is unambiguous, Yahoo passes the ordinary
  non-US contract there, and any existing OpenFIGI evidence has the same
  non-null `shareClassFIGI`.
- Direct German prefixes (`FWB`, `DUS`, `HAM`, `SWB`, `MUN`, `HAN`) get a
  one-sided exact-ISIN regional fallback only after the same-venue OpenFIGI
  path is exhausted.  The original source MIC is retained, no source FIGI is
  fabricated, and the alternate target must provide a non-null shareClassFIGI
  plus ordinary Yahoo evidence.  Mapping:
  `TV_ISIN_GERMANY_REGIONAL_TARGET_FALLBACK`.
- Cross-venue bridges such as `TRADEGATE` now retry a primary source miss with
  exact TradingView `ISIN + the same reviewed source MIC`.  That source result
  must still share exactly one `shareClassFIGI` with the target.  New mappings:
  `ISIN_SOURCE_SHARE_CLASS_BRIDGE` and
  `ISIN_SOURCE_REGIONAL_SHARE_CLASS_BRIDGE`.
- The former Yahoo-failure regional diagnostic is now production-capable, but
  only for the exact evidence class proven by the audit; conflicting
  shareClassFIGIs and missing source/security proof remain fail-closed.
- Existing UK/Swiss policies and reviewed exceptions are unchanged.
- Key counters:
  `openfigi_bridge_source_isin_fallback_*`,
  `bridge_source_isin_fallback_matches*`,
  `yahoo_failure_regional_fallback_matches*`,
  `tv_isin_germany_regional_target_fallback_matches*`.
- Resolver policy: `0.3.44-policy44`. Regression suite: 122 tests.


## v0.3.43 — rejection evidence audit (no admission-policy change)

This is an audit-only utility release. Resolver admission remains exactly
`0.3.42-policy42`, so the Germany `3978 VERIFIED / 22 REJECTED` baseline is
directly comparable.

- Adds `run --rejection-audit <path.jsonl>`.
- For every rejected row, writes exact TradingView identity fields, current
  resolver mapping, bounded source/regional MIC probes, OpenFIGI FIGI /
  compositeFIGI / shareClassFIGI / security taxonomy, Yahoo symbol / venue /
  quoteType / currency / price, and ordinary-contract blockers.
- The audit performs evidence probes only; it never upgrades a rejected row or
  changes production bindings.
- Fixed and regression-tested the Yahoo venue compatibility call used by the
  audit path.

## v0.3.42 — German exact-ISIN same-venue proof + bounded Yahoo fund-taxonomy anomaly

The Germany top-4000 audit reduced the remaining failures to exact repeated
security groups.  v0.3.42 strengthens evidence before relaxing any Yahoo
metadata rule.

- Reviewed direct German prefixes (`FWB`, `DUS`, `HAM`, `SWB`, `MUN`, `HAN`)
  now retry an exhausted `ID_EXCH_SYMBOL + MIC` lookup with exact TradingView
  `ISIN + the same MIC`.  A successful result uses
  `TV_ISIN_SAME_VENUE_FALLBACK`; no FIGI or venue is fabricated.
- An OpenFIGI-backed German regional common-stock/REIT identity may tolerate
  Yahoo `quoteType=MUTUALFUND` or `ETF` only when Yahoo returns the exact bounded
  symbol, explicit matching currency, and explicit compatible German regional
  venue.  Yahoo-only strict fallbacks are never eligible for this taxonomy
  exception.
- This also aligns missing Yahoo currency with the existing non-US contract: once
  exact `ISIN + MIC` has independently proven the listing, missing Yahoo currency
  is absence of corroboration rather than a contradiction.
- Remaining German `YAHOO_NO_MATCH` / strict missing-currency rows get a
  diagnostic-only alternate-regional probe across `XFRA/XSTU/XMUN/XHAN/XDUS/XHAM`.
  These probes never upgrade the row in v0.3.42; they only measure whether a
  stronger alternate quote target exists for the next policy step.

Key counters include `openfigi_german_direct_isin_fallback_*`,
`yahoo_germany_regional_fund_taxonomy_*`, and
`yahoo_failure_regional_probe_*`.


## v0.3.41 — Germany evidence-gated regional target routing

The live v0.3.40 Germany audit proved that Xetra is not a universal Yahoo/OpenFIGI target for the remaining bridge rows. Across 457 rows with no Xetra target, exact-ISIN regional probes found 2,129 OpenFIGI venue candidates and Yahoo validated 1,980 of them; 440/457 rows had at least one valid regional Yahoo target, while most had several.

- Regional probes across `XFRA`, `XSTU`, `XMUN`, `XHAN`, `XDUS`, and `XHAM` can now create production bindings instead of telemetry only. Every candidate still requires exact `ID_ISIN + MIC`, compatible OpenFIGI security type, a bounded Yahoo suffix, and normal Yahoo currency/type/venue validation.
- Multiple valid regional venues are treated as quote-target alternatives for the **same exact ISIN**, not as an identity ambiguity. A fixed MIC priority selects one target only after security consistency is proven. Explicitly conflicting non-null `shareClassFIGI` values remain fail-closed.
- `GETTEX` and `TRADEGATE` retain source-side protection: a regional target is admissible only when its non-null `shareClassFIGI` matches exactly one source listing. No source venue is guessed.
- `LSX` and `LS` retain the reviewed one-sided exact-ISIN rule established for Xetra: when OpenFIGI lacks the single reviewed source MIC (`HAML`/`LSSI`), TradingView's exact ISIN plus an independently proven regional target may bind without fabricating a source venue FIGI.
- New mapping methods: `TV_ISIN_REGIONAL_TARGET_BRIDGE`, `ISIN_REGIONAL_SHARE_CLASS_BRIDGE`, and `REGIONAL_SHARE_CLASS_BRIDGE`. Warm-cache quote refresh uses the normal cached target-MIC contract.
- Added production telemetry `regional_target_bridge_matches*`, `regional_target_bridge_multi_mic_matches*`, `tv_isin_regional_target_bridge_matches*`, `regional_share_class_bridge_matches*`, and bounded failure counters for source proof/share-class/security ambiguity.
- Resolver policy: `0.3.41-policy41`. Regression suite: 109 tests.

## v0.3.40 — Germany regional-target diagnostics

- The live v0.3.39 Germany run proved that `ID_WERTPAPIER + XETR` does not rescue the remaining LSX/LS target gaps: `0/253` matches. The WKN-to-Xetra fallback is therefore removed rather than retained as dead provider traffic.
- For bridge rows with no Xetra target, v0.3.40 performs a diagnostic-only exact-ISIN probe across the German regional venues already supported by the resolver: `XFRA`, `XSTU`, `XMUN`, `XHAN`, `XDUS`, `XHAM`.
- Any unambiguous regional OpenFIGI result is converted to its bounded Yahoo suffix (`.F`, `.SG`, `.MU`, `.HA`, `.DU`, `.HM`) and checked with the normal currency/type/venue contract. Results are telemetry only and **never create VERIFIED bindings** in this version.
- New stats distinguish OpenFIGI regional coverage from Yahoo-valid production targets, including per-prefix/per-MIC counts and unique-vs-multiple target rows.
- Resolver policy: `0.3.40-policy40`.

## v0.3.39 — historical WKN-to-Xetra experiment (removed in v0.3.40)

The v0.3.38 Germany live audit proved that Bloomberg-style `exchCode=GY` is not a usable Mapping API fallback for these Xetra targets: all **457/457** scoped fallback jobs returned no compatible identity. That path is removed rather than kept as dead traffic.

- For `LSX` and `LS` only, when the primary `ID_ISIN + micCode=XETR` target lookup is empty and the TradingView venue symbol has the strict six-character WKN shape, the resolver retries the target as `ID_WERTPAPIER + micCode=XETR`. OpenFIGI documents `ID_WERTPAPIER` as the German Wertpapierkennnummer identifier.
- This is not generic ticker rewriting. TradingView exposes WKN-style symbols on these namespaces (for example `LSX:BASF11` and `LS:887915`), and OpenFIGI itself must recognize the exact six-character value as `ID_WERTPAPIER` at Xetra before it can participate in resolution.
- If the source venue OpenFIGI identity exists, the WKN-derived Xetra target must still share exactly one non-empty `shareClassFIGI` with that source before Yahoo is consulted (`ISIN_WKN_SHARE_CLASS_BRIDGE`).
- If `LSX -> HAML` or `LS -> LSSI` remains unindexed at OpenFIGI, the existing one-sided source policy may use the exact WKN-derived Xetra target (`TV_WKN_TARGET_BRIDGE`), preserving the reviewed source MIC while leaving `source_venue_figi=null`. GETTEX and TRADEGATE do **not** receive this shortcut.
- Added stats `openfigi_wkn_target_fallback_jobs/matches/no_match`, per-prefix variants, `tv_wkn_target_bridge_matches*`, and `isin_wkn_share_class_bridge_matches*`.
- Resolver policy: `0.3.39-policy39`.
- Regression suite: 104 tests.


## v0.3.38 — Xetra OpenFIGI exchange-code target fallback (superseded)

- Keeps `micCode=XETR` as the primary OpenFIGI target proof. If that exact target returns no compatible identity for a German cross-venue bridge, the resolver performs one second **scoped Xetra** lookup using Bloomberg/OpenFIGI `exchCode=GY`. OpenFIGI's FIGI allocation rules explicitly show Xetra securities with the `GY` exchange code (for example `STM GY`), while Tradegate uses `TH`.
- For `GETTEX` / `LSX` / `LS`, the fallback remains `ID_ISIN + exchCode=GY`; for ticker-based `TRADEGATE`, it remains exact `ID_EXCH_SYMBOL + exchCode=GY` with currency/type filters. No unscoped ticker inference is used.
- `target_mic` stays `XETR`. Mapping methods using this fallback are marked `*_XETRA_EXCHCODE` so cached provenance remains explicit. Existing share-class bridge requirements are unchanged; the one-sided `TV_ISIN_TARGET_BRIDGE` remains limited to reviewed single-source-MIC namespaces (`LSX`, `LS`). GETTEX still cannot guess between `MUNC` and `MUND`.
- Added stats `openfigi_xetra_exchcode_fallback_jobs`, `openfigi_xetra_exchcode_fallback_matches/no_match` and per-prefix variants.
- Resolver policy: `0.3.38-policy38`. The Germany-wide live run returned `openfigi_xetra_exchcode_fallback_no_match=457` and zero matches; v0.3.39 removes this fallback.

## v0.3.37 — one-sided TV-ISIN target bridge + duplicate Xetra collapse

The v0.3.36 Germany diagnostic showed that OpenFIGI knows every failed GETTEX/LSX/LS ISIN unscoped, but its venue coverage is asymmetric: all 432 LSX rows returned no `HAML` source row while many still returned an exact `ID_ISIN + XETR` target. This release uses that evidence without pretending OpenFIGI proved the missing source listing.

- For an ISIN bridge with **exactly one reviewed source MIC** (`LSX -> HAML`, `LS -> LSSI`), if the source-scoped OpenFIGI job is empty but `ID_ISIN + XETR` returns one unambiguous type-compatible target, the resolver may use `TV_ISIN_TARGET_BRIDGE`. TradingView supplies the source namespace + exact ISIN; OpenFIGI proves that same ISIN at Xetra; Yahoo must still validate the bounded `.DE` target. No source venue FIGI is fabricated.
- GETTEX deliberately does **not** receive this fallback because its provider namespace spans two source MICs (`MUNC` and `MUND`); if both source probes are absent the resolver cannot guess which segment applies.
- Duplicate Xetra rows from an ISIN bridge are collapsed only when every surviving row has the same non-null `shareClassFIGI` and the same normalized ticker. The collapsed target keeps no arbitrary venue FIGI. Any differing ticker/share class remains fail-closed as `OPENFIGI_TARGET_AMBIGUOUS`.
- Unresolved unscoped ISIN diagnostics now also report whether all compatible OpenFIGI rows expose one unique normalized ticker (`openfigi_isin_bridge_unscoped_unique_ticker*`) or conflicting/missing ticker metadata. This is telemetry only and does not create a binding.
- Resolver policy: `0.3.37-policy37`.
- Regression suite: 100 tests.

## v0.3.36 — Germany bridge diagnostics (no admission-policy relaxation)

- Keeps the v0.3.35 German venue model unchanged. No new instrument is admitted solely by this release.
- Adds bounded per-prefix bridge telemetry for `TRADEGATE`, `GETTEX`, `LSX`, and `LS`, separating true scoped OpenFIGI empties from post-filter type/symbol mismatches and reporting target ambiguity by prefix.
- For failed ISIN-gated `GETTEX`/`LSX`/`LS` bridges only, performs a diagnostic unscoped `ID_ISIN` lookup. It records whether OpenFIGI knows the security and whether all compatible rows share one `shareClassFIGI`; the result is telemetry only and cannot create a binding.
- Resolver policy: `0.3.36-policy36`.

## v0.3.35 — Germany venue expansion + ISIN-gated LS/gettex bridges

The first Germany market-only audit (`Limit=4000`) returned 2,283 `MIC_UNKNOWN` rows, exactly accounted for by six TradingView provider prefixes: GETTEX, LSX, LS, SWB, MUN and HAN. This release adds reviewed venue semantics without treating provider names as aliases for Xetra.

- Direct regional mappings: `SWB -> XSTU -> .SG`, `MUN -> XMUN -> .MU`, `HAN -> XHAN -> .HA`. Yahoo venue validation accepts only the corresponding Stuttgart/Munich/Hannover metadata (or the existing reviewed `de_market` missing-venue fallback).
- `GETTEX` is not collapsed to Munich/Xetra: official gettex MICs are `MUNC` (regulated) and `MUND` (open market).
- `LSX` uses source MIC `HAML` (LS Exchange); `LS` uses source MIC `LSSI` (Lang & Schwarz TradeCenter systematic internaliser).
- GETTEX/LSX/LS use `ISIN_SHARE_CLASS_BRIDGE` to Xetra. TradingView ISIN is queried at the exact source MIC(s) and at `XETR`; the resolver requires exactly one common non-empty `shareClassFIGI` before generating the Yahoo `.DE` target. This handles WKN-style TradingView symbols such as LSX `BASF11` without fuzzy ticker rewriting. Missing TradingView ISIN fails closed as `TV_ISIN_UNKNOWN`.
- Added stats `openfigi_isin_bridge_jobs` and `isin_bridge_share_class_matches`.
- Resolver policy: `0.3.35-policy35`.
- Regression suite: 93 tests.

The Germany coverage profile is still a *top-N audit* when TradingView reports `totalCount > Limit`; a separate pagination change should be validated only after venue semantics are stable.



## v0.3.34 — exact reviewed Yahoo YHD venue artifact

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


## v0.3.50 performance-only OpenFIGI memoization

`v0.3.50` keeps resolver policy `0.3.49-policy49` unchanged. During one
`BatchResolver.resolve()` run, identical OpenFIGI mapping jobs are canonicalized,
deduplicated and memoized in memory. Empty mappings are memoized too. The memo
is reset at the beginning of each resolver run and is never persisted, so this
changes network work only, not identity/admission semantics or cache TTLs.

Additional resolver stats report actual provider work:
`openfigi_provider_requested_jobs`, `openfigi_provider_network_jobs`,
`openfigi_provider_network_batches`, `openfigi_provider_memo_hits`, and
`openfigi_provider_intra_call_dedup_hits`.

## v0.3.52 performance-only security evidence reuse

`v0.3.52` keeps resolver policy `0.3.49-policy49` unchanged and is based on
`v0.3.50` (the experimental OpenFIGI transport concurrency from `v0.3.51` is
not included).

Two run-local performance changes preserve the existing admission contract:

1. German regional exact-ISIN evidence is grouped by exact ISIN before the
   bounded `XFRA/XSTU/XMUN/XHAN/XDUS/XHAM` probe. Raw OpenFIGI evidence for one
   `ID_ISIN + MIC` lookup is shared by all TradingView rows for that ISIN, while
   target selection and type/taxonomy checks remain row-specific.
2. Yahoo v7 positive quote rows are memoized within one resolver run. Missing
   symbols are deliberately not negative-cached, so the existing targeted retry
   for thin German listings remains a real network request.

Useful counters:

- `openfigi_regional_target_probe_security_groups`
- `openfigi_regional_target_probe_grouped_row_reuses`
- `openfigi_regional_target_probe_row_equivalent_jobs`
- `openfigi_regional_target_probe_jobs_saved_by_grouping`
- `yahoo_provider_requested_symbols`
- `yahoo_provider_network_symbols`
- `yahoo_provider_network_batches`
- `yahoo_provider_memo_hits`
- `yahoo_provider_missing_symbols`

The resolver policy/cache identity remains `0.3.49-policy49`; existing verified
bindings therefore remain compatible.
