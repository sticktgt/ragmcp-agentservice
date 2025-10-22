from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from uuid import uuid4
import traceback
from contextlib import asynccontextmanager

from langchain_mcp_adapters.client import MultiServerMCPClient

from .config import CONFIG
from .chain import build_agent_chain
from .utils.logger import get_logger

logger = get_logger()

#CHAIN = build_agent_chain(CONFIG)

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    routing_overrides: Optional[Dict[str, Any]] = None

class ChatResponse(BaseModel):
    content: Optional[str] = None
    citations: Optional[List[Dict[str, Any]]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    error: Optional[Dict[str, Any]] = None  # <-- add error field


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the chain at startup
    try:

        # 1) Build MCP client from config
        mcp_cfg = (CONFIG.get("mcp") or {})
        servers = mcp_cfg.get("servers") or {
            "rag": {"transport": "streamable_http", "url": mcp_cfg.get("url")}
        }
        app.state.mcp_client = MultiServerMCPClient(servers)

        # 2) Load tools and pick rag.search
        tools = await app.state.mcp_client.get_tools()  # loads from all servers

        # Log all loaded tools at debug level
        # for idx, t in enumerate(tools):
        #    try:
        #         tool_name = getattr(t, "name", None) or getattr(t, "tool_name", None) or repr(t)
        #         logger.debug("[tool %d] name=%s repr=%s", idx, tool_name, repr(t))
        #     except Exception:
        #         logger.debug("[tool %d] (could not repr)", idx)

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
        app.state.startup_error = None
        logger.info("Agent chain built. has_rag_tool=%s", bool(app.state.rag_tool))

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

app = FastAPI(title="Agent Service", lifespan=lifespan)

# --- Global exception handlers (uniform JSON errors) ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    req_id = str(uuid4())
    logger.error(f"[{req_id}] 422 RequestValidationError: {exc}")
    return JSONResponse(
        status_code=422,
        content={
            "content": None,
            "citations": [],
            "tool_calls": None,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request payload.",
                "details": exc.errors(),
                "request_id": req_id,
            },
        },
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    req_id = str(uuid4())
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logger.error(f"[{req_id}] 500 Unhandled exception: {exc}\n{tb}")
    return JSONResponse(
        status_code=500,
        content={
            "content": None,
            "citations": [],
            "tool_calls": None,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unexpected server error.",
                "request_id": req_id,
            },
        },
    )

# --- Health/readiness ---
@app.get("/healthz")
async def healthz(request: Request):
    has_chain = bool(getattr(request.app.state, "chain", None))
    has_rag   = bool(getattr(request.app.state, "rag_tool", None))
    status = "ok" if has_chain else "degraded"
    # If chain is up but rag is missing, reflect partial capability
    if has_chain and not has_rag:
        status = "partial"
    return {"status": status, "has_chain": has_chain, "has_rag_tool": has_rag}

# --- Main chat endpoint ---
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    req_id = str(uuid4())

    # If chain failed to build at startup, return a friendly 503 with details
    startup_error = getattr(request.app.state, "startup_error", None)
    if startup_error is not None:
        logger.error(f"[{req_id}] Startup error prevents handling requests: {startup_error}")
        return JSONResponse(
            status_code=503,
            content={
                "content": None,
                "citations": [],
                "tool_calls": None,
                "error": {
                    "code": "SERVICE_UNAVAILABLE",
                    "message": f"Agent not ready: {startup_error}",
                    "request_id": req_id,
                },
            },
        )
    
    # Normal path
    try:
        user_msg = next((m.content for m in reversed(req.messages) if m.role == "user"), "").strip()
        if not user_msg:
            return JSONResponse(
                status_code=400,
                content={
                    "content": None,
                    "citations": [],
                    "tool_calls": None,
                    "error": {
                        "code": "BAD_REQUEST",
                        "message": "No user message provided.",
                        "request_id": req_id,
                    },
                },
            )

        logger.info(f"[{req_id}] /chat start msg_len={len(user_msg)}")
        chain = request.app.state.chain  # <-- get chain from app.state
        result = await chain.ainvoke({"question": user_msg})
        # text = result.content if hasattr(result, "content") else str(result)
        if isinstance(result, dict) and "content" in result:
            text = result.get("content", "")
            citations = result.get("citations", [])
        else:
            text = result.content if hasattr(result, "content") else str(result)
            citations = []
        logger.info(f"[{req_id}] /chat done len={len(text)} citations={len(citations)}")

        return ChatResponse(content=text, citations=citations, tool_calls=None, error=None)

    except Exception as exc:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        logger.error(f"[{req_id}] /chat error: {exc}\n{tb}")
        return JSONResponse(
            status_code=500,
            content={
                "content": None,
                "citations": [],
                "tool_calls": None,
                "error": {
                    "code": "AGENT_RUNTIME_ERROR",
                    "message": str(exc),
                    "request_id": req_id,
                },
            },
        )
