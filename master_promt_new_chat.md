Продолжаем разработку проекта `tv-market-identity-prototype` / CLI
`tv-market-id`.

Это MASTER PROMPT проекта.

Он предназначен для начала ЛЮБОГО нового чата по проекту:

-   resolver development;
-   анализ production результатов;
-   rejection-audit analysis;
-   исследование нового rejection cohort;
-   functional admission change;
-   diagnostics;
-   tests;
-   cleanup;
-   packaging/repository hygiene;
-   performance/cache optimization;
-   architecture;
-   Identity Registry/lifecycle;
-   documentation;
-   разбор regression;
-   provider/universe drift;
-   подготовка следующей production iteration.

Этот prompt содержит:

1.  подтверждённые invariants проекта;
2.  reference development/production state;
3.  подтверждённую историю исследований;
4.  negative results, которые не следует исследовать заново без нового
    evidence;
5.  testing/reproducibility policy;
6.  Git/pwsh workflow;
7.  architecture bookmarks, которые ещё НЕ являются production policy.

Не смешивать эти категории.

======================================================================
0. СРЕДА ПОЛЬЗОВАТЕЛЯ =====================

Среда:

Windows PowerShell 7 (`pwsh`)

Все команды для пользователя должны быть готовы для непосредственного
копирования в PowerShell 7.

Для переноса многострочных команд использовать PowerShell backtick:

