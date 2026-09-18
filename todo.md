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
