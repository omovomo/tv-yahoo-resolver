# Identity Registry / garp-cli mapping contract — Phase A audit

Status: **Phase A contract complete; Phase B schema v1 foundation and the first Phase C TV -> Yahoo read/write path are implemented through package `0.4.78`; admission policy unchanged**.

Baseline inspected: package `0.4.76`, resolver policy `0.4.57-policy457`.

This document records the Phase A contract audit for the next architecture work.
It does not change VERIFIED/REJECTED admission, provider contracts, cache
compatibility, or production behavior.

## 1. Product objective

The primary product objective is a fast, deterministic, fail-closed identity
layer for `garp-cli`:

```text
TradingView listing/security <-> Yahoo symbol/listing <-> IBKR contract/security
```

The resolver is not optimized for a zero-REJECTED score. A correct unresolved or
REJECTED result is preferable to an unproven mapping.

Authority boundaries:

- TradingView is the Stock/TV_ETF screen identity and policy-data authority.
- Yahoo is a target listing/symbol for live/base-price routing after a successful
  TV screen and a market-enrichment provider for Portfolio/TLH.
- IBKR/Flex is the broker/ownership authority (`conid`, broker symbol, ISIN and
  available broker context).
- OpenFIGI and Finnhub are independent resolution/evidence providers; they are
  not the product-facing integration target.

The first application paths are:

1. `TV -> Yahoo` for Stock-screen live/base-price routing;
2. `IBKR -> Yahoo` for Portfolio/TLH market enrichment;
3. `IBKR -> TV` for reconciliation and optional TV policy/audit context;
4. reverse lookup only when identity is unique and independently proven.

No symbol-only fuzzy join is permitted between TV, Yahoo and IBKR.

## 2. Current implementation audit

### 2.1 Current resolver boundary

`BatchResolver.resolve()` already provides a batch-first internal core:

```text
list[TvRow] -> dict[tv_id, Binding]
```

It performs cache lookup first, resolves only misses, persists non-transient
results and retains the current fail-closed admission rules.

This is a suitable **internal producer** for proven TV -> Yahoo bindings, but it
is not yet an application-facing contract for `garp-cli`.

### 2.2 Current TV input is wider than the identity contract needs

`TvRow` currently contains:

```text
tv_id, prefix, symbol, name, currency, tv_type, type_specs,
sector, market_cap, close, isin, active_symbol
```

In the current resolver implementation:

- `sector`, `market_cap` and `close` are not used for identity admission;
- `name` is used only as auxiliary provider/candidate context in a few paths;
- `tv_id`, `prefix`, `symbol`, `currency`, `tv_type`, `type_specs` and especially
  `isin` are identity-relevant inputs;
- `active_symbol` is currently diagnostic/source-lifecycle evidence rather than
  a general positive admission proof.

Therefore the future public mapping API must not require a screener display
DataFrame or stock analytics fields merely to resolve identity.

### 2.3 Current `Binding` mixes several lifecycles

The current mutable `Binding` contains, in one object:

- TV source identity;
- Yahoo target identity;
- Finnhub/OpenFIGI evidence;
- source/target MIC and mapping method;
- runtime Yahoo price/delay/quote status;
- rejection reason;
- resolver policy/version and TTL timestamps;
- cache-hit state.

This is convenient for the standalone CLI but is too broad for a stable
cross-project API. In particular, runtime price freshness must not become part
of persistent identity validity.

### 2.4 Current SQLite binding cache is TV-keyed, not a Registry

The `bindings` table is currently keyed by:

```text
tv_id PRIMARY KEY
```

with a JSON payload plus status, TV currency/type, resolver version and expiry.
The lookup contract is one-directional: TV identity -> cached Binding.

Important consequences for the next architecture phase:

- there is no indexed Yahoo -> identity lookup;
- there is no ISIN/security index;
- there is no IBKR `conid` index or broker identity model;
- there is no canonical security record shared by multiple listings;
- there is no explicit relationship for ticker migration/successor/predecessor;
- multiple TV listings may legitimately map to one security or one Yahoo
  home-market route, so a future Registry cannot assume one-to-one symbols.