\`

Не использовать bash continuation:

\

Если команда может быть однострочной без потери читаемости,
предпочтительна однострочная команда.

Все Git-команды пользователя выполняются непосредственно из текущего Git
root, если явно не сказано иное.

Полученный от ассистента patch пользователь сохраняет как:

\$HOME`\Downloads`{=tex}`\tv`{=tex}-market-identity.patch

======================================================================

1.  # SOURCE OF TRUTH

Постоянный Git repository пользователя является единственным source of
truth.

Tracked project state включает фактические source/tests/config/docs,
например:

-   `src/`;
-   `tests/`;
-   `config/`;
-   `pyproject.toml`;
-   README;
-   другие tracked project files.

В том же repository существует ignored local production/runtime state:

-   `.env`;
-   `cache/`;
-   `out/`;
-   `identity.sqlite3`;
-   API credentials;
-   provider state;
-   другие runtime artifacts.

Этот runtime state:

-   не должен попадать в обычный source snapshot;
-   не должен уничтожаться при development iteration;
-   не должен заменяться assistant-generated source tree;
-   должен сохраняться между production runs.

======================================================================
2. INTER-CHAT SOURCE SNAPSHOT =============================

Для передачи актуального committed source в новый чат пользователь из
текущего Git root выполняет:

git status

git archive `--format=zip` --output=tv-market-identity-current.zip \`
HEAD

Полученный:

.`\tv`{=tex}-market-identity-current.zip

является snapshot committed HEAD.

Если такой archive приложен к текущему чату:

ОН ЯВЛЯЕТСЯ ЕДИНСТВЕННЫМ АКТУАЛЬНЫМ SOURCE BASELINE ЭТОЙ СЕССИИ.

Не восстанавливать source из памяти.

Не использовать старый source tree из предыдущего чата.

Не смешивать приложенный archive со старыми snapshots.

Память о проекте используется для:

-   invariants;
-   history;
-   architecture bookmarks;
-   expected/reference state;
-   workflow;

но НЕ для реконструкции отсутствующего source.

======================================================================
3. ОСНОВНОЙ DEVELOPMENT TRANSPORT =================================

Основной процесс:

CURRENT USER GIT HEAD ↓ git archive HEAD ↓
tv-market-identity-current.zip ↓ ASSISTANT ↓ inspect actual source ↓
analyze evidence ↓ modify ↓ tests ↓ diff review ↓ Git patch ↓ USER
permanent Git repo ↓ git apply ↓ review ↓ git add -A ↓ commit ↓
production if needed ↓ git archive HEAD ↓ NEXT CHAT

Обычный artifact от ассистента:

tv-market-identity.patch

Не использовать assistant-generated full source ZIP как обычный способ
обновления permanent repository.

Не распаковывать новый source ZIP поверх рабочего Git repository.

Полный versioned release ZIP создавать только если он отдельно нужен как
release artifact.

======================================================================
4. ЦЕЛЬ ПРОЕКТА ===============

`tv-market-id` --- строгий fail-closed identity resolver:

TradingView security/listing → Yahoo / OpenFIGI / Finnhub → VERIFIED или
REJECTED.

Главная задача:

доказать identity конкретного TradingView security/listing.

Недостаточно:

найти похожий ticker/security у provider.

Приоритет:

корректный REJECTED

ложный VERIFIED

REJECTED сам по себе не является ошибкой.

Цель проекта НЕ:

0 REJECTED.

Не оптимизировать resolver по минимальному количеству REJECTED.

Главный критерий:

каждый VERIFIED должен иметь достаточное identity/listing evidence.

Ambiguity/conflict должны оставаться fail-closed.

======================================================================
5. CONFIRMED IDENTITY PRINCIPLES ================================

Подтверждённые основные anchors/evidence:

TRADINGVIEW ISIN

Exact TradingView ISIN является основным identity anchor.

OPENFIGI

FIGI/shareClassFIGI используются как независимое identity evidence.

MIC / VENUE

MIC и venue mapping являются listing evidence только если mapping явно
проверен.

YAHOO

Yahoo metadata используется как provider/listing evidence.

FINNHUB

Finnhub metadata/universe используется как provider/security/listing
evidence в соответствующих resolver paths.

======================================================================
6. SECURITY IDENTITY ≠ LISTING IDENTITY
=======================================

Всегда различать:

SECURITY IDENTITY

что это за security/share class;

LISTING / VENUE IDENTITY

какая именно listing/venue;

PROVIDER SYMBOL IDENTITY

как конкретный provider представляет эту listing/security.

Совпадение security identity не всегда доказывает конкретную listing.

Особенно важно:

same ISIN

-   same shareClassFIGI
-   same ticker

НЕ обязательно означает:

same source venue/listing.

======================================================================
7. FAIL-CLOSED INVARIANTS =========================

Обязательные правила:

-   exact evidence предпочтительнее inference;

-   ambiguity → REJECTED;

-   conflicting evidence → REJECTED;

-   отсутствие metadata само по себе ничего не доказывает;

-   provider pathology не является identity proof;

-   cross-venue bridge требует сильного source-venue evidence;

-   отсутствие provider field нельзя автоматически интерпретировать как
    совпадение;

-   market/provider-specific anomaly нельзя автоматически превращать в
    generic resolver rule.

Запрещённые shortcuts:

-   fuzzy matching;

-   name similarity;

-   issuer-name matching как identity proof;

-   ticker guessing;

-   per-ticker allowlists;

-   ad-hoc exceptions ради конкретных symbols;

-   глобальные taxonomy overrides ради уменьшения REJECTED;

-   generic MIC inference без verified mapping;

-   generic venue bridge только из-за совпадения ticker;

-   weakening policy ради красивых production counts.

======================================================================
8. ТРЕБОВАНИЯ К НОВОМУ RESCUE RULE ==================================

Новый functional rescue rule допустим только если pattern:

GENERIC

не зависит от списка отдельных symbols;

DETERMINISTIC

даёт воспроизводимый результат;

INDEPENDENTLY EVIDENCED

имеет независимое identity/listing evidence;

FAIL-CLOSED

не превращает отсутствие evidence в positive proof;

ADVERSARIALLY TESTABLE

имеет формулируемую negative boundary.

Новый rule должен иметь:

positive cohort + near-miss/adversarial cohort.

Если безопасный generic rule сформулировать нельзя:

оставить REJECTED.

======================================================================
9. SAME-VENUE VS CROSS-VENUE ============================

Same-venue и cross-venue имеют разную доказательную нагрузку.

SAME-VENUE

В некоторых resolver paths может быть достаточно комбинации:

-   exact ISIN;
-   однозначной candidate;
-   compatible provider metadata;
-   доказанного venue relation.

Конкретные требования определяются фактической policy/source.

CROSS-VENUE

Требует более сильного evidence.

Обычно нужны:

-   exact security identity;
-   share-class consistency, где применимо;
-   explicit source-venue proof;
-   explicit target/provider listing proof;
-   отсутствие ambiguity/conflict.

Unique shareClassFIGI сам по себе не доказывает source listing.

Permanent regression invariant:

same ISIN

-   same shareClassFIGI
-   same ticker
-   wrong/unproven source venue → REJECTED

======================================================================
10. CANDIDATE GENERATION ========================

Candidate generation должна быть bounded и deterministic.

Допустимы только явно поддерживаемые provider symbol transformations.

Candidate generation сама по себе не является identity proof.

Каждый candidate должен пройти required exact checks, например:

-   ISIN;
-   FIGI/shareClass;
-   MIC/venue;
-   currency;
-   type/taxonomy;
-   provider metadata;
-   ambiguity checks.

Если после required checks остаются несколько допустимых identity paths:

→ REJECTED.

======================================================================
11. GENERIC CORE / PROVIDER-MARKET QUIRKS
=========================================

Основной архитектурный принцип:

GENERIC RESOLVER CORE

-   

MARKET / PROVIDER SPECIFIC LOGIC

Generic core должен содержать общие identity invariants.

Provider/market-specific pathology должна быть локализована.

Не превращать локальную provider taxonomy/venue pathology в глобальную
identity policy.

Reviewed MIC mappings должны оставаться explicit.

Не выводить MIC только по похожему exchange label.

Для non-US resolution предпочтителен строгий evidence chain вида:

reviewed TradingView prefix → ISO MIC → exact/unique OpenFIGI evidence →
explicit MIC→provider mapping → raw provider venue/type/currency
verification

Фактическую реализацию всегда проверять по текущему source.

======================================================================
12. CURRENT REFERENCE DEVELOPMENT STATE
=======================================

Это REFERENCE STATE.

Он используется для обнаружения неожиданного baseline mismatch.

Он НЕ заменяет фактическую проверку приложенного source.

Последний ожидаемый package baseline:

v0.4.47

Production admission policy:

0.4.34-policy434

Package version и admission policy --- разные сущности.

v0.4.35+ в основном относились к:

-   diagnostics;
-   tooling;
-   cleanup;
-   tests;
-   research instrumentation;

и не должны автоматически означать изменение admission policy.

Ожидаемый test baseline:

pytest -q → 492 passed

Expected compile gate:

python -m compileall -q src tests → PASS

Если actual committed HEAD уже легитимно новее:

не откатывать его к v0.4.47.

Определить actual state по source.

======================================================================
13. 489 VS 492 TESTS --- ВАЖНАЯ ИСТОРИЯ
=====================================

Ранее assistant-generated v0.4.47 ZIP содержал:

489 passed

Он был неполным.

Причина:

случайно отсутствовал:

tests/test_openfigi_concurrency.py

Пользователь восстановил этот файл.

Правильный baseline после восстановления:

492 passed

Поэтому для соответствующего historical baseline:

489 = incomplete artifact

492 = correct baseline

Не менять expected count, чтобы скрыть mismatch.

======================================================================
14. SELF-CONTAINED TESTS ========================

Tests были сделаны self-contained.

`tests/conftest.py` предоставляет минимальный stub:

`tradingview_screener`

только если настоящий dependency отсутствует.

Это test isolation mechanism.

Он НЕ заменяет production runtime dependency.

External:

/mnt/data/testshim

больше не должен требоваться.

Assistant не должен возвращать внешний testshim как часть нормального
workflow.

======================================================================
15. OPENFIGI CONCURRENCY TEST =============================

Файл:

tests/test_openfigi_concurrency.py

является важным functional regression coverage.

Он должен сохраняться.

Он добавляет 3 tests и исторически объясняет:

489 → 492.

Не удалять его как obsolete cleanup.

======================================================================
16. HISTORICAL TEST CLEANUP ===========================

Ранее были удалены stale/obsolete diagnostic tests:

tests/test_cli_us_finnhub_unknown_type_dr_audit_v0433.py

tests/test_cli_us_finnhub_unknown_type_rebaseline_audit_v0435.py

tests/test_source_mic_proven_bridge_audit_v0445.py

tests/test_us_same_ticker_bridge_audit_v0444.py

tests/test_us_ootc_stock_preferred_unknown_type_rescue_v0431.py

Последний был redundant, поскольку актуальное functional coverage
сохранялось в:

tests/test_resolver.py

и

tests/test_us_ootc_stock_preferred_unknown_type_rescue_v0432.py

Удаление historical test допустимо только если functional invariant
остаётся покрытым.

======================================================================
17. CLEANUP REGRESSION TEST ===========================

Файл:

tests/test_rejection_audit_cleanup_v0446.py

должен сохраняться, пока актуален соответствующий cleanup invariant.

Он проверяет отсутствие retired temporary diagnostic probe names.

README mention удалённых diagnostics может быть историческим описанием и
не обязательно должен удаляться.

======================================================================
18. TEST COVERAGE HYGIENE =========================

Не считать test obsolete только потому, что filename содержит старую
version.

Перед удалением test определить:

1.  какой invariant он защищает;

2.  есть ли equivalent current coverage;

3.  сохранена ли positive boundary;

4.  сохранена ли adversarial/negative boundary.

Особенно сохранять coverage для:

-   concurrency;
-   ambiguity;
-   fail-closed;
-   cross-venue;
-   cache compatibility;
-   provider mismatch;
-   transient provider behavior.

======================================================================
19. REPOSITORY HYGIENE ======================

Tracked generated artifacts не нужны.

`.gitignore` должен покрывать по смыслу:

**pycache**/ *.py\[cod\] .pytest_cache/ *.egg-info/ build/ dist/

И локальные dependency artifacts, если они существуют:

deps/ \*.whl

Конкретный actual `.gitignore` проверять по source.

======================================================================
20. EGG-INFO CLEANUP ====================

Ранее:

src/tv_market_identity.egg-info/

был tracked.

Он был удалён из Git/index.

Generated `*.egg-info` не должен возвращаться в repository.

При baseline inspection проверять отсутствие tracked egg-info.

======================================================================
21. OLD WHEEL CLEANUP =====================

Ранее существовал:

deps/tradingview_screener-3.2.2-py3-none-any.whl

Он использовался только для старого способа передачи/testing.

После self-contained tests он не нужен.

Не возвращать старый bundled wheel в repository.

======================================================================
22. LINE ENDINGS / GITATTRIBUTES ================================

`.gitattributes` был добавлен для line-ending hygiene.

Не смешивать массовый:

git add --renormalize .

с unrelated functional/cleanup commit.

Если repository-wide EOL normalization действительно потребуется:

делать отдельным mechanical commit.

======================================================================
23. STALE FILE PROTECTION =========================

Ранее source ZIP overlay поверх старого tree привёл к тому, что
удалённые tests оставались на диске и продолжали запускаться.

Поэтому permanent workflow изменён.

НЕ ДЕЛАТЬ:

new ZIP → extract поверх old repo

ДЕЛАТЬ:

Git patch → git apply → git add -A → commit

Если assistant удаляет obsolete tracked file:

deletion должна присутствовать в patch.

`git add -A` включает:

-   additions;
-   modifications;
-   deletions.

После commit следующий:

git archive HEAD

уже не содержит удалённый stale file.

Не добавлять для этого второй permanent repository, manual manifests или
сложный tree-equivalence workflow без конкретной необходимости.

======================================================================
24. TESTING POLICY --- ОБЫЧНАЯ ITERATION
======================================

Для diagnostic/tooling/cleanup iteration:

change → targeted tests при необходимости → один full pytest перед
завершением → compileall → diff review → patch verification

Не запускать полный pytest после каждой маленькой правки.

======================================================================
25. TESTING POLICY --- FUNCTIONAL ADMISSION CHANGE
================================================

Если меняется VERIFIED/REJECTED admission logic:

functional change → targeted positive tests → targeted
adversarial/negative tests → full pytest → compileall → package/policy
sanity → diff review → patch → git apply --check → user applies patch →
bounded REAL provider smoke, если change вводит новый/изменённый
provider contract → smoke PASS → user production full-universe →
baseline comparison

Mocked/unit tests НЕ являются достаточным основанием для full-universe
production, если functional admission change вводит новый или изменяет
существующий внешний provider contract.

Под provider contract здесь понимается фактическая комбинация, от
которой зависит provider response/admission, например:

-   provider;
-   endpoint/method;
-   `idType`;
-   источник `idValue`;
-   `micCode` / exchange scope;
-   currency filter;
-   `securityType2` / taxonomy filter;
-   Yahoo suffix/venue contract;
-   Finnhub symbol/type contract;
-   expected identity fields;
-   scoped vs unscoped request semantics.

Если discovery/probe уже доказал конкретный provider contract,
production implementation MUST воспроизводить именно этот contract.

Нельзя без нового real-provider evidence незаметно заменять, например:

-   `ID_ISIN` → `ID_EXCH_SYMBOL`;
-   `ID_EXCH_SYMBOL` → `ID_ISIN`;
-   scoped MIC request → unscoped request;
-   unscoped request → scoped MIC request;
-   `micCode` → `exchCode`;
-   один Yahoo suffix/venue contract → другой;
-   добавлять или удалять provider filters, если это может изменить
    mapping.

Если такая замена нужна, она сама считается новым provider contract и
требует отдельного bounded REAL provider probe/smoke до full-universe
production.

Relevant regression dimensions могут включать:

-   positive cohort;
-   near miss;
-   wrong MIC;
-   wrong currency;
-   wrong Yahoo type;
-   ambiguous OpenFIGI;
-   missing ISIN;
-   multiple FIGI/shareClass;
-   ticker mismatch;
-   wrong source venue;
-   cross-venue false positive.

Permanent negative regression:

same ISIN

-   same shareClassFIGI
-   same ticker
-   wrong/unproven source venue → REJECTED

======================================================================
25A. REAL PROVIDER SMOKE GATE =============================

Этот gate обязателен для functional admission change, если change:

-   вводит новый provider path;
-   меняет provider request contract;
-   меняет source-venue routing;
-   меняет MIC/suffix selection;
-   меняет provider filters, влияющие на mapping;
-   переносит discovery/probe evidence в production resolver;
-   использует новый rescue/fallback path, зависящий от внешнего
    provider.

До full-universe production необходимо:

1.  Зафиксировать exact provider contract, доказанный discovery/probe.

    Минимально зафиксировать, если применимо:

    -   provider;
    -   `idType`;
    -   откуда берётся `idValue`;
    -   MIC/exchange scope;
    -   currency;
    -   security taxonomy/type;
    -   Yahoo suffix;
    -   expected provider identity fields;
    -   expected positive/negative result.

2.  Сверить implementation с этим exact contract.

    Production code не должен использовать "похожий" contract только
    потому, что mocked tests проходят.

3.  После применения functional patch выполнить bounded REAL provider
    smoke, если новый/изменённый provider contract ещё не был
    подтверждён именно в production-equivalent форме.

4.  Smoke должен быть минимальным и репрезентативным.

    Обычно достаточно:

    -   минимум одного positive representative каждого нового branch;
    -   одного negative/near-miss representative, если применимо;
    -   ambiguous representative, если ambiguity является частью policy.

5.  Smoke должен проверять не только конечный VERIFIED/REJECTED, но и
    фактический provider request contract/telemetry настолько, насколько
    это возможно без добавления permanent diagnostic complexity.

6.  Если smoke не подтверждает ожидаемое provider behavior:

    STOP.

    Full-universe production НЕ запускать.

    Сначала анализировать конкретный mismatch между доказанным discovery
    contract и production implementation.

7.  Если smoke PASS:

    только тогда разрешён full-universe production run.

8.  Повторный smoke не обязателен, если change НЕ вводит
    нового/изменённого provider contract и полностью использует ранее
    подтверждённый production/provider path без изменения его semantics.

9.  Если provider behavior можно проверить только в permanent user
    runtime из-за `.env`, credentials, cache или network state:

    ASSISTANT готовит минимальный smoke artifact;

    USER выполняет его;

    ASSISTANT анализирует результат до full-universe production.

10. Smoke не заменяет permanent tests.

    Правильная последовательность:

    real discovery evidence → implementation → targeted
    positive/adversarial tests → full local gates → verified patch →
    bounded REAL provider smoke when required → full-universe
    production.

11. Если exact provider contract уже был доказан отдельным real probe ДО
    implementation, после implementation всё равно необходимо убедиться,
    что production code воспроизводит именно этот contract.

    Если это нельзя доказать локально без network/provider call,
    выполнить bounded post-patch smoke.

12. Стоимость smoke должна быть bounded.

    Не использовать весь market universe как smoke test.

    Не отправлять тысячи provider jobs для проверки нового routing
    branch, если тот же contract можно доказать на нескольких
    representative rows.

======================================================================
26. TESTING POLICY --- DOCS / MECHANICAL
======================================

Для docs-only или чистого mechanical change:

production run не нужен.

Local gates должны соответствовать фактически изменённым files.

Не запускать expensive production verification механически.

======================================================================
27. ASSISTANT ДЕЛАЕТ LOCAL GATES ================================

Нормальный workflow:

ASSISTANT запускает local tests сам.

Не просить пользователя запускать:

pytest

compileall

вместо ассистента.

Перед передачей patch assistant должен самостоятельно выполнить
необходимые gates.

Обычный final local gate:

pytest -q

python -m compileall -q src tests

Reference historical result:

492 passed compileall PASS

Actual result определяется текущим source.

======================================================================
28. PATCH VERIFICATION ======================

Перед передачей patch assistant обязан проверить:

git apply --check `<generated-patch>`{=html}

Patch должен быть относительно source baseline текущей сессии.

Если patch не применяется:

исправить его до передачи пользователю.

Не передавать broken patch.

======================================================================
29. COMPREHENSIVE REJECTION AUDIT =================================

`--rejection-audit` является основным diagnostic workflow.

Не создавать новую diagnostic release для каждого rejection reason.

Предпочтительный процесс:

production run → comprehensive rejection JSONL → cohort analysis →
hypothesis → existing evidence → при необходимости новый generic
diagnostic field → hypothesis verification → решение о functional rule

Перед добавлением instrumentation сначала проверить:

можно ли уже ответить на вопрос по существующему JSONL.

======================================================================
30. DIAGNOSTIC EVIDENCE ≠ ADMISSION EVIDENCE
============================================

Diagnostic field может показать интересную correlation.

Это НЕ означает автоматически, что он достаточен для VERIFIED admission.

Перед functional rule требуется отдельное доказательство
identity/listing semantics.

Не превращать diagnostic coincidence в resolver rule.

======================================================================
31. ЦЕЛЕВОЕ НАПРАВЛЕНИЕ DIAGNOSTICS ===================================

Предпочтителен один comprehensive audit вместо цепочки временных probes.

Audit по возможности должен позволять исследовать:

-   source identity evidence;
-   target identity evidence;
-   ISIN;
-   FIGI;
-   shareClassFIGI;
-   source MIC;
-   target MIC;
-   provider symbol state;
-   provider venue;
-   currency;
-   taxonomy/type;
-   ambiguity;
-   active/inactive state;
-   final rejection reason.

Новое поле добавлять только если существующая schema действительно не
отвечает на generic research question.

======================================================================
32. CLOSED INVESTIGATIONS =========================

Без нового независимого evidence не открывать заново:

FINNHUB_TYPE_MISMATCH:?

FINNHUB_TYPE_MISMATCH:PUBLIC

FINNHUB_TYPE_MISMATCH:Unit

FINNHUB_TYPE_MISMATCH:Preference

FINNHUB_TYPE_MISMATCH:Stapled Security

FINNHUB_TYPE_MISMATCH:CDI

FINNHUB_TYPE_MISMATCH:Closed-End Fund

YAHOO_CURRENCY_MISMATCH:?

generic UNIQUE_SHARE_CLASS bridge

последний исследованный FINNHUB_NO_SYMBOL cohort

Residual rejects во многих случаях являются корректным fail-closed
результатом.

Не создавать новую diagnostic version только потому, что cohort остаётся
REJECTED.

======================================================================
33. v0.4.44 / v0.4.45 SHARE-CLASS INVESTIGATION
===============================================

Исследовался generic bridge:

exact ISIN

-   unique shareClassFIGI
-   same ticker

Гипотеза:

может ли это безопасно доказать identity при provider/source venue
mismatch?

Результат:

НЕТ.

Это достаточно сильное security/share-class evidence,

но недостаточное source-listing evidence.

Unique shareClassFIGI не доказывает конкретную source venue.

======================================================================
34. SOURCE-MIC BRIDGE INVESTIGATION ===================================

После этого исследовался более строгий вариант:

source MIC proven + unique shareClassFIGI + same ticker

Generic безопасного rescue также доказано не было.

В исследовании фигурировали, среди прочих:

BEP KHC PAGP

BEP/KHC имели OpenFIGI source evidence, но не достаточный Yahoo
same-venue proof.

PAGP не получил необходимого XNAS-scoped proof.

Итог:

explicit source-venue evidence остаётся обязательным для
соответствующего cross-venue admission path.

======================================================================
35. RETIRED TEMPORARY PROBES ============================

Временные probes:

us_same_ticker_unique_share_class_bridge

source_mic_proven_unique_share_class_bridge

были исследовательскими.

После отрицательного результата они были удалены.

Не возвращать их без нового independent evidence.

Cleanup regression должен предотвращать их случайное возвращение.

======================================================================
36. FINNHUB_NO_SYMBOL INVESTIGATION ===================================

Последний исследованный historical cohort включал:

TLAC PHXE/P MTAK HYAC.U DRK CATL

Generic functional rescue найден не был.

Большинство cases соответствовали inactive/provider lifecycle behavior.

PHXE/P дополнительно не имел достаточного shareClassFIGI evidence.

Итог:

оставить fail-closed.

Не открывать этот historical cohort заново без нового generic evidence.

======================================================================
37. CURRENT REFERENCE PRODUCTION RUN
====================================

Последний подтверждённый production run v0.4.46:

TradingView returned 13476 rows totalCount = 13476

VERIFIED = 13179

REJECTED = 297

CACHE_HIT = 13469

Rejection reasons:

128 YAHOO_TYPE_MISMATCH:MUTUALFUND

49 FINNHUB_TYPE_MISMATCH:?

28 YAHOO_CURRENCY_MISMATCH:?

17 FINNHUB_TYPE_MISMATCH:Unit

17 FINNHUB_TYPE_MISMATCH:PUBLIC

8 FINNHUB_NO_SYMBOL

6 FINNHUB_TYPE_MISMATCH:Preference

6 FINNHUB_TYPE_MISMATCH:Stapled Security

6 FINNHUB_TYPE_MISMATCH:CDI

5 FINNHUB_TYPE_MISMATCH:Closed-End Fund

4 YAHOO_SYMBOL_NOT_FOUND

4 FINNHUB_TYPE_MISMATCH:Ltd Part

2 FINNHUB_TYPE_MISMATCH:Royalty Trst

2 FINNHUB_TYPE_MISMATCH:NVDR

2 FINNHUB_TYPE_MISMATCH:Common Stock

2 YAHOO_VENUE_MISMATCH:OOTC-\>NCM\|NasdaqCM

1 YAHOO_VENUE_MISMATCH:XNAS-\>OQX\|OTC Markets OTCQX

1 YAHOO_VENUE_MISMATCH:XNAS-\>ASE\|NYSE American

1 YAHOO_RUNTIME_MISMATCH:PNK/USD/EQUITY

1 FINNHUB_TYPE_MISMATCH:ADR

======================================================================
38. REFERENCE PRODUCTION TELEMETRY ==================================

v0.4.46 reference stats:

cache_compatible_rejected_ignored = 0

cache_compatible_verified_hits = 13176

cache_hits = 13469

cache_misses = 7

finnhub_local_rows_indexed = 31066

finnhub_universe_cache_hits = 1

transient_rejections_not_cached = 0

yahoo_http_batches = 0

yahoo_provider_intra_call_dedup_hits = 0

yahoo_provider_requested_symbols = 0

yahoo_quote_refresh_batches = 176

Использовать эти numbers как reference, а не вечный expected output.

Provider/universe state динамичен.

======================================================================
39. v0.4.45 → v0.4.46 PRODUCTION DRIFT
======================================

v0.4.45 reference:

TradingView rows = 13478 VERIFIED = 13183 REJECTED = 295 CACHE_HIT =
13478

v0.4.46:

TradingView rows = 13476 VERIFIED = 13179 REJECTED = 297 CACHE_HIT =
13469

Это изменение было исследовано.

Исчезли старые FINNHUB_NO_SYMBOL:

TLAC MTAK CATL DRK HYAC.U

Появились новые OTC symbols:

EQTAF GCAND PGRPF RITRF SMIO SUNI TELWY

Все новые:

active_symbol = false

У новых семи:

ISIN = None

Arithmetic:

295 - 5 + 7 = 297

Поэтому изменение REJECTED было классифицировано как:

universe/provider lifecycle drift

а НЕ:

admission regression.

======================================================================
40. PROVIDER / UNIVERSE DRIFT POLICY
====================================

TradingView universe динамичен.

Provider metadata динамична.

При сравнении production runs СНАЧАЛА вычислять:

Δ universe

Δ VERIFIED

Δ REJECTED

Только затем связывать изменения с resolver rule.

Различать:

-   added security;
-   removed security;
-   unchanged security;
-   identity changed;
-   provider metadata changed;
-   resolver decision changed.

Изменение counts само по себе не является доказательством regression или
improvement.

======================================================================
41. TRANSIENT PROVIDER FAILURE ==============================

Не смешивать:

IDENTITY FAILURE

с

PROVIDER AVAILABILITY FAILURE.

Transient provider/network error не должен автоматически становиться
устойчивым identity rejection.

Historical telemetry:

transient_rejections_not_cached

существует именно в контексте этой semantics.

Lifecycle/cache design должен сохранять различие между:

identity evidence

и

временной доступностью provider.

======================================================================
42. CACHE PRINCIPLES ====================

Не использовать:

--refresh

без необходимости.

Compatible VERIFIED cache должен сохраняться.

REJECTED reprocessing нужен только если:

-   появилась новая functional rescue path;

-   изменилась policy compatibility;

-   действительно нужен provider refresh.

Diagnostics по возможности выполнять поверх final rejected bindings, не
повторяя дорогой полный resolution.

======================================================================
43. CACHE COMPATIBILITY =======================

Provider/universe cache и resolver identity binding не являются одной и
той же сущностью.

Policy change может потребовать re-evaluation identity bindings,

но не обязательно требует уничтожить независимый provider universe
cache.

Не использовать глобальный refresh как default solution.

======================================================================
44. PRODUCTION ACQUISITION COMPLETENESS
=======================================

Full-universe acquisition должен сохранять strict completeness
semantics.

Не считать truncated TradingView response полным universe.

Проверять actual implementation/invariants текущего source.

Historical production output использовал full-universe single-shot.

Не возвращаться автоматически к offset pagination без конкретной
причины.

При completeness analysis учитывать:

returned rows totalCount unique rows duplicate rows

Фактический source имеет приоритет над historical description.

======================================================================
45. RESOLVER COMPLEXITY BUDGET ==============================

Каждый новый admission rule увеличивает:

-   resolver complexity;
-   false-positive surface;
-   provider-specific coupling;
-   maintenance cost;
-   regression surface.

Поэтому новый rule оправдан только если:

1.  найден relevant cohort;

2.  причина rejection действительно resolver deficiency;

3.  существует generic deterministic evidence pattern;

4.  rule не зависит от списка тикеров;

5.  есть independent identity/listing evidence;

6.  есть adversarial negative boundary;

7.  tests доказывают positive и negative behavior.

Если нет:

оставить REJECTED.

======================================================================
46. STOP CRITERIA =================

Исследование rejection cohort можно считать завершённым, если:

-   существующий evidence объясняет rejection;

-   безопасный generic rescue не найден;

-   дальнейшее уменьшение rejection потребует ad-hoc/provider-specific
    weakening;

-   negative boundary показывает false-positive risk.

Не продолжать исследование только потому, что REJECTED count не равен
нулю.

======================================================================
47. КОГДА ОТКРЫВАТЬ НОВУЮ RESOLVER INVESTIGATION
================================================

Новая functional resolver работа оправдана при наличии:

-   нового заметного rejection cohort;

-   reproducible false REJECTED;

-   reproducible false VERIFIED;

-   заметного provider behavior/drift;

-   нового independent source-venue evidence;

-   generic resolver deficiency;

-   существенной lifecycle/cache проблемы.

Не открывать investigation только ради уменьшения residual REJECTED.

======================================================================
48. VERSIONING POLICY =====================

Различать:

PACKAGE VERSION

и

ADMISSION POLICY.

Package version может меняться для:

-   diagnostics;
-   tooling;
-   cleanup;
-   tests;
-   packaging;
-   docs.

Admission policy bump нужен только при изменении semantics:

VERIFIED / REJECTED

или

policy/cache compatibility.

Не bump-ить package или policy только потому, что начался новый чат.

======================================================================
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
59. PRODUCTION VERIFICATION RESPONSIBILITY
==========================================

Production/full-universe run выполняет USER.

Причина:

только permanent user repo имеет реальные:

`.env`

API credentials

`cache/`

`out/`

`identity.sqlite3`

provider/runtime state.

Assistant отвечает за local deterministic gates.

User отвечает за real production/provider verification.

======================================================================
60. PRODUCTION COMMANDS =======================

Production command всегда давать в PowerShell 7 syntax.

Например каноническая форма:

``` powershell
tv-market-id `
  --cache .\cache\identity.sqlite3 `
  run `
  --config .\config\identity_coverage_america.ini `
  --output .\out\identity_coverage_america.csv `
  --rejection-audit .\out\identity_rejections_america.jsonl
```

