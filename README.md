# Агент-сервис (LangChain + MCP)

Лёгкий HTTP‑сервис (FastAPI), оборачивающий LLM с **условным поиском** по базе знаний (RAG) через **Model Context Protocol (MCP)**. Агент решает, **когда** выполнять поиск, **как** включать переранжирование (rerank), добавляет контекст (с указанием источников) в промпт.

## Ключевые возможности

- **Pre‑check роутер** — решает, нужен ли поиск по RAG для каждого запроса.
- MCP‑инструмент **`rag.search`** через **langchain-mcp-adapters**.
- Режимы переранжирования: **`on | off | auto`**; в `auto` используется эвристика (ключевые слова и др.).
- Компактное форматирование контекста с бюджетом символов (контроль токенов).
- **Локализация подсказок RU/EN** (автодетект по алфавиту).

---

## Архитектура (высокоуровнево)

```
Клиент → FastAPI (/chat)
          │
          ▼
    Цепочка LangChain
    ├─ Router (precheck: locale, forceSearchKeywords, rerankKeywords, escalation)
    │    └─ need=True/False (+ locale)
    ├─ [need=True] → MCP Tool (rag.search через langchain-mcp-adapters)
    │        └─ normalize → [{title, snippet, score, page}]   # имя файла/отн. путь + страница
    │        └─ _format_snippets → компактный список в лимит символов
    └─ LLM (LiteLLM/OpenAI‑совместимый или YandexGPT)
           └─ Итоговый ответ (+ список цитат в API)
```

**Основные модули**
- `app.py` — FastAPI с `lifespan`, глобальные обработчики ошибок, эндпоинты `/chat`, `/healthz`.
- `chain.py` — сборка цепочки (Router → [опц. RAG] → LLM), выбор rerank `on/off/auto`, сборка контекста.
- `router.py` — принятие решения о поиске; учет кодировки RU/EN и ключевых слов.
- `rag_tool.py` — нормализация MCP‑результатов в `{title, snippet, score, page}`.
- `factory.py` — инициализация LLM (LiteLLM/OpenAI‑совместимый, либо прямой YandexGPT).
- `config.py` — загрузка `config.yaml` + переопределения окружением `RS__...`.

---

## Конвейер обработки (Pipeline)

1. **Маршрутизация (`need_retrieval`)**
   - Определяется `locale` (RU/EN) по алфавиту.
   - Если текст слишком короткий (`< 12` символов) → поиск не производится.
   - Если найдены ключи из `routing.forceSearchKeywords[locale]` → поиск производится.
   - Если ключи из `routing.rerankKeywords[locale]` **и** `routing.escalateIfRerankTriggers=true` → поиск производится.

2. **Поиск (RAG), когда `need=True`**
   - Вызов MCP‑инструмента `rag.search`.
   - Решение **rerank** берётся из `routing.allowRerank`:
     - `on` — всегда,
     - `off` — никогда,
     - `auto` — эвристика (большой `k`, сравнительные ключи `rerankKeywords`, длинный вопрос).
   - **`top_n` передаётся только когда `rerank=true`**.
   - Результаты нормализуются в `{title, snippet, score, page}`; `title` — имя файла/относительный путь (+ страница). URL пока не используются.
   - `_format_snippets` собирает компактный маркированный список в лимит `limits.maxToolChars` (контроль токенов).

3. **LLM**
   - Формируется системный промпт (RU/EN) + опциональный контекст‑блок со сниппетами.
   - Возвращается ответ. **Цитаты** одновременно проксируются наружу в JSON‑поле `citations` (см. ниже).

---

## API

### `POST /chat`

**Запрос:**
```json
{
  "messages": [
    {"role": "user", "content": "Как снизить лаг Kafka consumer? Укажите источники."}
  ]
}
```

**Ответ (успех):**
```json
{
  "content": "Краткий ответ...",
  "citations": [
    {"title": "consumer_lag.md (p.3)", "page": 3},
    {"title": "tuning.md", "page": null}
  ],
  "tool_calls": null,
  "error": null
}
```

### `GET /healthz`
```json
{
  "status": "ok | partial | degraded",
  "has_chain": true,
  "has_rag_tool": true
}
```
- `partial`: сервис поднят, но MCP‑инструмент не найден (ответы будут LLM‑only).

---

## Конфигурация (`config.yaml`)

Все параметры задаются в YAML и могут быть переопределены окружением `RS__...`.

```yaml
server: # Параметры запуска сервиса

i18n: # Параметры кодировки текста

llm: # Настройки соединения с LLM

routing: # Настройки роутинга, режим, ключевые слова...

limits: # Настройка лимитов

mcp: # Настройки соединения и правил для MCP сервиса
```

### Переопределение через ENV
Любой параметр в YAML конфигурации может быть переопределён через переменные окружения, например:
```
RS__LLM__PROVIDER=litellm
RS__LLM__LITELLM__API_BASE=http://litellm:4000/v1
RS__MCP__SERVERS__RAG__URL=http://ragretriever:8080/mcp
RS__ROUTING__ALLOWRERANK=auto
```

---

## Запуск

### Локально

```bash
python -m agentservice.main
```

Проверка:
```bash
curl -s http://localhost:8081/healthz
curl -s -X POST http://localhost:8081/chat   -H "Content-Type: application/json"   -d '{"messages":[{"role":"user","content":"Как снизить лаг Kafka consumer? Укажите источники."}]}'
```

### Docker (набросок)
- TODO

---
## TODO

- 
    