The current cache lookup validates resolver version compatibility plus TV
currency/type. It does not use current TV ISIN, `type_specs` or source lifecycle
state as lookup keys. In addition, `Binding` does not persist the source TV ISIN
itself. Therefore a complete canonical-security backfill cannot be reconstructed
safely from the legacy `bindings` table alone. Phase B/C migration must be
non-destructive and may need lazy promotion when a current `TvRow` supplies the
missing exact source evidence.

That is acceptable for the current bounded cache contract, but it is insufficient
as the only invalidation model for a long-lived Registry that must handle
corporate actions and ticker/listing migrations.

### 2.5 Identity and quote freshness are already partially separated

On a warm cache read, cached Yahoo price is explicitly cleared and marked stale.
`refresh_cached_quotes()` then refreshes only cached VERIFIED Yahoo symbols.
Provider unavailability can leave identity VERIFIED while quote status becomes
unavailable, while an explicit metadata contradiction can invalidate the
binding.

This is the correct architectural direction: **stable identity and runtime quote
freshness are separate concerns**.

For `garp-cli`, the public mapping contract should expose the proven Yahoo target
identity, not become a second live-price subsystem. Existing `garp-cli` Yahoo
preload/WebSocket logic should remain responsible for operational quote updates.

### 2.6 Current package has no stable application API

The package exposes the CLI and internal Python classes, but there is currently
no versioned public bulk mapping service/DTO boundary for another application.
`__init__.py` exposes only the package version.

`garp-cli` integration should therefore be added through one explicit mapping
boundary rather than importing CLI helpers or duplicating resolver logic.

### 2.7 Current source has no IBKR identity layer

There is no IBKR provider, `conid` model, IBKR lookup index or broker-ingest
contract in the current project.

The first IBKR phase should consume identifiers already available from the
`garp-cli` import layer. It must **not** add an IBKR network dependency merely to
claim integration.

## 3. Required public contracts

The exact Python names are implementation details for Phase C/D. The semantic
contract is fixed here.

### 3.1 TV identity input

Minimum application-facing TV input should be independent of the screener
DataFrame and contain only identity/lifecycle fields required by the resolver:

```text
request_id                 caller correlation key
qualified_tv_id            e.g. NASDAQ:MSFT
currency                   source-listing currency when known
tv_type                    TradingView type
type_specs                 normalized TradingView type specs
isin                       exact TV ISIN when available
name                       optional auxiliary context
active_symbol              optional source-lifecycle evidence
```

`prefix` and local `symbol` can be deterministically parsed from
`qualified_tv_id`; they do not need to be independently supplied unless the
implementation chooses to validate them redundantly.

Stock analytics/display fields such as score, RSI, market cap, close, sector and
`TVStockAssessment` presentation fields are outside the identity contract.

### 3.2 IBKR identity input

The initial broker-side contract should accept the strongest identifiers already
present in imported holdings/trades:

```text
request_id
conid                      optional but stable broker contract identifier
symbol                     broker symbol
isin                       exact security anchor when available
currency                   compatibility/evidence field
asset_class                STK / ETF / ADR when available
name                       optional diagnostic context
```

Additional broker venue/exchange identifiers should be added only if the actual
`garp-cli` import source exposes them reliably.

Rules:

- an already-known `conid` may be a direct Registry lookup key;
- exact ISIN may connect the broker record to a known security;
- broker symbol alone is not generic identity proof;
- currency/type are compatibility evidence, not identity anchors;
- if no proven Registry edge exists and exact evidence is insufficient, return
  unresolved rather than guessing a TV/Yahoo symbol.

### 3.3 Mapping result

Every requested row must get one deterministic result record. A missing row in
the response is not an acceptable unresolved representation.

The product-facing result should contain identity, not runtime market data:

```text
request_id
status                     VERIFIED / UNRESOLVED(or REJECTED)
security_id                internal Registry id when known
source_provider            TV or IBKR
source_identity            normalized source identifier
source_listing_id          Registry listing id when proven
yahoo_symbol               target symbol when VERIFIED
yahoo_listing_id           Registry Yahoo listing id when proven
tv_id                      target/source TV id when proven
ibkr_conid                  target/source broker contract when proven
isin                       canonical/exact ISIN when proven
source_mic
target_mic
mapping_method
resolver_policy
identity_fingerprint
validated_at
lifecycle_state
reason                     unresolved/rejection/conflict reason
cache_state                registry hit / resolver-produced / revalidated
```