Важно:

-   global option `--cache` идёт до subcommand `run`;
-   `run` является обязательной subcommand для production run;
-   `--config`, `--output`, `--rejection-audit` относятся к `run`;
-   `--output` является CSV output;
-   `--rejection-audit` является JSONL diagnostic output;
-   не подменять CSV output файлом `.jsonl`;
-   фактический CLI contract всегда проверять по актуальному source
    перед тем, как давать пользователю команду.

Это только пример формы.

Фактическую production command брать из актуального
source/config/current iteration.

Не выдумывать config filenames или flags без проверки source.

Не использовать `--refresh` без явной причины.

======================================================================
61. MINIMAL PRODUCTION FEEDBACK ===============================

Не требовать от пользователя лишние artifacts после каждого production
run.

Для первичной проверки обычно достаточно console sections:

Identity

Rejection reasons

Resolver stats

Полный rejection JSONL нужен только если следующий шаг требует
cohort/evidence analysis.

Если console summary уже доказывает expected behavior:

не требовать JSONL механически.

======================================================================
62. PRODUCTION RESULT ANALYSIS ORDER
====================================

После production run анализировать в таком порядке:

1.  totalCount / universe;

2.  VERIFIED;

3.  REJECTED;

4.  CACHE_HIT;

5.  rejection reason distribution;

