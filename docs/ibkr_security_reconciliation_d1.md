# Phase D1 — IBKR/Flex security reconciliation (read-only)

**Package:** `0.4.81` · **Admission policy:** `0.4.57-policy457` (unchanged).

This is an evidence-only application boundary for the existing IBKR Flex import
identifiers (`conid`, `symbol`, `isin`, `currency`, `asset_class`). No IBKR API,
Yahoo API, or TradingView network call is used. No positions, lots, transactions,
price feeds, existing cache bindings, or Registry tables are modified.

## Evidence contract

- `conid` is a broker identifier from Flex, **not yet** a separately verified
  Registry linkage. `conid_verified` is always `false` in Phase D1.
- Exact broker `isin` is required for an on-demand security match. Neither the
  broker symbol nor a coincidental currency match can replace it.
- Registry must already contain an **active**, independently VERIFIED,
  current-policy-compatible, non-expired TV → Yahoo edge with an exact matching
  TV source ISIN and internally consistent source identity fingerprint.
- The result `SECURITY_MATCH` means *the broker ISIN and Registry security
  identifier match*. It does **not** prove that the IBKR contract is listed on
  a particular TV venue or that any Yahoo symbol is valid for Portfolio pricing.
- `tv_candidates` and `yahoo_candidates` are **informational only**. Even a
  one-element list is not a VERIFIED listing route. Consumers **MUST NOT**
  populate price subscriptions from them.
- `yahoo_symbol` and `tv_id` always remain `null` and `listing_verified=false`.
- Missing ISIN, legacy-only evidence, stale/incompatible evidence, and missing
  current Registry evidence remain `UNRESOLVED`. Contradictory ISIN claims for
  one `conid` within a batch are `CONFLICT` for all affected rows.
- Invalid input is rejected before any broker mapping. No symbol-only fallback.

The current 82k historical legacy `bindings` cannot safely populate the broker
security projection because they lack the complete TV source identity evidence.
Consequently, a Registry-empty production DB will return `UNRESOLVED`; this is
expected and must not trigger a blind migration or forced full-market refresh.

## JSONL CLI

After installing the updated project into its **own** Python environment:

```powershell
python -m pip install --no-deps -e .
tv-market-id-broker-map --help
```

A single JSONL input record (synthetic `conid`, for illustration only):

```json
{"request_id":"example-1","conid":"123456","symbol":"MSFT","isin":"US5949181045","currency":"USD","asset_class":"STK"}
```

Run from project Git root using `--input` / `--output` paths under `./out/`:

```powershell
tv-market-id-broker-map `
  --cache .\cache\identity.sqlite3 `
  --input .\out\ibkr_security_requests.jsonl `
  --output .\out\ibkr_security_results.jsonl `
  --telemetry
```

The CLI opens the existing SQLite database with `mode=ro` and returns one result
per input. The JSONL contract is version `1` **separate** from the existing
`tv-market-id-map` TV→Yahoo API v1; existing consumers remain unchanged.

### Follow-up (D2, not yet implemented)

Persist actual broker `conid` observations with explicit provenance and
idempotent conflict/lifecycle handling, then prove a broker **listing**/target
route through independent IBKR venue/contract evidence. Only after that should
`garp-cli` consume a VERIFIED `IBKR → Yahoo` price-enrichment mapping.
No automatic Portfolio/TLH routing changes are included in D1.