Runtime fields such as Yahoo price, delay, pre/post market state or Stock-screen
fundamentals are deliberately absent.

The final implementation may split this into typed nested records, but the
semantics above must remain visible and testable.

### 3.4 Batch result / telemetry

A bulk call should return both per-row outcomes and aggregate operational
telemetry:

```text
requested
verified
unresolved
registry_hits
registry_misses
stale_or_incompatible
provider_calls
provider_jobs
provider_batches
revalidated
elapsed_ms
```

Telemetry must not influence admission. It exists to measure the real
`garp-cli` optimization target: compatible local hits and provider calls avoided.

## 4. Lookup semantics by product path

### 4.1 TV -> Yahoo

This is the first latency-sensitive path and should reuse the current resolver as
producer of proof.

Target behavior:

```text
exact TV identity input
  -> Registry indexed lookup
  -> if compatible VERIFIED hit: return Yahoo target locally
  -> else: current fail-closed resolver path
  -> on VERIFIED: write-through Registry
  -> return mapping result
```

The `garp-cli` Yahoo quote/live subsystem then consumes `yahoo_symbol`.

A quote refresh must not trigger full identity resolution merely because market
data TTL expired.

### 4.2 IBKR -> Yahoo

Preferred order:

```text
known conid Registry hit
  -> exact ISIN/security Registry match
  -> only then any evidence-gated unresolved-tail resolution
```

If one security has multiple possible Yahoo listings/routes and there is no
product rule proving the desired target, the result remains unresolved.

Portfolio ownership facts remain valid even if Yahoo is temporarily unavailable.
Provider availability failure must not rewrite broker identity.

### 4.3 IBKR -> TV

This is primarily reconciliation/audit/policy-context mapping.

Exact ISIN can prove security identity, but it does not by itself prove one
specific TradingView listing when multiple venues/listings exist. The Registry
must retain that distinction.

If more than one TV listing is compatible and there is no deterministic listing
selection contract, return an ambiguous/unresolved result rather than choosing a
ticker heuristically.

### 4.4 Reverse lookup

Yahoo -> TV or symbol -> broker reverse lookup is not a generic fuzzy service.
It is allowed only when Registry evidence makes the reverse edge unique under
the requested semantics.

## 5. Registry constraints derived from the current resolver

The future schema must support all of the following without flattening them into
one ticker:

1. one security with multiple source/target listings;
2. one TV listing mapped to a different Yahoo home-market listing;
3. multiple TV listings that legitimately converge on one Yahoo route;
4. security identity proven while source listing identity remains unproven;
5. provider symbol changes without changing the underlying security;
6. listing/venue migration without losing historical provenance;
7. policy-compatible VERIFIED evidence surviving a package/tooling release;
8. transient provider unavailability without permanent identity rejection;
9. explicit ambiguity/conflict as a first-class state;
10. current and historical provider identifiers without making stale symbols
    active again.

A normalized Registry therefore needs separate logical entities for at least:

- security/share class;
- listing/venue;
- provider identifier/contract;
- mapping/evidence edge;
- lifecycle/provenance state.

Package `0.4.77` implements the additive schema-v1 foundation with:

```text
registry_securities
registry_security_identifiers
registry_listings
registry_provider_identifiers
registry_mappings
```

The schema version is stored in `meta` as `identity_registry_schema_version=1`.
The tables are created beside the legacy cache. Package `0.4.78` adds write-through
for freshly resolved VERIFIED TV -> Yahoo proofs and an indexed Registry read path
before the legacy JSON cache. No legacy Binding is blindly backfilled: an old cache
payload is still insufficient to prove that its evidence belongs to the current
TV source snapshot.

## 6. Fingerprint and invalidation requirements

The current `Binding.fingerprint` is a resolver-output fingerprint built from
selected mapping fields and policy. It is useful for the standalone binding but
is not sufficient as the only long-lived source snapshot fingerprint.

