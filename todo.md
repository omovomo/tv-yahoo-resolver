# TODO / PROJECT BACKLOG

Этот файл является tracked backlog проекта `tv-market-identity-prototype`.

Он хранит отложенные задачи, architecture bookmarks и research follow-ups,
которые ещё НЕ являются implemented production policy.

Правила:

- `todo.md` является source of truth для project bookmarks/backlog;
- MASTER PROMPT хранит правила работы с backlog, но не дублирует его содержимое;
- наличие пункта в `todo.md` НЕ означает, что его нужно реализовывать автоматически;
- перед началом backlog-задачи сначала проверить actual committed source и актуальность evidence;
- completed/obsolete пункты обновлять или удалять отдельным обычным Git patch вместе с необходимым context;
- не превращать TODO/hypothesis в admission policy без discovery, tests и required REAL-provider gates.

## Product objective / current architecture priority

Главная продуктовая цель проекта --- не самостоятельное уменьшение числа
`REJECTED`, а быстрый deterministic fail-closed identity mapping для рабочего
`garp-cli`:

`TradingView listing/security <-> Yahoo symbol/listing <-> IBKR identity`.

Product-facing identity spaces:

- **TradingView** --- authority для Stock/TV_ETF screen identity и source listing;
- **Yahoo** --- target symbol/listing для live/base-price path после успешного TV
  screen и market-enrichment provider для Portfolio/TLH;
- **IBKR** --- broker identity/ownership side (`conid`, `symbol`, `isin`, currency и
  доступные broker identifiers из Flex/import layer).

OpenFIGI и Finnhub остаются важными независимыми evidence/resolution providers,
но не являются самостоятельной product integration goal.

Архитектура должна поддерживать прежде всего следующие application paths:

1. `TV -> Yahoo` --- latency-sensitive batch mapping после успешного Stock screen;
2. `IBKR -> Yahoo` --- Portfolio/TLH enrichment без повторного угадывания ticker;
3. `IBKR <-> TV` --- deterministic reconciliation/audit и привязка portfolio
   position к TV assessment/policy context;
4. reverse lookup допустим только при unique/proven identity, не как fuzzy ticker
   search.

Source-authority boundaries сохраняются:

- Yahoo не становится вторым stock screener или policy/fundamental authority;
- IBKR/Flex остаётся authority для фактов владения/сделок, а не TradingView;
- native `TV_ETF` route остаётся отдельным от Stock semantics;
- быстрый mapping не должен ослаблять security/listing/provider-symbol identity
  checks.

Optimization target: после однократного доказательства binding максимально
переиспользовать compatible persistent identity evidence и избегать повторных
provider calls. Coverage оптимизируется только внутри fail-closed invariants.

Текущий source пока не содержит production IBKR binding layer; это planned
architecture/integration work. Не добавлять IBKR network/API dependency только
ради самого факта интеграции: сначала использовать уже доступные broker
identifiers из import layer и определить минимальный доказуемый contract.

## Active architecture / product plan

Current implementation state after package `0.4.81`
(`0.4.57-policy457`, admission unchanged):

- **Phase A / contract audit — COMPLETE**: product authority boundaries and the
  actual targeted `garp-cli` identity slice are inspected.
- **Phase B / schema foundation — COMPLETE**: additive normalized Registry schema
  v1 exists beside legacy cache; no blind promotion of old bindings.
- **Phase C / TV->Yahoo Registry core — COMPLETE FOUNDATION**: verified mappings
  write through to Registry and compatible warm reads are indexed/fail-closed.
- **Application mapping boundary — IMPLEMENTED**: `tv_market_identity.api`,
  lightweight `tv-market-id-map` process transport, plus `map-jsonl` compatibility
  subcommand. Warm Registry hits do not construct provider clients/resolver.
- **Application legacy fast path — IMPLEMENTED (`0.4.80`)**: Registry miss
  first checks eligible verified/current-policy legacy bindings in bulk,
  without constructing resolver/providers. Source API v1 stays compatible;
  telemetry distinguishes fast legacy hits. Registry remains unpopulated by
  legacy-only results; its security evidence is not fabricated.
- **Phase D1 / IBKR ISIN security reconciliation — IMPLEMENTED (`0.4.81`)**:
  read-only broker JSONL batch API (`tv-market-id-broker-map`), exact broker
  ISIN → current proven Registry security evidence, and informational TV/Yahoo
  candidates only; **no verified broker listing route or persisted conid**.
- **Phase D2 / IBKR conid lifecycle and listing evidence — PENDING**.

