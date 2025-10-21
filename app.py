from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from uuid import uuid4
import traceback
from contextlib import asynccontextmanager

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
        app.state.chain = build_agent_chain(CONFIG)
        app.state.startup_error = None
        logger.info("Agent chain built successfully")
    except Exception as exc:
        # Fail-safe: keep server up, but record startup error
        app.state.chain = None
        app.state.startup_error = exc
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        logger.error(f"Failed to build agent chain at startup: {exc}\n{tb}")
    yield
    # teardown if needed
    app.state.chain = None

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
    status = "ok" if getattr(request.app.state, "chain", None) else "degraded"
    return {"status": status, "has_chain": bool(getattr(request.app.state, "chain", None))}

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
        text = result.content if hasattr(result, "content") else str(result)

        logger.info(f"[{req_id}] /chat done len={len(text)}")
        return ChatResponse(content=text, citations=[], tool_calls=None, error=None)

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
