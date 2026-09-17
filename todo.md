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

## Active research

### Korea residual analysis

Статус baseline после v0.4.68 / `0.4.54-policy454`:

- TradingView Korea universe: 2753;
- VERIFIED: 2661;
- REJECTED: 92;
- 91 × `OPENFIGI_KOREA_SEGMENT_NO_MATCH:XKRX:OPENFIGI_NO_MATCH|XKOS:OPENFIGI_NO_MATCH`;
- 1 × `YAHOO_TYPE_MISMATCH:MUTUALFUND`.

Следующая research-задача:

- не считать 92 REJECTED автоматически окончательным результатом;
- приоритетно исследовать ~90-row KONEX cohort;
- искать generic, deterministic, independently evidenced target-resolution path для `XKON`;
- source venue `XKON` уже подтверждён representative exact `ID_ISIN+MIC` probes;
- `.KS` / `.KQ` НЕ являются доказанным Yahoo target contract для KONEX: representative probes возвращали `MUTUALFUND`;
- не добавлять `XKON → .KS/.KQ` без нового provider evidence;
- сначала discovery/probes, затем bounded REAL-provider smoke; admission change только после доказанного contract;
- `094800` и `169670` сохранять fail-closed, пока не появится новый generic evidence;
- не использовать per-ticker exceptions ради уменьшения REJECTED.

## Architecture bookmarks

49. ARCHITECTURE BOOKMARK --- IDENTITY REGISTRY
=============================================

ЭТО ОТЛОЖЕННАЯ АРХИТЕКТУРНАЯ ЗАКЛАДКА.

Она НЕ является текущей implemented policy.

Не реализовывать автоматически во время обычного rejection cleanup.

Будущая отдельная architecture phase:

IDENTITY REGISTRY

Главная идея:

разделить

IDENTITY VALIDITY

и

PROVIDER / LISTING REFRESH LIFECYCLE.

======================================================================
50. IDENTITY REGISTRY --- ЗАДАЧИ ==============================

Будущий Registry должен помочь корректно обрабатывать:

-   corporate actions;

-   ticker changes;

-   venue changes;

-   exchange migrations;

-   delisting;

-   uplisting;

-   stale provider IDs;

-   stale symbols;

-   inactive symbols;

-   provider metadata drift;

-   TradingView universe drift;

-   temporary provider outages;

-   re-verification;

-   resolver policy migrations.

Доказанная stable identity не должна обязательно требовать полного
дорогого identity resolution при каждом provider refresh.

Но provider/listing state должен обновляться независимо.

======================================================================
51. IDENTITY REGISTRY --- POTENTIAL FIELDS
========================================

Potential lifecycle fields:

first_verified_at

last_verified_at

last_seen_tv_at

last_provider_check_at

resolver_policy

Это design candidates, а не утверждённая schema.

======================================================================
52. IDENTITY REGISTRY --- TTL HYPOTHESES
======================================

Предварительные architectural hypotheses:

TradingView universe \~ 1 day

REJECTED retry \~ 1 day

Yahoo/Finnhub metadata \~ 7 days

VERIFIED identity \~ 30 days

OpenFIGI identity \~ 90 days

ЭТО НЕ УТВЕРЖДЁННАЯ POLICY.

Не реализовывать эти значения как constants без отдельного design
review.

======================================================================
53. IDENTITY REGISTRY --- STALE-WHILE-REVALIDATE
==============================================

Отдельно рассмотреть:

stale-while-revalidate

Идея потенциально полезна для stable VERIFIED identity.

Но stale state не должен скрывать:

-   delisting;

-   corporate action;

-   venue migration;

-   identity conflict;

-   incompatible resolver policy.

Это отдельная architecture problem.

======================================================================
54. IDENTITY REGISTRY --- ПЕРЕД IMPLEMENTATION
============================================

Перед реализацией отдельно спроектировать:

-   schema;

-   migration;

-   cache compatibility;

-   policy compatibility;

-   invalidation;

-   delisting handling;

-   uplisting handling;

-   ticker migration;

-   venue migration;

-   corporate actions;

-   stale identity detection;

-   provider failure handling;

-   re-verification;

-   regression tests.

Не смешивать Identity Registry migration с небольшим resolver rescue
patch.

======================================================================
55. ARCHITECTURE BOOKMARK --- CACHE LIFECYCLE
===========================================

Отдельно различать:

stable identity

provider metadata

universe snapshot

runtime quote

rejection evidence

У них не обязательно одинаковые TTL/invalidation semantics.

Не использовать один глобальный TTL как универсальное решение.

Identity Registry и cache optimization связаны,

но НЕ являются одной задачей.

======================================================================
56. ARCHITECTURE BOOKMARK --- COMPREHENSIVE DIAGNOSTICS
=====================================================

Не возвращаться к циклу:

diagnostic release → один новый boolean → production → ещё одна release
→ ещё один boolean

без необходимости.

Целевое направление:

один comprehensive rejection audit,

который позволяет исследовать большинство cohorts offline.

======================================================================
57. ARCHITECTURE BOOKMARK --- REPRODUCIBILITY
===========================================

Постоянная цель:

SOURCE / TEST REPRODUCIBILITY.

Для этого:

Git HEAD = source of truth

git archive HEAD = inter-chat source transport

Git patch = modification transport

tests = self-contained

runtime state = отдельно

generated artifacts = not tracked

Не возвращаться к source ZIP overlay workflow.

======================================================================
58. ARCHITECTURE BOOKMARK --- PROVIDER LIFECYCLE
==============================================

Будущая lifecycle architecture должна отличать:

security disappeared from provider

от

security identity invalid

и:

temporary provider outage

от

delisting / venue migration.

Это важно для:

-   cache;
-   retries;
-   rejection semantics;
-   Identity Registry;
-   provider refresh policy.

Не реализовывать эту architecture неявно через отдельные rescue
exceptions.

======================================================================
