from __future__ import annotations

from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, ConfigDict
from langserve import add_routes
from langchain_core.runnables import RunnableLambda
from langchain_mcp_adapters.client import MultiServerMCPClient

from .config import CONFIG
from .chain import build_agent_chain
from .utils.logger import get_logger

logger = get_logger()

# ---------- Public request/response schemas ----------
class AgentInput(BaseModel):
    question: str

class AgentOutput(BaseModel):
    content: str
    citations: Optional[List[Dict[str, Any]]] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize MCP client, load tools, build the chain, and mount it via LangServe.
    """
    try:

        # 1) Build MCP client from config
        mcp_cfg = (CONFIG.get("mcp") or {})
        servers = mcp_cfg.get("servers") or {
            "rag": {"transport": "streamable_http", "url": mcp_cfg.get("url")}
        }
        app.state.mcp_client = MultiServerMCPClient(servers)

        # 2) Load tools and pick rag.search
        tools = await app.state.mcp_client.get_tools()  # loads from all servers
        rag_name = mcp_cfg.get("toolName")
        rag_tool = next((t for t in tools if t.name == rag_name), None)
        if not rag_tool:
            # Soft-fail: keep running without RAG tool
            logger.warning("MCP tool '%s' not found. Agent will run without retrieval.", rag_name)
            app.state.rag_tool = None
        else:
            app.state.rag_tool = rag_tool

        # 3) Build the agent chain WITH the MCP tool
        from .chain import build_agent_chain
        app.state.chain = build_agent_chain(CONFIG, rag_tool=app.state.rag_tool)
        logger.info("Agent chain built. has_rag_tool=%s", bool(app.state.rag_tool))

        # 4) Adapter: accept the request shape and map to chain input
        def _normalize_agent_input(payload: Any) -> Dict[str, str]:
            if hasattr(payload, "question"):
                return {"question": (payload.question or "").strip()}
            if isinstance(payload, dict):
                return {"question": (payload.get("question") or "").strip()}
            if isinstance(payload, str):
                return {"question": payload.strip()}
            return {"question": ""}

        chain_adapter = RunnableLambda(_normalize_agent_input) | app.state.chain

        # 5) Publish LangServe routes (this replaces your custom /chat)
        # Endpoints:
        #   POST /agent/invoke       body: {"input": ChatRequest}
        #   GET  /agent/playground   interactive UI
        try:
            add_routes(
                app,
                chain_adapter,
                path="/agent",
                input_type=AgentInput,
                # output_type=AgentOutput,
                # playground_type="chat",
                playground_type="default",
            )
            logger.info("LangServe mounted at /agent (typed I/O).")
        except TypeError:
            add_routes(app, chain_adapter, path="/agent")
            logger.warning("LangServe mounted at /agent (untyped fallback). Consider upgrading langserve.")
        app.state.startup_error = None
        
    except Exception as exc:
        # Fail-safe: keep server up, but record startup error
        app.state.chain = None
        app.state.rag_tool = None
        app.state.mcp_client = None
        app.state.startup_error = exc
        import traceback
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        logger.error(f"Failed to build agent chain at startup: {exc}\n{tb}")
    yield
    # teardown if needed
    app.state.chain = None
    app.state.rag_tool = None
    app.state.mcp_client = None

# FastAPI app (LangServe runs on top of it)
app = FastAPI(title="Agent Service (LangServe)", lifespan=lifespan)

# Minimal health endpoint
@app.get("/healthz")
async def healthz(request: Request):
    has_chain = bool(getattr(request.app.state, "chain", None))
    has_rag   = bool(getattr(request.app.state, "rag_tool", None))
    status = "ok" if has_chain else "degraded"
    if has_chain and not has_rag:
        status = "partial"
    startup_error = getattr(request.app.state, "startup_error", None)
    return {
        "status": status,
        "has_chain": has_chain,
        "has_rag_tool": has_rag,
        "startup_error": str(startup_error) if startup_error else None,
    }