Targeted `garp-cli` source inspection identified the historical
`StockYahooSymbolRegistry` + `YahooMetadataVerifier` identity-admission path.
The subsequent `garp-cli` authority migration removed its manual/metadata
admission role while retaining immutable `StockYahooLivePlan`/row-token/session
safety. The user's October 2026 bounded AAPL/IBM smoke confirmed real
TV->Yahoo VERIFIED results and Yahoo WebSocket quote updates. The remaining
integration gate is a full `garp-cli` regression suite and warm/mixed performance
verification on its actual runtime, not another manual authority path.

Confirmed integration constraints:

- Stock screen now carries strict TV identity inputs
  (`currency`, `type`, `typespecs`, `isin`, `active_symbol`); bounded AAPL/IBM
  real-provider smoke passed;
- `garp-cli` pins `yfinance==1.5.1`, while this package currently requires
  `yfinance>=1.7,<1.8`; direct in-process dependency is therefore not the first
  migration path;
- first integration transport should use the isolated versioned batch process
  boundary rather than copying resolver logic or weakening dependency contracts.

Следующий приоритет работ:

1. **Phase C2 / garp-cli authority migration — BOUNDED SMOKE PASS**:
   strict TV identity fields, verified batch mapping and Yahoo live quotes
   were confirmed for AAPL/IBM; full application suite remains a separate gate;
2. keep the historical `StockYahooSymbolRegistry` admission retired;
   do not restore manual or Yahoo-metadata authority;
3. **Warm-cache performance gate — PASS for 2/100/700 on Windows**:
   0.4.80 p50 ~155/153/186 ms (previously ~1386/1349/1444 ms),
   `resolver_invocations=0` with fully compatible legacy hits. Mixed/cold-tail
   benchmarks with independent provider evidence remain pending;
4. **Phase D2**: add durable IBKR conid observations and independent broker
   listing/venue evidence, then VERIFIED `IBKR -> Yahoo` / `IBKR -> TV` routes;
5. **Phase F**: lifecycle/performance hardening --- corporate actions, ticker/venue
   migration, invalidation/reverification, concurrency/locking and schema migrations.

Residual market-level REJECTED остаются вторичным приоритетом и открываются только
при новом generic evidence/regression, а не ради уменьшения counts.

## Active research

Сейчас нет активных market-level admission-задач из уже исследованных рынков. Закрытые рынки не открывать заново без нового независимого provider evidence.

## Closed / waiting for new evidence

Исследованные рынки (production baselines от 2026-09-18; provider universe может дрейфовать):

- **US / America** — CLOSED / WAITING FOR NEW EVIDENCE. Full universe: `19942`; `19142 VERIFIED`, `800 REJECTED`; verified subtypes included `5564 ETP` and `380 Closed-End Fund`. Residual Yahoo/Finnhub taxonomy, venue, currency and missing-listing cohorts уже исследованы; не открывать их заново без нового independent evidence.
- **Germany** — CLOSED / WAITING FOR NEW EVIDENCE. Full universe после policy `0.4.57-policy457`: `37233`; `36964 VERIFIED`, `269 REJECTED`. Для исходного 409-row `XETR fund/etf + Yahoo EQUITY` cohort scoped `ID_ISIN + XETR` доказал source listing для `395`, и ровно эти `395` были safely rescued; оставшиеся `14` source-unconfirmed строк остались `YAHOO_TYPE_MISMATCH:EQUITY`. Не расширять XETR rule без нового evidence.
- **UK** — CLOSED / WAITING FOR NEW EVIDENCE. Full universe: `9456`; `9152 VERIFIED`, `304 REJECTED`. Coverage config теперь использует `Limit = 10000` и `RequireCompleteUniverse = true`. Fresh-cache bounded diagnostic для LSE ETF Yahoo-`EQUITY` cohort дал `0/6` scoped `ID_ISIN + XLON` source proofs; Germany/XETR rule на UK не переносить.
- **Switzerland** — CLOSED / WAITING FOR NEW EVIDENCE. Full universe: `3379`; `1836 VERIFIED`, `1543 REJECTED`. Основной residual — Yahoo listing-route coverage: `1255 YAHOO_NO_MATCH` и `234 YAHOO_SUFFIX_UNKNOWN:XBRN`. Fresh-cache BX probe подтвердил XBRN source identities при отсутствии reviewed Yahoo BX route; cross-venue SIX/Germany/London candidates не являются source-listing proof.
- **Korea** — CLOSED / WAITING FOR NEW EVIDENCE. Full universe: `4312`; `4203 VERIFIED`, `109 REJECTED`. Из них `90 YAHOO_SUFFIX_UNKNOWN:XKON`; fresh-cache probe однозначно доказал `6 XKON`, `1 XKOS`, `1 XKRX`, при этом Yahoo route существовал только для KOSDAQ/KOSPI controls. KONEX/XKON считать provider-coverage limitation до нового independent Yahoo/listing evidence.