6.  resolver telemetry.

Первым делом вычислить:

Δ universe Δ VERIFIED Δ REJECTED

Только после этого оценивать functional change.

======================================================================
63. КРИТЕРИЙ УСПЕХА FUNCTIONAL CHANGE
=====================================

Functional rescue не считается доказанным просто потому, что:

REJECTED уменьшился.

Нужно показать:

-   expected target cohort rescued;

-   negative boundary осталась REJECTED;

-   unrelated cohorts не получили неожиданный VERIFIED;

-   изменения counts объясняются rule, а не universe drift;

-   telemetry не показывает новую pathology.

======================================================================
64. UNIVERSAL START-OF-CHAT ROUTING ===================================

В начале любого нового чата сначала определить тип входа.

Возможные режимы:

A. SOURCE ARCHIVE + JSONL

B. SOURCE ARCHIVE ONLY

C. PRODUCTION OUTPUT / JSONL ONLY

D. SOURCE MODIFICATION REQUEST

E. ARCHITECTURE / DESIGN

F. TEST / CLEANUP / PACKAGING

G. CONCEPTUAL PROJECT QUESTION

H. PRODUCTION REGRESSION ANALYSIS

Не запускать один и тот же workflow механически для всех режимов.

======================================================================
65. MODE A --- ARCHIVE + JSONL ============================

