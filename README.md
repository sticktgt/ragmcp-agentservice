# Агент-сервис (LangChain + MCP, LangServe)

Лёгкий HTTP‑сервис на базе **LangServe (FastAPI)**, оборачивающий LLM с **условным поиском** по базе знаний (RAG) через **Model Context Protocol (MCP)**. Агент решает, **когда** выполнять поиск, **как** включать переранжирование (rerank), добавляет контекст (с указанием источников) в промпт. Возврат источников (цитат) настраивается в конфигурации.

## Ключевые возможности

- **Pre‑check роутер** — решает, нужен ли поиск по RAG для каждого запроса.
- MCP‑инструмент **`rag.search`** через **langchain-mcp-adapters**.
- Режимы переранжирования: **`on | off | auto`**; в `auto` используется эвристика (ключевые слова и др.).
- Компактное форматирование контекста с бюджетом символов (контроль токенов).]
- **Локализация подсказок RU/EN** (автодетект по алфавиту).
- LangServe‑роуты + playground, **/healthz** для проверки готовности.
- Конфиг‑переключатели для **политики цитирования** (в том числе полное отключение цитат).

---

## Архитектура (высокоуровнево)

```
Клиент → LangServe (FastAPI) (/agent/invoke)
          │
          ▼
    Цепочка LangChain
    ├─ Router (precheck: locale, forceSearchKeywords, rerankKeywords, escalation)
    │    └─ need=True/False (+ locale)
    ├─ [need=True] → MCP Tool (rag.search через langchain-mcp-adapters)
    │        └─ normalize → [{title, snippet, score, page}]   # имя файла/отн. путь + страница
    │        └─ _format_snippets → компактный список в лимит символов
    └─ LLM (LiteLLM/OpenAI‑совместимый или YandexGPT)
           └─ Итоговый ответ (+ опц. список цитат в API)
```

**Основные модули**
- `app.py` — LangServe‑поднятие цепочки на FastAPI, `/agent`, `/agent/playground`, `/healthz`.
- `chain.py` — сборка цепочки (Router → [MCP] → LLM), контекст, политика rerank и выдача ответа.
- `router.py` — решение о поиске; локаль RU/EN; ключевые слова.
- `rag_tool.py` — нормализация MCP‑результатов в `{title, snippet, score, page}`.
- `llm/factory.py` — инициализация LLM (LiteLLM/OpenAI‑совместимый, либо YandexGPT).
- `config.py` — загрузка `config.yaml` + ENV‑переопределения `RS__...`.

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

### `POST /agent/invoke`

**Запрос:**
```json
{
    "input": {
        "question": "Как снизить лаг Kafka consumer? Укажите источники."
    }
}
```

**Ответ (успех, с цитатами):**
```json
{
    "output": {
        "content": "Текст ответа от LLM",
        "citations": [
            {
                "title": "имя_файла.pdf",
                "page": 0,
                "snippet": "Текст цитаты...",
                "score": 0.14167605406794226
            }
        ]
    },
    "metadata": {
        "run_id": "e41b117c-0cf9-4bdc-840f-326161c4da5e",
        "feedback_tokens": []
    }
}
```
**Ответ (успех, без цитат):**
```json
{
    "output": {
        "content": "Текст ответа от LLM"
    },
    "metadata": {
        "run_id": "5e7e8c7e-ebc8-448b-9699-fcbfcb676cc6",
        "feedback_tokens": []
    }
}
```
### `GET /healthz`
```json
{
    "status":"ok",
    "has_chain":true,
    "has_rag_tool":true,
    "startup_error":null}
```
- `has_rag_tool`: подключен ли сервис RAG.

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

api: # Настройки API
  citations: # Настрокйи возврата результатов поиска в RAG
```

### Переопределение через ENV
Любой параметр в YAML конфигурации может быть переопределён через переменные окружения, например:
```
RS__API__CITATIONS__ENABLED=false
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
curl -s http://localhost:8081/agent/invoke   -H "Content-Type: application/json"   -d '{"input": {"question": "Как снизить лаг Kafka consumer? Укажите источники."}}'
```

### Docker (набросок)
- TODO
---

## Дополнительно

**LangServe Playground**

http://localhost:8081/agent/playground/

---
## TODO

- 
    