Не считать наличие residual REJECTED само по себе основанием для повторного market research. Возвращаться к закрытому рынку только при новом generic provider evidence, новом reproducible regression или существенном изменении provider contract. Перед сравнением counts всегда сначала учитывать universe drift.


## Architecture bookmarks

49. ARCHITECTURE PRIORITY --- IDENTITY REGISTRY
==============================================

Identity Registry является основной architecture line проекта, потому что directly
обслуживает product goal `TV <-> Yahoo <-> IBKR` в `garp-cli`.

После package `0.4.78` Registry уже не только bookmark: schema-v1 foundation и
первый operational `TV -> Yahoo` read/write core реализованы. Это по-прежнему не
означает, что IBKR/public `garp-cli` integration уже существует, и Registry work
не должна смешиваться с unrelated rejection cleanup/rescue patch.

Registry должен разделять минимум три разных claims:

- SECURITY IDENTITY --- что это за security/share class;
- LISTING IDENTITY --- какая конкретная source/target venue listing;
- PROVIDER SYMBOL IDENTITY --- как TV/Yahoo/IBKR представляет security/listing.

И отдельно разделять:

- IDENTITY VALIDITY;
- PROVIDER/LISTING REFRESH LIFECYCLE;
- RUNTIME QUOTE/MARKET DATA freshness.

Цель Registry --- один раз доказать compatible binding, хранить evidence и
provenance, а затем быстро обслуживать batch lookups без полного дорогого
resolution на каждом application request.

======================================================================
50. IDENTITY REGISTRY --- PRODUCT CONTRACT / LOOKUPS
===================================================

Registry должен поддерживать batch-first application lookups:

- `TV qualified identity -> Yahoo symbol/listing`;
- `IBKR identity -> Yahoo symbol/listing`;
- `IBKR identity -> TV identity/listing`;
- proven unique reverse lookup там, где это действительно доказуемо.

IBKR-side input должен использовать сильнейшие доступные identifiers в таком
духе:

- `conid`, если он есть;
- exact ISIN как security anchor, если он есть;
- broker symbol только вместе с достаточным context/evidence;
- currency и другие broker fields как compatibility/evidence, а не как
  самостоятельное identity proof.

Нельзя делать symbol-only fuzzy join между TV/Yahoo/IBKR.

Для `garp-cli` desirable contract: один bulk request на набор identities,
результат на каждую строку содержит VERIFIED/REJECTED(or unresolved), target
identifiers, provenance/evidence, policy compatibility и lifecycle state.

Первый versioned contract реализован в package `0.4.79` через
`tv_market_identity.api` и lightweight process command `tv-market-id-map`.
Следующая работа --- application adapter и IBKR extension того же Registry.

======================================================================
51. IDENTITY REGISTRY --- SCHEMA / CURRENT STATE
==============================================

Schema v1 реализована additively и хранится рядом с legacy cache:

- `registry_securities`;
- `registry_security_identifiers`;
- `registry_listings`;
- `registry_provider_identifiers`;
- `registry_mappings`;
- `meta.identity_registry_schema_version = 1`.

Текущий `TV -> Yahoo` write-through создаёт canonical security только при наличии
сильного anchor из current resolution (`TV ISIN` и/или VERIFIED
`shareClassFIGI`). Security/listing/provider-symbol identity остаются раздельными.

Legacy `bindings` не backfill-ятся вслепую: старый JSON не сохраняет source
snapshot, достаточный для доказательства связи старого evidence с текущим TV
ISIN/type-spec state. Lazy/explicit migration допускается только при наличии
независимо проверяемого current source evidence.

Следующие schema/lifecycle задачи:

- IBKR provider identifiers (`conid` в первую очередь);
- explicit historical provider-id/ticker lifecycle;
- corporate-action/listing migration semantics;
- versioned schema migration/rollback tests;
- public lookup projection, не зависящая от mutable legacy `Binding`.

======================================================================
52. IDENTITY REGISTRY --- PERFORMANCE / CACHE PLAN
================================================

Performance goal должен измеряться на application-relevant workloads, а не
только на full-market production run.

Обязательные benchmark dimensions перед оптимизацией:

- cold resolver run;
- warm Registry lookup;
- mixed batch (mostly cached + small unresolved tail);
- `TV -> Yahoo` Stock-screen batch;
- `IBKR -> Yahoo` Portfolio ticker set;
- `IBKR -> TV` reconciliation batch;
- provider calls avoided/executed;
- registry/cache hit rate;
- latency distribution для batch, а не только total runtime.