Если приложены source archive и rejection JSONL:

1.  inspect source baseline;

2.  run baseline gates;

3.  analyze JSONL existing evidence;

4.  correlate evidence с actual resolver source;

5.  сформулировать hypothesis;

6.  только затем решать, нужен ли code change.

Не начинать с нового diagnostic probe, не изучив JSONL.

======================================================================
66. MODE B --- ARCHIVE ONLY =========================

Если приложен только source archive:

inspect source

→ verify baseline

→ определить текущую задачу

→ выполнить source-based analysis/change.

Не требовать rejection JSONL, если задача решается без него.

======================================================================
67. MODE C --- PRODUCTION OUTPUT / JSONL ONLY
===========================================

Если новый чат начинается с production output:

сначала анализировать production evidence.

Порядок:

universe delta → VERIFIED/REJECTED delta → rejection distribution →
telemetry → cohort evidence

Не требовать source archive до тех пор, пока не нужен code
inspection/change.

Если найден потенциальный resolver deficiency:

тогда запросить current `git archive HEAD`.

======================================================================
68. MODE D --- SOURCE MODIFICATION REQUEST
========================================

Если пользователь сразу просит изменить code:

нужен актуальный source baseline.

Если current archive уже приложен:

использовать его.

Если нет:

попросить:

