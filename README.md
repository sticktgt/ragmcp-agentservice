# Агент-сервис (LangChain + MCP, **LangGraph API Server**)

Лёгкий HTTP‑серЛёгкий агент для вопросов/ответов с **условным RAG-поиском** по базе знаний через **Model Context Protocol (MCP)**.  
Агент решает, **когда** выполнять поиск, **как** включать переранжирование (rerank), добавляет контекст (с указанием источников) в промпт. Возврат источников (цитат) настраивается в конфигурации.
Текущая реализация использует **LangGraph API Server**. Для простого синхронного HTTP добавлен собственный маршрут `/invoke` поверх сервера LangGraph.
Также добавлена реализация A2A протокола с использованием **python_a2a** A2AServer на порту 5050 (как proxy)

## Ключевые возможности

- **LangGraph**: граф из узлов (Route → Search[RAG/MCP] → Generate[LLM] → Finalize), управляет ветвлением и состоянием.
- **MCP через LangChain**: `langchain-mcp-adapters` + `MultiServerMCPClient` с транспортом `streamable_http`.
- **Условный поиск**: Router решает, выполнять ли RAG (по ключевым словам/длине/настройке).
- **Переранжирование**: режимы `on | off | auto`; параметр `top_n` добавляется **только** при `rerank=true`.
- **Цитаты (источники)**: настраиваются в `config.yaml` (включение/выключение, сниппеты, лимит символов, score...
- **Простой синхронный HTTP**: `/invoke` (возвращает финальный JSON без стриминга).
- **Стриминг**: стандартные эндпоинты LangGraph (`/runs/stream`, `/runs`, `/messages`).
- **A2A протокол**:  эндпоинт A2AServer (`:5050/`).

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
- `a2a_server.py` — прокси сервера A2AServer (*python_a2a).
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

**Запрос A2A:**
```json
{
    "role": "user",
    "parts": [
        {
            "type": "text",
            "text": "Как снизить лаг Kafka consumer? Укажите источники."
        }
    ]
}
```

**Ответ A2A:**
```json
{
    "metadata": {
        "citations": [
            {
                "page": null,
                "snippet": " текст цитаты 1…",
                "title": "имя_файла_1.html"
            },
            {
                "page": null,
                "snippet": " текст цитаты 2…",
                "title": "имя_файла_2.html"
            },
            {
                "page": 1,
                "snippet": "текст цитаты 3",
                "title": "имя_файла_3.xlsx"
            }
        ],
        "created_at": "2025-11-17T19:42:24.349811",
        "message_id": "bb3dd9a4-926b-4365-881e-95c7b08632fa",
        "parent_message_id": "259ccd79-4d7f-4e34-b02e-3493bf93a735"
    },
    "parts": [
        {
            "text": "К сожалению, в предоставленном контексте нет информации, которая могла бы помочь в решении вопроса о снижении лага Kafka consumer.",
            "type": "text"
        }
    ],
    "role": "agent"
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

Карточка агента A2A 

```bash (запрос)
curl -s http://localhost:5050/.well-known/agent-card.json | jq .
```

```json (ответ)
{
  "capabilities": {
    "google_a2a_compatible": true,
    "parts_array_format": true,
    "pushNotifications": false,
    "stateTransitionHistory": false,
    "streaming": false
  },
  "defaultInputModes": [
    "text/plain"
  ],
  "defaultOutputModes": [
    "text/plain"
  ],
  "description": "LangGraph-backed agent with MCP RAG",
  "name": "RAG Agent",
  "preferredTransport": "JSONRPC",
  "protocolVersion": "0.3.0",
  "skills": [
    {
      "description": "Answer questions; conditionally performs RAG via MCP.",
      "examples": [
        "Как снизить лаг Kafka consumer? Укажите источники.",
        "Особенности аппаратуры дистанционного управления АО «Азимут»?"
      ],
      "id": "bacca9a1-2a6d-46b6-ba3f-52204f0547fd",
      "inputModes": [
        "text/plain"
      ],
      "name": "answer",
      "outputModes": [
        "text/plain"
      ],
      "tags": [
        "rag",
        "langgraph",
        "mcp"
      ]
    }
  ],
  "url": "http://127.0.0.1:5050",
  "version": "0.1.0"
}
```
---
## TODO
Добавить логирование в LangGraph
...
- 
    