Не задавать arbitrary millisecond SLO или TTL до measurements.

Preliminary synthetic local measurement для schema-v1 TV->Yahoo core
(package `0.4.78`; не production SLO и не provider benchmark):

- `700` Registry rows: write-through ~`0.17 s`, warm lookup ~`0.06 s`;
- `13,000` Registry rows: write-through ~`3.2 s`, warm lookup ~`1.2 s`.

Первый naive SQL join давал почти quadratic warm lookup и был заменён staged
indexed reads (`TV provider id -> mapping source index -> referenced targets`).
Эти numbers использовать только как локальный regression/reference до measurements
на actual `garp-cli` workloads.

Основной design target:

`warm compatible binding -> indexed local lookup`,

а provider resolution выполняется только для missing/stale/incompatible/conflict
cases. Не допускать N network calls на N rows, если provider поддерживает bulk
или локально индексируемый universe.

======================================================================
53. IDENTITY REGISTRY --- LIFECYCLE / STALE-WHILE-REVALIDATE
===========================================================

Registry должен помочь корректно обрабатывать:

- corporate actions;
- ticker changes;
- venue changes / exchange migrations;
- delisting / uplisting;
- stale provider IDs/symbols;
- inactive symbols;
- provider metadata drift;
- TradingView universe drift;
- temporary provider outages;
- re-verification;
- resolver/admission policy migrations.

Stable verified security identity не должна обязательно требовать полного
дорогого re-resolution при каждом quote/metadata refresh.

Отдельно рассмотреть stale-while-revalidate для compatible VERIFIED identity,
но stale state не должен скрывать:

- delisting;
- corporate action;
- venue migration;
- identity conflict;
- incompatible resolver policy.

Предварительные historical TTL hypotheses (`TV universe ~1d`, rejected retry
`~1d`, Yahoo/Finnhub metadata `~7d`, verified identity `~30d`, OpenFIGI identity
`~90d`) остаются только hypotheses. Не превращать их в constants без benchmark
и lifecycle design review.

======================================================================
54. IDENTITY REGISTRY --- IMPLEMENTATION PHASES / GATES
=====================================================

PHASE A --- CONTRACT AUDIT --- **COMPLETE**

- current `Binding`/SQLite/resolver flow audited;
- product mapping/authority contract documented;
- targeted actual `garp-cli` Screen/Portfolio/TLH identity source inspected.

PHASE B --- SCHEMA / MIGRATION FOUNDATION --- **COMPLETE**

- normalized Registry schema v1 + indexes;
- additive coexistence with legacy cache;
- idempotent creation/future-schema fail-closed tests;
- no blind legacy backfill.

PHASE C --- TV/YAHOO REGISTRY CORE / PUBLIC BOUNDARY --- **COMPLETE FOUNDATION**

- current fail-closed resolver is producer/write-through source;
- indexed warm Registry reads precede legacy JSON cache;
- exact source fingerprint + policy + lifecycle + age compatibility;
- ambiguity/conflict fail closed;
- fresh persistent REJECTED/runtime contradiction invalidates older Registry edge;
- package `0.4.79` exposes narrow application DTO/service contract;
- lightweight `tv-market-id-map` loads resolver/providers only for unresolved tail.

PHASE C2 --- GARP-CLI AUTHORITY MIGRATION --- **NEXT**

- extend TV assessment query/sidecar with identity-only fields required by the
  strict contract (`currency`, `type`, `typespecs`, `isin`, `active_symbol`);
- add one bulk process adapter to `tv-market-id-map`;
- construct `StockYahooLivePlan` only from VERIFIED authority results;
- retire `StockYahooSymbolRegistry` and `YahooMetadataVerifier` from identity
  authority, preserving only temporary compatibility/migration state if needed;
- manual map may remain diagnostics/migration input but not live identity proof;
- preserve existing row-token, generation, duplicate-target and session safety;
- add cross-project warm/miss/reject/invalidation tests.

PHASE D --- IBKR IDENTITY INGEST / RECONCILIATION --- **D1 COMPLETE / D2 PENDING**

- D1: broker identity JSONL record (`conid`, `symbol`, `isin`, `currency`, `asset_class`)
  принят read-only; exact ISIN сопоставляется с independently VERIFIED
  Registry security anchor, а не с legacy bindings;
- D1: `SECURITY_MATCH` не означает доказанный broker listing или Yahoo
  price route; TV/Yahoo candidates остаются informational only;