tv-market-identity-current.zip

созданный:

git archive `--format=zip` --output=tv-market-identity-current.zip \`
HEAD

Не создавать patch по remembered source.

======================================================================
69. MODE E --- ARCHITECTURE / DESIGN ==================================

Если запрос касается:

Identity Registry

cache lifecycle

provider refresh

resolver architecture

diagnostics architecture

performance architecture

сначала определить:

DESIGN

или

IMPLEMENTATION.

Для DESIGN можно работать концептуально на основе confirmed invariants и
architecture bookmarks.

Для IMPLEMENTATION сначала проверить actual source.

Не смешивать большую architecture migration с небольшим текущим cleanup.

======================================================================
70. MODE F --- TEST / CLEANUP / PACKAGING
=======================================

Для cleanup сначала проверить:

какой invariant защищает удаляемый code/test.

Не удалять historical coverage механически.

После cleanup:

full pytest compileall diff review patch check

если изменения затрагивают executable Python project.

Production обычно не нужна, если admission/runtime semantics не
меняются.

======================================================================
71. MODE G --- CONCEPTUAL PROJECT QUESTION
========================================

Если пользователь задаёт conceptual question по проекту:

не требовать source archive автоматически.

Использовать confirmed invariants/history.

Если ответ зависит от точной текущей implementation:

явно сказать, что нужно проверить actual source.

Не выдавать reference state за фактическую current implementation.

======================================================================
72. MODE H --- PRODUCTION REGRESSION ==================================

Если пользователь сообщает:

"стало больше REJECTED"

"стало меньше VERIFIED"

"изменились counts"

"новая version хуже"

НЕ начинать сразу с resolver rollback.

Сначала:

Δ universe Δ VERIFIED Δ REJECTED

added/removed rows

provider drift

cache behavior

rejection reason movement

и только потом resolver diff.

======================================================================
73. ОБЯЗАТЕЛЬНЫЙ ASSISTANT WORKFLOW ПРИ SOURCE CHANGE
=====================================================

Если source будет изменяться:

1.  использовать received archive как baseline;

2.  extract в clean temporary source directory;

3.  inspect actual source;

4.  определить package/policy;

5.  проверить test/repo composition;

6.  если есть JSONL --- анализировать его первым;

7.  сформулировать минимальный change;

8.  targeted tests;

9.  adversarial tests для admission change;

10. full pytest;

11. compileall;

12. inspect diff;

13. проверить deletions;

14. проверить отсутствие generated/stale artifacts;

15. создать Git patch;

16. `git apply --check`;

17. вернуть patch + changelog + commit message;

18. если functional change вводит новый/изменённый provider contract ---
    подготовить bounded REAL provider smoke artifact/command;

19. дать full-universe production command только после обязательного
    smoke PASS либо если §25A явно не требует smoke;

20. production command проверить по актуальному CLI source, включая
    положение global options, subcommand, output format и diagnostic
    flags;

21. указать минимально необходимый feedback.

======================================================================
74. ЧТО ASSISTANT НЕ ДОЛЖЕН ДЕЛАТЬ ==================================

Не должен:

-   просить пользователя запускать local pytest вместо себя;

-   возвращать непроверенный patch;

-   overlay-ить source trees;

-   использовать старый remembered source вместо archive;

-   придумывать provider evidence;

-   вводить ticker allowlists;

-   ослаблять fail-closed ради counts;

-   добавлять diagnostic release без анализа existing JSONL;

-   автоматически использовать `--refresh`;

-   автоматически bump admission policy;

-   отправлять пользователя на full-universe production для проверки
    нового provider contract до bounded REAL provider smoke;

-   заменять доказанный discovery/provider contract на похожий contract
    без нового real-provider evidence;

-   использовать full market universe как smoke test, если достаточно
    bounded representative cohort;

-   удалять historical test без проверки coverage;

-   реализовывать Identity Registry как побочный cleanup;

-   требовать JSONL после каждого run;

-   считать universe drift resolver regression;

-   считать отсутствие metadata positive evidence.

======================================================================
74A. TEMPORARY DIAGNOSTIC ARTIFACT WORKFLOW
===========================================

Временные probe scripts/configs/diagnostic patches не должны загрязнять
permanent Git repository.

Если пользователю нужен temporary probe:

ASSISTANT должен по возможности создать готовый downloadable artifact, а
не заставлять пользователя вручную копировать большой Python/script
block из чата.

Пользователь сохраняет downloaded temporary artifact в:

`$HOME\Downloads\`

Если probe должен использовать project environment, `.env`, editable
package или current source, пользователь запускает его ИЗ Git root, но
сам artifact остаётся в Downloads.

Пример:

``` powershell
python "$HOME\Downloads\probe-korea-openfigi.py"
```

Если нужен temporary config:

``` powershell
tv-market-id `
  --cache .\cache\identity.sqlite3 `
  run `
  --config "$HOME\Downloads\identity_coverage_korea_smoke.ini" `
  --output .\out\identity_coverage_korea_smoke.csv `
  --rejection-audit .\out\identity_coverage_korea_smoke_rejections.jsonl
```

Если diagnostic experiment требует временного source change,
предпочтителен temporary Git patch.

Применение:

``` powershell
git apply --check "$HOME\Downloads\<temporary-probe>.patch"
git apply "$HOME\Downloads\<temporary-probe>.patch"
```

После эксперимента, если patch не должен остаться:

``` powershell
git apply -R "$HOME\Downloads\<temporary-probe>.patch"
```

Перед reverse apply проверить рабочее дерево и не уничтожать unrelated
user changes.

Temporary artifact не становится permanent project source автоматически.

Если probe дал полезный generic result, permanent implementation
выполняется отдельным normal source patch с permanent tests.

Не оставлять в tracked source:

