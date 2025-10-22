from typing import Dict, Any, List, Optional
# from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableBranch, RunnableLambda
from langchain_core.messages import HumanMessage, SystemMessage # AIMessage
import json

from .llm.factory import build_chat_model
from .router import need_retrieval

from .tools.rag_tool import normalize_mcp_hits
from .utils.logger import get_logger

logger = get_logger()

SYSTEM_PROMPT = {
  "ru": "Вы — краткий и точный помощник. Если предоставлен контекст, опирайтесь на него и приводите источники (URI или название документа).",
  "en": "You are a concise and precise assistant. If context is provided, ground answers in it and include sources (URI or document title).",
}
CONTEXT_FMT = {
  "ru": "Используйте эти фрагменты как контекст:\n{context}\nПри цитировании предпочитайте URI, если он есть.",
  "en": "Use these snippets as context:\n{context}\nWhen citing, prefer the URI if available.",
}

def _get_rerank_keywords(cfg: Dict[str, Any], locale: str) -> List[str]:
    return list((cfg.get("routing", {}).get("rerankKeywords") or {}).get(locale, []))

def _should_rerank_auto(cfg, question: str, k: int, locale: str) -> bool:
    q = (question or "").lower()

    # 1) if we’re retrieving a lot, rerank helps
    if k >= max(int(cfg["routing"].get("defaultK", 6)) + 2, 8):
        return True
    
    # 2) ambiguous / comparative intents
    kw = _get_rerank_keywords(cfg, locale)
    if any(w in q for w in kw):
        return True
    
    # 3) longer, multi-aspect questions benefit from rerank
    if len(q) > 80 and (" и " in q or " and " in q or "," in q):
        return True
    return False

def _resolve_rerank_flag(cfg, question: str, k: int, locale: str) -> bool:
    mode = (cfg["routing"].get("allowRerank", "auto") or "auto").strip().lower()
    if mode == "on":  flag = True
    elif mode == "off": flag = False
    else: flag = _should_rerank_auto(cfg, question, k, locale)
    logger.debug("rerank: mode=%s → flag=%s (k=%s, locale=%s)", mode, flag, k, locale)
    return flag

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

# --- add near the top of chain.py ---
def _clip(s: str, n: int) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[:n].rstrip() + "…"

def _build_citations(items: List[dict], cfg: Dict[str, Any]) -> List[dict]:
    api_cfg = (cfg.get("api") or {})
    cit_cfg = (api_cfg.get("citations") or {})
    include_snippet = bool(cit_cfg.get("includeSnippet", False))
    include_score   = bool(cit_cfg.get("includeScore", False))
    include_uri     = bool(cit_cfg.get("includeUri", False))
    snip_limit      = int(cit_cfg.get("snippetCharsLimit", 400))

    cites: List[dict] = []
    for d in items:
        c = {
            "title": d.get("title"),
            "page": d.get("page"),
        }
        if include_snippet:
            c["snippet"] = _clip(d.get("snippet") or "", snip_limit)
        if include_score:
            c["score"] = d.get("score")
        if include_uri:
            c["uri"] = d.get("uri")
        cites.append(c)
    return cites


def build_agent_chain(cfg: Dict[str, Any], rag_tool: Optional[Any] = None):
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
    # ---- ASYNC context loader using the MCP-backed LangChain tool ----
    async def with_context_async(input_dict):
        items = []
        try:
            if rag_tool is not None:
                k_val   = cfg["routing"].get("defaultK")
                # top_n   = cfg["routing"].get("topN")
                locale  = input_dict.get("route", {}).get("locale", cfg.get("i18n", {}).get("defaultLocale", "ru"))
                rerank_flag = _resolve_rerank_flag(cfg, input_dict["question"], k_val, locale)

                args = {
                    "query":  input_dict["question"],
                    "k":      k_val,
                    "rerank": rerank_flag,
                    "filters": None,
                }
                if rerank_flag:
                    args["top_n"] = cfg["routing"].get("topN", 6)  # only when rerank=True

                logger.debug("rag.call args=%s", args)

                out = await rag_tool.ainvoke(args)
                # out may be:
                # - a dict: {"results": [...]}
                # - a list: [...] (already hits)
                # - a JSON string (parse)
                import json
                hits = []
                if isinstance(out, dict) and "results" in out:
                    hits = out["results"]
                elif isinstance(out, list):
                    hits = out
                elif isinstance(out, str):
                    try:
                        parsed = json.loads(out)
                        hits = parsed.get("results", []) if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
                    except Exception:
                        hits = []
                norm = normalize_mcp_hits(hits, cfg)
                items = [i.dict() for i in norm]
                logger.debug("rag.results count=%d titles=%s", len(items), [d.get("title") for d in items[:5]])
            else:
                # Fallback: no MCP tool injected
                items = []
        except Exception as e:
            logger.error(f"with_context_async: MCP tool error: {e}")
            items = []

        input_dict["context"] = _format_snippets(items, cfg["limits"].get("maxToolChars", 6000))
        input_dict["citations"] = _build_citations(items, cfg)
        return input_dict

    with_ctx = RunnableLambda(with_context_async)

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

    def _finalize(output):
        ai = output.get("ai")
        citations = output.get("citations", [])
        content = ai.content if hasattr(ai, "content") else (
            ai if isinstance(ai, str) else str(ai)
        )
        return {
            "content": content,
            "citations": citations,
        }
    
    # Compose branches to carry citations through
    branch_true  = with_ctx | {"ai": main, "citations": (lambda x: x.get("citations", []))}
    branch_false = {"ai": main, "citations": (lambda x: [])}

    chain = (
        {"question": lambda x: x["question"]}
        | add_route_rl
        | RunnableBranch(
            (lambda x: x["route"].get("need") is True, branch_true),
            branch_false
        )
        | RunnableLambda(_finalize)    # <-- emit {"content", "citations"}
    )

    return chain