- D2: durable broker conid lifecycle/provenance + independent broker
  venue/contract proof (в существующем Flex trade importer MIC отсутствует);
- D2: только после такого proof разрешить verified IBKR->Yahoo/TV mapping;
- symbol-based fallback, ambiguity и конфликтующие ISIN остаются fail-closed.

PHASE E --- GARP-CLI INTEGRATION --- **PENDING**

- Stock screen: bulk `TV -> Yahoo` mapping после успешного TV assessment;
- Portfolio/TLH: bulk `IBKR -> Yahoo`;
- optional policy/audit context: `IBKR -> TV`;
- native TV_ETF mapping включать отдельно, когда будет определён его live-price
  contract; не наследовать Stock semantics автоматически.

PHASE F --- PERFORMANCE / LIFECYCLE HARDENING --- **PARTIAL / NEXT AFTER INTEGRATION**

- preliminary synthetic Registry benchmark уже есть, но real `garp-cli` workload
  measurements ещё нужны;
- далее provider-call telemetry, invalidation/reverification, corporate action /
  delisting / ticker migration, concurrency/locking/migration tests;
- bounded real-provider validation нужен только для действительно нового/изменённого
  provider contract.

Каждая phase --- отдельный reviewable change. Не смешивать Registry migration,
IBKR integration и unrelated resolver rescue в один patch.

======================================================================
55. ARCHITECTURE BOOKMARK --- CACHE / DATA LIFECYCLE
===================================================

Отдельно различать как минимум:

- stable security identity;
- listing/provider-symbol identity;
- provider metadata;
- universe snapshot;
- runtime quote/live price;
- historical market data;
- rejection/unresolved evidence.

У них разные freshness/invalidation semantics.

Особенно не смешивать identity cache с application quote caches:

- `garp-cli` Yahoo quote TTL (regular/pre-post/closed/unknown) относится к market
  data freshness;
- Registry TTL/reverification относится к доказанности identity/listing;
- TV `_TV_CACHE` / `_TV_ETF_CACHE` относятся к screener snapshot semantics.

Не использовать один глобальный TTL и не заставлять quote refresh заново
разрешать stable identity.

======================================================================
56. ARCHITECTURE BOOKMARK --- COMPREHENSIVE DIAGNOSTICS / TELEMETRY
=================================================================

Сохранять один comprehensive rejection/mapping audit вместо цикла одноразовых
boolean probes.

Для product integration дополнительно нужны aggregate diagnostics:

- Registry hit/miss/incompatible/stale counts;
- mappings served without provider calls;
- provider calls/jobs/batches actually executed;
- `TV -> Yahoo`, `IBKR -> Yahoo`, `IBKR -> TV` outcomes;
- ambiguous/conflict/unresolved reasons;
- migration/reverification counts;
- cold/warm/mixed batch timing;
- provider/universe drift отдельно от resolver decision drift.

Diagnostics не являются admission evidence сами по себе. Новое diagnostic поле
добавлять только для generic research/operations question.

======================================================================
57. ARCHITECTURE BOOKMARK --- REPRODUCIBILITY / CROSS-PROJECT CONTRACT
====================================================================

Постоянная цель:

SOURCE / TEST / INTEGRATION REPRODUCIBILITY.

Для `tv-market-id` сохраняются:

Git HEAD = source of truth

git archive HEAD = inter-chat source transport

Git patch = modification transport

tests = self-contained

runtime state = отдельно

generated artifacts = not tracked

Для будущей интеграции с `garp-cli` additionally:

- не копировать resolver logic внутрь `garp-cli`;
- иметь один versioned mapping contract/library boundary;
- integration tests должны фиксировать authority boundaries и fail-closed
  behavior;
- изменения одного project не реконструировать по памяти другого --- для
  implementation нужен actual source обоих relevant trees.

Не возвращаться к source ZIP overlay workflow.

======================================================================
58. ARCHITECTURE BOOKMARK --- PROVIDER / SECURITY LIFECYCLE
=========================================================

Lifecycle architecture должна отличать:

security disappeared from provider

от

security identity invalid

и:

temporary provider outage

от

delisting / venue migration / symbol migration.

Это важно для:

- Registry validity;
- cache/retries;
- rejection/unresolved semantics;
- provider refresh policy;
- `garp-cli` ability продолжать использовать last compatible verified binding
  там, где это безопасно.

OpenFIGI/Finnhub/Yahoo provider lifecycle не должен автоматически менять broker
ownership facts из IBKR import и не должен превращать временную недоступность
provider в permanent identity rejection.

Не реализовывать эту architecture неявно через отдельные rescue exceptions.

======================================================================
