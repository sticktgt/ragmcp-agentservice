# Агент-сервис (LangChain + MCP, **LangGraph API Server**)

Лёгкий HTTP‑серЛёгкий агент для вопросов/ответов с **условным RAG-поиском** по базе знаний через **Model Context Protocol (MCP)**.  
Агент решает, **когда** выполнять поиск, **как** включать переранжирование (rerank), добавляет контекст (с указанием источников) в промпт. Возврат источников (цитат) настраивается в конфигурации.
Текущая реализация использует **LangGraph API Server**. Для простого синхронного HTTP добавлен собственный маршрут `/invoke` поверх сервера LangGraph.

## Ключевые возможности

- **LangGraph**: граф из узлов (Route → Search[RAG/MCP] → Generate[LLM] → Finalize), управляет ветвлением и состоянием.
- **MCP через LangChain**: `langchain-mcp-adapters` + `MultiServerMCPClient` с транспортом `streamable_http`.
- **Условный поиск**: Router решает, выполнять ли RAG (по ключевым словам/длине/настройке).
- **Переранжирование**: режимы `on | off | auto`; параметр `top_n` добавляется **только** при `rerank=true`.
- **Цитаты (источники)**: настраиваются в `config.yaml` (включение/выключение, сниппеты, лимит символов, score...
- **Простой синхронный HTTP**: `/invoke` (возвращает финальный JSON без стриминга).
- **Стриминг**: стандартные эндпоинты LangGraph (`/runs/stream`, `/runs`, `/messages`).

---

## Архитектура (высокоуровнево)

```

Клиент ──(HTTP)──→ LangGraph API (+ кастомный FastAPI app)
├─ /invoke ← синхронный вызов graph.ainvoke() → финальный JSON
├─ /runs, /runs/stream, /messages (встроенные эндпоинты)
└─ /docs (OpenAPI)

Граф (StateGraph, LangGraph)
├─ RouteNode → решает нужен ли поиск, режим поиска
├─ SearchNode → если нужно - вызов MCP инструмента (rag.search)
├─ GenerateNode→ сбор промпта (RU/EN) + контекста; вызов LLM
└─ FinalizeNode→ формирует ответ и список citations (если включено)

```

**Основные модули**
- `chain_graph.py` — описание графа (узлы/переходы), сборка `StateGraph` и компиляция.
- `router.py` — определение параметров вызова RAG.
- `mcp_lazy.py` — создание клиента `MultiServerMCPClient` и выбор инструмента (`toolName`).
- `tools/rag_tool.py` — нормализация результатов MCP (title/snippet/score/page/uri) и формат контекста.
- `llm/factory.py` — фабрика LLM (LiteLLM/OpenAI-совместимые/YandexGPT).
- `config.py` — загрузка `config.yaml` + ENV (`RS__...`) и доступ к параметрам.
- `graph_entry.py` — экспорт **фабрики графа** `make_graph` (некомпилированный Graph) для LangGraph.
- `webapp.py` — FastAPI-приложение, публикующее `/invoke` (синхронный JSON без стриминга).
- `langgraph.json` — конфигурация сервера LangGraph: где взять граф и веб-приложение.

---

## API

### `POST /invoke`

**Запрос:**
```json
{
    "question": "Как снизить лаг Kafka consumer? Укажите источники."
}
```

**Ответ (успех, с цитатами):**
```json
{
    "content": "Текст ответа от LLM",
    "citations": [
        {
            "title": "имя_файла.pdf",
            "page": 0,
            "snippet": "Текст цитаты...",
            "score": 0.14167605406794226
        }
    ]
}
```
**Ответ (успех, без цитат):**
```json
{
    "content": "Текст ответа от LLM"
}
```

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
langgraph dev
```

Проверка:
```bash
curl -s -X POST http://localhost:2024/invoke   -H "Content-Type: application/json"   -d '{"question":"Как снизить лаг Kafka consumer? Укажите источники."'
```

```bash
curl -s --request POST \
  --url "http://localhost:2024/runs/stream" \
  --header 'Content-Type: application/json' \
  --data '{
    "assistant_id": "agent",
    "input": { "question": "Как снизить лаг Kafka consumer? Укажите источники." },
    "stream_mode": "messages-tuple"
  }'
```

### Docker (пример)
```bash
docker run --rm -it -p 2024:2024 --add-host=host.docker.internal:host-gateway -e "RS__LLM__LITELLM__API_BASE=http://host.docker.internal:4000/v1" -e "RS__LLM__LITELLM__API_KEY=****************" -e "RS__LLM__LITELLM__FOLDER_ID=****************" -e "RS__MCP__SERVERS__RAG__URL=http://host.docker.internal:8080/mcp" -e "RS__API__CITATIONS__ENABLED=false" agentservice:latest
```
---

## Дополнительно

GET /docs — OpenAPI от LangGraph.

---
## TODO
Добавить логирование в LangGraph
...
- 
    