The Registry design should distinguish at least:

- **identity evidence fingerprint** — what exact evidence proved the edge;
- **source snapshot fingerprint** — what caller/source identity fields were
  observed (including exact stable identifiers where available);
- **policy compatibility** — whether the proof may be reused by the current
  admission policy;
- **runtime market-data freshness** — explicitly separate.

A changed ISIN, conflicting source venue, proven corporate action or incompatible
policy must be able to invalidate/reverify an edge without depending on quote
TTL.

## 7. Phase A decisions

The following decisions are accepted for the next implementation phases:

1. Keep `BatchResolver` as the admission engine; do not duplicate its policy in
   `garp-cli`.
2. Add one versioned, batch-first application/library boundary around identity
   mapping.
3. Do not expose runtime Yahoo price as part of persistent identity mapping.
4. Do not make the public TV input depend on screener display/analytics fields.
5. Treat Registry as many-security/many-listing/many-provider-identifier graph,
   not `ticker -> ticker` dictionary.
6. Add IBKR initially from imported broker identifiers; no mandatory IBKR network
   dependency.
7. Exact ISIN proves security identity only; listing selection still requires
   listing evidence.
8. Warm compatible mappings should be served by indexed local lookup; provider
   work is for missing/stale/incompatible/conflict tails.
9. Preserve explicit ambiguity and unresolved states.
10. Keep existing fail-closed resolver admission unchanged during Registry
    plumbing/migration unless a separately reviewed functional policy change is
    intentionally made.

## 8. Phase C TV -> Yahoo Registry core implemented

Package `0.4.78` implements the first operational Registry path without changing
admission policy:

- fresh VERIFIED `TvRow + Binding` results write through to Registry;
- canonical security creation requires at least exact TV ISIN or a VERIFIED
  shareClassFIGI anchor; unanchored results remain in the legacy cache only;
- exact TV source fingerprints cover qualified id, prefix/symbol, currency, type,
  normalized type specs, ISIN and source active-state evidence;
- warm Registry reads require accepted policy, matching source fingerprint, ACTIVE
  lifecycle and verification age within the resolver identity TTL;
- more than one active compatible Yahoo target fails closed as ambiguous;
- an explicit runtime Yahoo metadata contradiction deactivates the Registry edge;
- a fresh non-transient cold-resolution REJECTED deactivates any older Registry
  VERIFIED edge for that TV id, while transient provider failures do not;
- old legacy JSON hits are not promoted automatically;
- many TV listings may share one proven Yahoo target/security; conflicting strong
  security anchors, multiple active ISIN/shareClass identifiers for one current
  security, or Yahoo-symbol ownership are skipped and counted as Registry conflicts
  rather than weakening identity.

Registry telemetry now distinguishes hits, misses, stale/incompatible rows,
ambiguity, write-through counts/conflicts and runtime invalidations.

## 9. Remaining Phase C/D work

The Registry core now supports the first access pattern below. Remaining work
should extend the same evidence/lifecycle model, in priority order:

```text
TV qualified id -> verified mapping edge -> Yahoo listing
IBKR conid       -> broker contract       -> security/listing edges
ISIN             -> security/share class  -> proven provider listings
Yahoo symbol     -> Yahoo listing         -> reverse edges (diagnostic/unique only)
```

Remaining deliverables:

- versioned public batch mapping DTO/service boundary for `garp-cli`;
- explicit product-facing mapping result/telemetry that does not expose mutable
  internal `Binding` or runtime Yahoo prices;
- IBKR `conid`/ISIN ingest plus `IBKR -> Yahoo` and `IBKR -> TV` lookups;
- lifecycle handling for symbol/listing migration and historical provider ids;
- bounded/lazy migration strategy for useful legacy bindings where current source
  evidence can independently re-establish the edge;
- performance measurements for real `garp-cli` screen/portfolio batch sizes and
  mixed hit/miss tails;
- no package policy bump unless VERIFIED/REJECTED semantics actually change.

The concrete `garp-cli` adapter and cross-project integration tests remain gated
on inspection of the actual relevant `garp-cli` source tree. The standalone
Registry/schema work does not need to wait for that adapter.
