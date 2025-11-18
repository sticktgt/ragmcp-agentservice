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

### `POST /invoke порт 2024`

**Запрос порт**
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

v

**Запрос LangGraph API:**
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

**Ответ LangGraph API:**
```json
event: metadata
data: {"run_id":"019a96b1-b161-712f-af32-2599443182b5","attempt":1}
id: 1763464819917-0

event: messages
data: [{"content":"К сожалению, в предоставленном контексте нет информации, которая помогла бы ответить на ваш вопрос о снижении лага Kafka consumer.","additional_kwargs":{},"response_metadata":{},"type":"AIMessageChunk","name":null,"id":"run--0a6119f7-9d7f-4ceb-8d41-bd279a060d84","example":false,"tool_calls":[],"invalid_tool_calls":[],"usage_metadata":null,"tool_call_chunks":[]},{"created_by":"system","langgraph_auth_user_id":"","langgraph_request_id":"b3f08a9c-ab7c-478b-ad49-15dac2a86b71","run_id":"019a96b1-b161-712f-af32-2599443182b5","thread_id":"ac6d40d6-3f17-4f9e-aa76-c5a004eee514","graph_id":"agent","assistant_id":"fe096781-5601-53d2-b2f6-0d3403f7e9ca","user_id":"","run_attempt":1,"langgraph_version":"1.0.1","langgraph_api_version":"0.4.28","langgraph_plan":"developer","langgraph_host":"self-hosted","langgraph_api_url":"http://0.0.0.0:2024","langgraph_step":3,"langgraph_node":"generate","langgraph_triggers":["branch:to:generate"],"langgraph_path":["__pregel_pull","generate"],"langgraph_checkpoint_ns":"generate:795fc25b-5182-aad7-4783-e4fbe7274607","checkpoint_ns":"generate:795fc25b-5182-aad7-4783-e4fbe7274607","ls_provider":"openai","ls_model_name":"yandex-chat","ls_model_type":"chat","ls_temperature":0.0}]
id: 1763464822748-0

event: messages
data: [{"content":"","additional_kwargs":{},"response_metadata":{"finish_reason":"stop","model_name":"chat"},"type":"AIMessageChunk","name":null,"id":"run--0a6119f7-9d7f-4ceb-8d41-bd279a060d84","example":false,"tool_calls":[],"invalid_tool_calls":[],"usage_metadata":null,"tool_call_chunks":[]},{"created_by":"system","langgraph_auth_user_id":"","langgraph_request_id":"b3f08a9c-ab7c-478b-ad49-15dac2a86b71","run_id":"019a96b1-b161-712f-af32-2599443182b5","thread_id":"ac6d40d6-3f17-4f9e-aa76-c5a004eee514","graph_id":"agent","assistant_id":"fe096781-5601-53d2-b2f6-0d3403f7e9ca","user_id":"","run_attempt":1,"langgraph_version":"1.0.1","langgraph_api_version":"0.4.28","langgraph_plan":"developer","langgraph_host":"self-hosted","langgraph_api_url":"http://0.0.0.0:2024","langgraph_step":3,"langgraph_node":"generate","langgraph_triggers":["branch:to:generate"],"langgraph_path":["__pregel_pull","generate"],"langgraph_checkpoint_ns":"generate:795fc25b-5182-aad7-4783-e4fbe7274607","checkpoint_ns":"generate:795fc25b-5182-aad7-4783-e4fbe7274607","ls_provider":"openai","ls_model_name":"yandex-chat","ls_model_type":"chat","ls_temperature":0.0}]
id: 1763464822825-0
```

### `POST / порт 2024`

**Запрос Google A2A (RS__API__USE_GOOGLE_A2A=true):**
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

**Ответ Google A2A:**
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

**Запрос python-a2a (RS__API__USE_GOOGLE_A2A=flase):**
```json
{
    "role": "user",
    "content": { "type": "text", "text": "Как снизить лаг Kafka consumer? Укажите источники." }
}
```

**Ответ python-a2a:**
```json
{
  "content": {
    "text": "К сожалению, в предоставленных фрагментах нет информации о том, как снизить лаг Kafka consumer.",
    "type": "text"
  },
  "message_id": "2fb6e237-159f-41d4-a30a-2fde717bc7f7",
  "metadata": {
    "created_at": "2025-11-18T11:12:05.039587",
    "custom_fields": {
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
          "title": "имя файла 3.xlsx"
        }
      ]
    }
  },
  "parent_message_id": "dc0bf2db-d553-43ba-815c-7ea047da3627",
  "role": "agent"
}
```

### `POST / порт 2024`/a2a/tasks/send

**Запрос JSON-RPC style:**
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "params": {
    "id": "task-id-optional",
    "message": {
      "role": "user",
      "parts": [{ "type": "text", "text": "Как снизить лаг Kafka consumer? Укажите источники." }]
    }
  }
}
```

**Ответ JSON-RPC style:**
```json
{
  "id": "1",
  "jsonrpc": "2.0",
  "result": {
    "artifacts": [
      {
        "parts": [
          {
            "text": "текст ответа...",
            "type": "text"
          }
        ]
      }
    ],
    "id": "task-id-optional",
    "message": {
      "metadata": {
        "message_id": "4ac58bfb-67d1-4844-a7ef-8c2df0fc45e7"
      },
      "parts": [
        {
          "text": "Как снизить лаг Kafka consumer? Укажите источники.",
          "type": "text"
        }
      ],
      "role": "user"
    },
    "sessionId": "8fd1144f-ef05-4b24-8415-35b35c1a7dc8",
    "status": {
      "state": "completed",
      "timestamp": "2025-11-18T11:28:01.832218"
    }
  }
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
    
