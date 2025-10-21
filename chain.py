from typing import Dict, Any, List
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableBranch, RunnableLambda
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from .llm.factory import build_chat_model
from .router import need_retrieval
from .tools.rag_tool import rag_search_tool

SYSTEM_PROMPT = {
  "ru": "Вы — краткий и точный помощник. Если предоставлен контекст, опирайтесь на него и приводите источники (URI или название документа).",
  "en": "You are a concise and precise assistant. If context is provided, ground answers in it and include sources (URI or document title).",
}
CONTEXT_FMT = {
  "ru": "Используйте эти фрагменты как контекст:\n{context}\nПри цитировании предпочитайте URI, если он есть.",
  "en": "Use these snippets as context:\n{context}\nWhen citing, prefer the URI if available.",
}

def _format_snippets(items: List[dict], limit_chars: int) -> str:
    lines = []
    used = 0
    for it in items:
        uri = it.get("uri") or it.get("title") or "source"
        snip = it.get("snippet") or ""
        chunk = f"- [{uri}] {snip.strip()}"
        if used + len(chunk) > limit_chars:
            break
        lines.append(chunk)
        used += len(chunk)
    return "\n".join(lines)

def build_agent_chain(cfg: Dict[str, Any]):
    llm = build_chat_model(cfg["llm"])


    # 1) Route once, keep locale on the dict
    def add_route(input_dict):
        route = need_retrieval(input_dict["question"], cfg)
        input_dict["route"] = route
        input_dict["locale"] = route.get("locale", cfg.get("i18n", {}).get("defaultLocale", "ru"))
        return input_dict
    add_route_rl = RunnableLambda(add_route)

    # Branch: decide retrieval
    # router = RunnableLambda(lambda x: need_retrieval(x["question"], cfg))

    # 2) If retrieval is needed, call tool and add context/citations
    def with_context(input_dict):
        items = rag_search_tool.invoke({
            "query": input_dict["question"],
            "k": cfg["routing"].get("defaultK", 6),
            "top_n": cfg["routing"].get("topN", 6),
            "rerank": (cfg["routing"].get("allowRerank") == "on")
        })
        as_dicts = [i if isinstance(i, dict) else i.dict() for i in (items or [])]
        input_dict["context"] = _format_snippets(as_dicts, cfg["limits"].get("maxToolChars", 6000))
        input_dict["citations"] = [{"uri": d.get("uri"), "title": d.get("title")} for d in as_dicts]
        return input_dict
    with_ctx = RunnableLambda(with_context)

    # 3) Build messages dynamically from locale (+ optional context)
    def build_messages(input_dict):
        loc = input_dict.get("locale", "ru")
        sys = SYSTEM_PROMPT.get(loc, SYSTEM_PROMPT["ru"])
        msgs = [SystemMessage(content=sys), HumanMessage(content=input_dict["question"])]
        ctx = (input_dict.get("context") or "").strip()
        if ctx:
            ctx_text = CONTEXT_FMT.get(loc, CONTEXT_FMT["ru"]).format(context=ctx)
            msgs.append(SystemMessage(content=ctx_text))
        return msgs
    make_msgs = RunnableLambda(build_messages)

    main = make_msgs | llm

    chain = (
        {"question": lambda x: x["question"]}
        | add_route_rl
        | RunnableBranch(
            (lambda x: x["route"].get("need") is True, with_ctx | main),
            # else: no retrieval → still uses locale for RU/EN system prompt
            main
        )
    )
    return chain