-   одноразовые probe scripts;
-   временные debug prints;
-   temporary configs без постоянной роли;
-   provider credentials;
-   probe output;
-   ad-hoc ticker lists.

======================================================================
75. USER PATCH WORKFLOW --- PWSH ==============================

Patch пользователь сохраняет:

\$HOME`\Downloads`{=tex}`\tv`{=tex}-market-identity.patch

Все команды ниже выполняются из текущего Git root.

Проверить repository:

git status

Проверить patch:

git apply --check
"\$HOME`\Downloads`{=tex}`\tv`{=tex}-market-identity.patch"

Если PASS:

git apply "\$HOME`\Downloads`{=tex}`\tv`{=tex}-market-identity.patch"

Проверить:

git status git diff

Stage ВСЕ изменения:

git add -A

Проверить staged changes:

git diff --cached --stat

При необходимости:

git diff --cached

Commit:

git commit -m "`<recommended commit message>`{=html}"

Проверить:

git status

======================================================================
76. NEXT CHAT SNAPSHOT --- PWSH =============================

После commit и завершения iteration:

git status

Создать:

git archive `--format=zip` --output=tv-market-identity-current.zip \`
HEAD

Передать следующему чату:

.`\tv`{=tex}-market-identity-current.zip

При необходимости также:

актуальный rejection-audit JSONL.

======================================================================
77. РАСПРЕДЕЛЕНИЕ РАБОТЫ ========================

ASSISTANT отвечает за:

-   source inspection;

-   JSONL analysis;

-   evidence analysis;

-   hypothesis;

-   implementation;

-   targeted tests;

-   adversarial tests;

-   full pytest;

-   compileall;

-   diff review;

-   coverage review;

-   repository hygiene review;

-   Git patch creation;

-   patch apply-check;

-   production-result analysis.

USER отвечает за:

-   permanent Git repository;

-   production `.env`;

-   API credentials;

-   cache;

-   identity DB;

-   сохранение patch в Downloads;

-   применение patch;

-   review diff;

-   `git add -A`;

-   commit;

-   production run;

-   передачу requested production evidence;

-   создание следующего `git archive HEAD`.

======================================================================
78. ПЕРВЫЙ ОТВЕТ ЛЮБОГО НОВОГО ЧАТА ===================================

ВАЖНО.

Первый содержательный ответ нового чата НЕ должен быть только:

"контекст принят".

Он должен быть operational.

Если пользователь приложил files:

сначала реально изучить их.

Первый ответ должен содержать:

1.  INPUTS / BASELINE

2.  КРАТКОЕ ОПИСАНИЕ ПРОЦЕССА

3.  PWSH-КОМАНДЫ ПРОЦЕССА

4.  NEXT STEP

======================================================================
79. FIRST RESPONSE --- INPUTS ===========================

Показать фактически полученные inputs.

Пример:

INPUTS

Archive: `tv-market-identity-current.zip`

Rejection audit: `<actual filename>`

или:

Rejection audit: NOT PROVIDED

Не утверждать наличие файла, которого нет.

Если archive не приложен:

не изображать, что source baseline был проверен.

======================================================================
80. FIRST RESPONSE --- BASELINE =============================

Если source archive приложен, фактически проверить и показать:

BASELINE

Package: `<actual>`{=html}

Admission policy: `<actual>`{=html}

pytest: `<actual>`{=html}

compileall: `<actual>`{=html}

Repository sanity:

tests/conftest.py PRESENT / ABSENT

tests/test_openfigi_concurrency.py PRESENT / ABSENT

external testshim ABSENT / PRESENT

tracked \*.egg-info ABSENT / PRESENT

bundled old \*.whl ABSENT / PRESENT

retired v0.4.44/v0.4.45 probes ABSENT / PRESENT

Reference для historical v0.4.47 baseline:

Package: v0.4.47 Admission policy: 0.4.34-policy434 pytest: 492 passed
compileall: PASS

Если actual отличается:

не скрывать mismatch.

Если actual легитимно новее:

использовать actual.

Если mismatch неожиданный:

не начинать functional change, пока причина не понятна.

======================================================================
81. FIRST RESPONSE --- КРАТКОЕ ОПИСАНИЕ ПРОЦЕССА
==============================================

В первом ответе обязательно кратко напомнить:

ПРОЦЕСС

Работаем от committed Git snapshot.

ASSISTANT:

archive/source → inspect → analyze evidence → minimal change → targeted
tests при необходимости → full local gates → diff review → create +
verify Git patch → prepare bounded REAL provider smoke when §25A
requires it

USER:

save patch to Downloads → apply to permanent Git repo → review →
`git add -A` → commit → bounded REAL provider smoke when required →
full-universe production только после smoke PASS / когда smoke не
требуется → новый `git archive HEAD`

Отдельно сказать кратко:

Git HEAD остаётся source of truth.

Source ZIP не распаковывается поверх рабочего repository.

======================================================================
82. FIRST RESPONSE --- PWSH COMMANDS ==================================

В первом ответе ОБЯЗАТЕЛЬНО показать standard user commands.

Все команды выполняются из текущего Git root.

PATCH:

git status

git apply --check
"\$HOME`\Downloads`{=tex}`\tv`{=tex}-market-identity.patch"

git apply "\$HOME`\Downloads`{=tex}`\tv`{=tex}-market-identity.patch"

git status git diff

git add -A

git diff --cached --stat

git commit -m "`<recommended commit message>`{=html}"

git status

NEXT SNAPSHOT:

git archive `--format=zip` --output=tv-market-identity-current.zip \`
HEAD

Если текущая iteration ещё не предполагает patch:

всё равно показать этот standard cycle кратко,

но не утверждать, что patch уже создан.

======================================================================
83. FIRST RESPONSE --- NEXT STEP ==============================

После baseline/evidence verification назвать:

ОДИН

конкретный следующий технический шаг.

Не выдавать длинный список вариантов.

NEXT STEP должен следовать из:

-   actual source;
-   actual production evidence;
-   current user request.

Если приложен JSONL:

сначала использовать existing evidence.

Если JSONL отсутствует:

не требовать его автоматически.

======================================================================
84. РЕКОМЕНДУЕМЫЙ ФОРМАТ ПЕРВОГО ОТВЕТА
=======================================

Пример:

INPUTS

Archive: `tv-market-identity-current.zip` Rejection audit: `...jsonl` /
NOT PROVIDED

BASELINE

Package: ... Admission policy: ... pytest: ... compileall: ...

conftest.py PRESENT test_openfigi_concurrency.py PRESENT external
testshim ABSENT tracked *.egg-info ABSENT old bundled *.whl ABSENT
retired bridge probes ABSENT

ПРОЦЕСС

Работаем по схеме:

`git archive HEAD` → source/evidence analysis → minimal changes → local
tests → verified Git patch → `git apply` → `git add -A` → commit →
production при необходимости → следующий `git archive HEAD`.

Я выполняю source analysis, изменения и local tests.

Вы применяете готовый patch к permanent repo и выполняете production
verification, когда она нужна.

Git HEAD остаётся source of truth; source ZIP поверх repo не
распаковываем.

КОМАНДЫ

git status

git apply --check
"\$HOME`\Downloads`{=tex}`\tv`{=tex}-market-identity.patch"

git apply "\$HOME`\Downloads`{=tex}`\tv`{=tex}-market-identity.patch"

git status git diff

git add -A

git diff --cached --stat

git commit -m "`<recommended commit message>`{=html}"

git status

Следующий snapshot:

git archive `--format=zip` --output=tv-market-identity-current.zip \`
HEAD

NEXT STEP

`<одно конкретное действие>`{=html}

======================================================================
85. ЕСЛИ В НОВОМ ЧАТЕ НЕТ ARCHIVE =================================

Master prompt должен работать и без source archive.

Если запрос:

-   conceptual;
-   architecture design;
-   workflow;
-   production result analysis;
-   discussion existing evidence;

можно работать без archive.

Но нельзя утверждать:

actual package version;

actual test count;

actual implementation details;

без проверки current source.

Если требуется source modification:

запросить current archive.

Команда:

git archive `--format=zip` --output=tv-market-identity-current.zip \`
HEAD

======================================================================
86. ЕСЛИ НОВЫЙ ЧАТ НАЧИНАЕТСЯ С JSONL
=====================================

Если пользователь сразу прикладывает rejection JSONL:

не начинать с требования нового diagnostic code.

Сначала:

-   определить cohorts;
-   изучить existing evidence;
-   проверить distributions;
-   найти generic patterns;
-   определить, чего именно не хватает.

Source archive нужен тогда, когда analysis переходит к:

implementation inspection

или

code modification.

======================================================================
87. ЕСЛИ НОВЫЙ ЧАТ НАЧИНАЕТСЯ С PRODUCTION SUMMARY
==================================================

Сначала:

Δ universe Δ VERIFIED Δ REJECTED

Потом:

reason movement telemetry provider/cache behavior

Только затем решать:

нужен ли source investigation.

======================================================================
88. ЕСЛИ НОВЫЙ ЧАТ НАЧИНАЕТСЯ С ARCHITECTURE
============================================

Для architecture request сначала определить:

DESIGN

или

IMPLEMENTATION.

DESIGN:

можно использовать confirmed invariants + bookmarks.

IMPLEMENTATION:

нужен current source archive.

Не выдавать architecture hypothesis за уже implemented behavior.

======================================================================
89. CURRENT ARCHITECTURE PRIORITIES ===================================

Не считать этот список обязательным roadmap.

Это bookmarks.

Основные будущие направления:

1.  Identity Registry / lifecycle;

2.  separation identity validity vs provider freshness;

3.  comprehensive rejection diagnostics;

4.  cache lifecycle / stale-while-revalidate;

5.  provider/universe drift handling;

6.  source/test reproducibility;

7.  keeping resolver complexity bounded.

Начинать их только по отдельному запросу или когда текущая evidence
показывает необходимость.

======================================================================
90. ТЕКУЩИЙ STOP POINT RESOLVER RESEARCH
========================================

На текущем reference state:

основные residual cohorts уже существенно исследованы.

Не продолжать механический rejection cleanup.

Следующая functional resolver modification должна быть вызвана:

НОВЫМ EVIDENCE

или

НОВОЙ GENERIC DEFICIENCY.

В противном случае правильный результат:

оставить current fail-closed behavior.

======================================================================
91. MAIN WORKFLOW SUMMARY =========================

Для обычной source iteration:

USER:

git archive HEAD

ASSISTANT:

inspect → analyze → modify → targeted tests → pytest → compileall → diff
→ patch → patch check

USER:

git apply --check → git apply → git diff → git add -A → commit →
production if needed

NEXT:

git archive HEAD

======================================================================
92. ГЛАВНЫЕ ИНВАРИАНТЫ MASTER PROMPT
====================================

1.  Git HEAD --- единственный source of truth.

2.  Actual archive имеет приоритет над remembered source.

3.  Exact TradingView ISIN --- основной identity anchor.

4.  OpenFIGI FIGI/shareClassFIGI --- independent identity evidence.

5.  Security identity не равна автоматически listing identity.

6.  Ambiguity/conflict → REJECTED.

7.  Absence of metadata proves nothing.

8.  Cross-venue bridge требует explicit strong evidence.

9.  Никаких fuzzy/name/ticker guessing shortcuts.

10. Никаких per-symbol allowlists.

11. Provider pathology не превращать в generic policy.

12. Не минимизировать REJECTED ценой weakening resolver.

13. Новый rescue rule должен быть generic + deterministic + evidenced.

14. Functional rescue должен иметь adversarial negative boundary.

15. Same ISIN + shareClass + ticker без source-venue proof недостаточно.

16. Residual REJECTED могут быть правильным конечным результатом.

17. Existing comprehensive JSONL анализировать до новых probes.

18. Diagnostic evidence не равно admission evidence.

19. Universe/provider drift анализировать до вывода о regression.

20. Transient provider failure не равно identity failure.

21. `--refresh` не использовать без причины.

22. Package version и admission policy различаются.

23. Tests должны быть self-contained.

24. `test_openfigi_concurrency.py` является важным coverage.

25. Historical correct v0.4.47 baseline = 492 tests, не 489.

26. Generated egg-info/wheels/testshim не должны возвращаться.

27. Historical test удалять только после проверки equivalent coverage.

28. Source ZIP не overlay-ить поверх permanent repo.

29. Git patch должен включать deletions.

30. Пользователь применяет patch через `git apply`.

31. Пользователь делает `git add -A`.

32. Assistant выполняет local tests сам.

33. Assistant проверяет patch через `git apply --check`.

34. Production выполняет user в permanent runtime environment.

35. Новый/изменённый external provider contract требует bounded REAL
    provider smoke до full-universe production.

36. Production implementation должна воспроизводить exact provider
    contract, доказанный discovery/probe; похожий contract без нового
    evidence запрещён.

37. Temporary probe scripts/configs/diagnostic patches по возможности
    передавать готовыми artifacts через `$HOME\Downloads\`, не добавляя
    их в permanent repo.

38. Production JSONL запрашивать только когда он действительно нужен.

39. Identity Registry --- architecture bookmark, не current policy.

40. TTL values --- hypotheses, не constants/policy.

41. Большие architecture changes делать отдельными phases.

42. Все user commands должны быть `pwsh`.

43. Первый ответ нового чата должен быть operational:

INPUTS / BASELINE → PROCESS → PWSH COMMANDS → ONE NEXT STEP.

======================================================================
93. ФИНАЛЬНОЕ ПРАВИЛО =====================

Не путать:

"можно найти соответствующий security"

с

"identity конкретной TradingView listing доказана".

Resolver должен оставаться доказательным и fail-closed.

Не добавлять complexity без evidence.

Не повторять уже закрытые исследования без нового evidence.

Не терять накопленные regression boundaries при cleanup.

Не принимать architecture bookmarks за production policy.

Не принимать historical reference state за actual state без проверки.

При source modification:

ACTUAL COMMITTED SOURCE → ACTUAL EVIDENCE → MINIMAL GENERIC CHANGE →
POSITIVE + NEGATIVE TESTS → FULL LOCAL GATES → VERIFIED GIT PATCH →
BOUNDED REAL PROVIDER SMOKE WHEN REQUIRED → USER COMMIT → FULL-UNIVERSE
PRODUCTION WHEN REQUIRED AND SMOKE GATE PASSED

При начале любого нового чата:

сначала определить тип задачи и фактические inputs,

затем сразу дать пользователю:

INPUTS / BASELINE PROCESS PWSH COMMANDS NEXT STEP.
