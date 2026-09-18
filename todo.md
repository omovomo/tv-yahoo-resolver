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

Главная следующая architecture phase --- **Identity Registry + garp-cli mapping
contract**. Она имеет более высокий приоритет, чем дальнейшее уменьшение
residual market-level REJECTED без нового evidence.

Порядок работ:

1. зафиксировать product mapping contracts и authority boundaries для
   `TV -> Yahoo`, `IBKR -> Yahoo`, `IBKR <-> TV`;
2. спроектировать persistent Identity Registry, отделяющий stable security
   identity от listing/provider lifecycle;
3. сделать batch-first lookup API/indexes для hot paths `garp-cli`;
4. перенести текущие verified TV->Yahoo bindings в Registry/write-through model
   без ухудшения fail-closed admission;
5. добавить IBKR-side identity input (`conid`/ISIN/symbol + доступный context) и
   deterministic reconciliation;
6. измерить cold/warm mapping latency, cache/registry hit rate и число реально
   выполненных provider calls; только после measurements задавать performance
   targets/TTL;
7. после стабилизации standalone contract интегрировать его в `garp-cli`
   Screen/Portfolio/TLH boundaries и добавить cross-project integration tests.

Actual `garp-cli` source не входит в текущий archive, поэтому concrete adapter/API
integration должна проектироваться по его фактическому source, когда он будет
предоставлен. До этого здесь фиксируется contract, а не выдумывается реализация
чужого project tree.

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

Identity Registry теперь является основной planned architecture phase проекта,
потому что directly обслуживает product goal `TV <-> Yahoo <-> IBKR` в
`garp-cli`.

Это всё ещё НЕ implemented production policy и не должно внедряться побочно в
маленький rejection cleanup/rescue patch.

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

Конкретный Python API/CLI contract проектировать после inspection actual
`garp-cli` source.

======================================================================
51. IDENTITY REGISTRY --- SCHEMA CANDIDATES
==========================================

Schema должна быть normalized around identity/evidence, а не одним JSON blob с
единственным `tv_id` primary key. Возможные logical groups:

SECURITY

- canonical security record/internal id;
- ISIN;
- composite/share-class identifiers, где они доказаны и полезны.

TRADINGVIEW LISTING

- `tv_id`;
- prefix/symbol;
- source MIC/venue;
- currency/type;
- source fingerprint / last seen state.

YAHOO LISTING

- Yahoo symbol;
- exchange/MIC/market;
- currency/quote type;
- provider listing state.

IBKR IDENTITY

- `conid`;
- broker symbol;
- ISIN;
- currency;
- дополнительные broker identifiers только если реально доступны из import
  contract.

EVIDENCE / LIFECYCLE

- mapping method/evidence provenance;
- resolver/admission policy compatibility;
- first/last verified timestamps;
- last seen/check timestamps по provider;
- active/inactive/stale/conflict state;
- reason for unresolved/rejected mapping.

Это design candidates, не утверждённая schema. Не мигрировать current DB до
отдельного schema review и migration plan.

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

Рекомендуемая отдельная architecture sequence:

PHASE A --- CONTRACT AUDIT

- описать current `Binding`/SQLite semantics и actual resolver lookup flow;
- получить/inspect relevant `garp-cli` Screen/Portfolio/TLH integration source;
- определить minimal public mapping API и required identifiers.

PHASE B --- SCHEMA / MIGRATION DESIGN

- normalized Registry schema;
- indexes для TV/Yahoo/IBKR lookup keys;
- migration текущих verified bindings;
- compatibility с current cache;
- rollback/upgrade strategy.

PHASE C --- TV/YAHOO REGISTRY CORE

- current fail-closed resolver становится producer/write-through source
  доказанных TV->Yahoo bindings;
- warm reads обслуживаются Registry;
- no admission weakening.

PHASE D --- IBKR IDENTITY INGEST / RECONCILIATION

- принимать broker identity record из existing import layer;
- exact identifiers first (`conid`, ISIN);
- symbol-based path только с достаточным context/evidence;
- ambiguity/conflict остаются unresolved/REJECTED.

PHASE E --- GARP-CLI INTEGRATION

- Stock screen: bulk `TV -> Yahoo` mapping после успешного TV assessment;
- Portfolio/TLH: bulk `IBKR -> Yahoo`;
- optional policy/audit context: `IBKR -> TV`;
- native TV_ETF mapping включать отдельно, когда будет определён его live-price
  contract; не наследовать Stock semantics автоматически.

PHASE F --- PERFORMANCE / LIFECYCLE HARDENING

- cold/warm/mixed benchmarks;
- provider-call telemetry;
- invalidation/reverification;
- corporate action/delisting/ticker-migration tests;
- concurrency/locking/migration tests;
- bounded real-provider validation для новых provider contracts.

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
