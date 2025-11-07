from __future__ import annotations
from typing import TypedDict, Optional, List, Dict, Any
import json
import asyncio

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage

from .router import need_retrieval
from .tools.rag_tool import normalize_mcp_hits
from .llm.factory import build_chat_model
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

def _format_snippets(items: List[dict], limit_chars: int) -> str:
    if not items or limit_chars <= 0:
        return ""
    out, used = [], 0
    for it in items:
        uri = it.get("uri") or it.get("title") or "source"
        snip = (it.get("snippet") or "").strip()
        chunk = f"- [{uri}] {snip}"
        if used + len(chunk) > limit_chars:
            break
        out.append(chunk)
        used += len(chunk)
    return "\n".join(out)

def _citations_enabled(cfg: Dict[str, Any]) -> bool:
    return bool(((cfg.get("api") or {}).get("citations") or {}).get("enabled", True))

def _build_citations(items: List[dict], cfg: Dict[str, Any]) -> List[dict]:
    cit_cfg = (cfg.get("api", {}).get("citations") or {})
    if cit_cfg.get("enabled", True) is False:
        return []
    inc_snip = bool(cit_cfg.get("includeSnippet", False))
    inc_score = bool(cit_cfg.get("includeScore", False))
    inc_uri   = bool(cit_cfg.get("includeUri", False))
    snip_lim  = int(cit_cfg.get("snippetCharsLimit", 400))

    def clip(s: str, n: int) -> str:
        s = s or ""
        return s if len(s) <= n else s[:n].rstrip() + "…"

    out = []
    for d in items:
        c = {"title": d.get("title"), "page": d.get("page")}
        if inc_snip:  c["snippet"] = clip(d.get("snippet"), snip_lim)
        if inc_score: c["score"]   = d.get("score")
        if inc_uri:   c["uri"]     = d.get("uri")
        out.append(c)
    return out

def _resolve_rerank_flag(cfg: Dict[str, Any], question: str, k: int, locale: str) -> bool:
    mode = (cfg["routing"].get("allowRerank", "auto") or "auto").strip().lower()
    if mode in ("on", "off"):
        return mode == "on"
    q = (question or "").lower()
    if k >= max(int(cfg["routing"].get("defaultK", 6)) + 2, 8):
        return True
    kws = list((cfg.get("routing", {}).get("rerankKeywords") or {}).get(locale, []))
    if any(w in q for w in kws):
        return True
    return len(q) > 80 and (" и " in q or " and " in q or "," in q)

# ---------- Graph state ----------
class AgentState(TypedDict, total=False):
    question: str
    route: Dict[str, Any]
    locale: str
    k: int
    rerank: bool
    hits: List[Dict[str, Any]]
    context: str
    citations: Optional[List[Dict[str, Any]]]
    content: str
    error: Dict[str, Any]

# ---------- Nodes (callable classes to avoid closure issues) ----------
class RouteNode:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    def __call__(self, state: AgentState) -> AgentState:
        q = state["question"]
        route = need_retrieval(q, self.cfg)
        state["route"] = route
        state["locale"] = route.get("locale", self.cfg.get("i18n", {}).get("defaultLocale", "ru"))
        state["k"] = int(self.cfg["routing"].get("defaultK", 6))
        state["rerank"] = _resolve_rerank_flag(self.cfg, q, state["k"], state["locale"])
        return state

class SearchNode:
    def __init__(self, cfg: Dict[str, Any], rag_tool: Any | None):
        self.cfg, self.tool = cfg, rag_tool

    async def __call__(self, state: AgentState) -> AgentState:
        state["hits"], state["context"], state["citations"] = [], "", None
        if not self.tool:
            return state

        args = {"query": state["question"], "k": state["k"], "rerank": state["rerank"]}
        if state["rerank"]:
            args["top_n"] = int(self.cfg["routing"].get("topN", 6))

        try:
            out = await asyncio.wait_for(self.tool.ainvoke(args), timeout=self.cfg["mcp"].get("timeoutSec", 15))
        except asyncio.TimeoutError:
            logger.warning("rag_tool timeout (args=%s)", args)
            out = []
        except Exception as e:
            logger.warning("rag_tool failed: %s", e)
            out = []

        hits = out.get("results", []) if isinstance(out, dict) else (out if isinstance(out, list) else [])
        if isinstance(out, str):
            try:
                parsed = json.loads(out)
                hits = parsed.get("results", []) if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
            except Exception:
                hits = []

        norm = normalize_mcp_hits(hits, self.cfg)  # list of pydantic models
        items = [i.model_dump(exclude_none=True) for i in norm]

        state["hits"] = items
        state["context"] = _format_snippets(items, self.cfg["limits"].get("maxToolChars", 6000))
        state["citations"] = _build_citations(items, self.cfg) if _citations_enabled(self.cfg) else None
        return state

class GenerateNode:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.llm = build_chat_model(cfg["llm"])

    async def __call__(self, state: AgentState) -> AgentState:
        loc = state.get("locale", "ru")
        sys = SYSTEM_PROMPT.get(loc, SYSTEM_PROMPT["ru"])

        msgs = [SystemMessage(content=sys), HumanMessage(content=state["question"])]
        if state.get("context"):
            ctx_text = CONTEXT_FMT.get(loc, CONTEXT_FMT["ru"]).format(context=state["context"])
            msgs.append(SystemMessage(content=ctx_text))

        try:
            ai = await self.llm.ainvoke(msgs)
            state["content"] = ai.content if hasattr(ai, "content") else str(ai)
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            state["error"] = {"code": "LLM_ERROR", "message": str(e)}
            state["content"] = ""
        return state

class FinalizeNode:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    def __call__(self, state: AgentState) -> AgentState:
        res: AgentState = {"content": state.get("content", "")}
        # Only include citations if enabled + present
        if _citations_enabled(self.cfg) and state.get("citations") is not None:
            res["citations"] = state["citations"]
        return res

# ---------- Public builder ----------
def build_agent_graph(cfg: Dict[str, Any], rag_tool: Any | None) -> Any:
    g = StateGraph(AgentState)
    g.add_node("route",    RouteNode(cfg))
    g.add_node("search",   SearchNode(cfg, rag_tool))
    g.add_node("generate", GenerateNode(cfg))
    g.add_node("finalize", FinalizeNode(cfg))

    g.add_edge(START, "route")

    def _branch(state: AgentState) -> str:
        need = bool((state.get("route") or {}).get("need"))
        return "search" if need else "generate"

    g.add_conditional_edges("route", _branch, {"search": "search", "generate": "generate"})
    g.add_edge("search", "generate")
    g.add_edge("generate", "finalize")
    g.add_edge("finalize", END)

    # Returns a Runnable (works with LangServe add_routes)
    return g.compile()
