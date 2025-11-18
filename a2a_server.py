from python_a2a import (
    A2AServer, run_server, AgentCard, AgentSkill
)
import uuid
import httpx
from python_a2a.models.message import Message, MessageRole, Metadata
from python_a2a.models.content import TextContent, ErrorContent
from utils.logger import get_logger
from config import CONFIG

logger = get_logger()

# Read API/citations toggles from config (kept from your version)
CIT_CFG = (CONFIG.get("api", {}) or {}).get("citations", {}) or {}
USE_GOOGLE_A2A = bool(CONFIG.get("api", {}).get("use_google_a2a", True))  # default ON
APPEND_CITATIONS = bool(CIT_CFG.get("enabled", False))      # default OFF

INVOKE_PORT = CONFIG.get("server", {}).get("port", 2024)
INVOKE_URL  = f"http://127.0.0.1:{INVOKE_PORT}/invoke"

class MyAgentA2A(A2AServer):
    def __init__(self) -> None:
        logger.info("Initializing MyAgentA2A...")
        public_url = CONFIG.get("server", {}).get("a2a_public_url", "").strip()

        agent_card = AgentCard(
            name="RAG Agent",
            description="LangGraph-backed agent with MCP RAG",
            url=public_url,
            version="0.1.0",
            skills=[AgentSkill(
                name="answer",
                description="Answer questions; conditionally performs RAG via MCP.",
                tags=["rag", "langgraph", "mcp"],
                examples=[
                    "Как снизить лаг Kafka consumer? Укажите источники.",
                    "Особенности аппаратуры дистанционного управления АО «Азимут»?",
                ],
            )],
            capabilities={
                "google_a2a_compatible": USE_GOOGLE_A2A,
                "parts_array_format": USE_GOOGLE_A2A,
                "pushNotifications": False,
                "stateTransitionHistory": False,
                "streaming": False,   # we want non-stream
            },
        )

        super().__init__(agent_card=agent_card)

        self._supports_streaming = False
        self.supports_streaming = False

        # Tell the base server which wire format to use
        if hasattr(self, "use_google_a2a_format") and callable(getattr(self, "use_google_a2a_format")):
            # call the method, do not assign to it
            self.use_google_a2a_format(USE_GOOGLE_A2A)

        # Also set private flags some versions check directly
        setattr(self, "_use_google_a2a", USE_GOOGLE_A2A)
        setattr(self, "_parts_array_format", USE_GOOGLE_A2A)    
        try:
            self.agent_card.capabilities["streaming"] = False
            self.agent_card.capabilities["google_a2a_compatible"] = USE_GOOGLE_A2A
            self.agent_card.capabilities["parts_array_format"] = USE_GOOGLE_A2A
        except Exception:
            pass

    def supports_streaming(self) -> bool:
        return False

    def handle_message(self, message: Message) -> Message:
        """Return a python-a2a Message with text in content and citations in metadata (if enabled)."""
        logger.info("handle_message(): role=%s id=%s", message.role, getattr(message, "message_id", None))

        # 1) Extract user text from google-A2A format (parts[]) or from python-a2a content
        user_text = ""
        if getattr(message, "content", None) and getattr(message.content, "type", None) == "text":
            user_text = message.content.text or ""
        elif hasattr(message, "parts") and message.parts:
            for p in message.parts:
                if isinstance(p, dict) and p.get("type") == "text" and "text" in p:
                    user_text = p["text"]
                    break

        # 2) Call LangGraph non-stream /invoke
        try:
            res = httpx.post(INVOKE_URL, json={"question": user_text}, timeout=60.0)

        except Exception as e:
            return Message(
                content=ErrorContent(message=f"Internal error calling agent graph: {e}"),
                role=MessageRole.AGENT,
                parent_message_id=getattr(message, "message_id", None),
            )
        # logger.info("LangGraph /invoke response data: %s", data)

        if res.status_code >= 400:
            msg = res.text
            try:
                j = res.json()
                if isinstance(j, dict) and isinstance(j.get("error"), dict):
                    msg = j["error"].get("message", msg)
            except Exception:
                pass
            return Message(
                role=MessageRole.AGENT,
                content=ErrorContent(message=f"Agent error ({res.status_code}): {msg}"),
                parent_message_id=getattr(message, "message_id", None),
            )

        # JSON body
        try:
            data = res.json() or {}
        except Exception as e:
            return Message(
                role=MessageRole.AGENT,
                content=ErrorContent(message=f"Bad JSON from agent: {e}"),
                parent_message_id=getattr(message, "message_id", None),
            )
        
        # Body-level error? Convert to ErrorContent
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            code = err.get("code") if isinstance(err, dict) else None
            prefix = f"{code}: " if code else ""
            return Message(
                role=MessageRole.AGENT,
                content=ErrorContent(message=f"{prefix}{msg}"),
                parent_message_id=getattr(message, "message_id", None),
            )        

        content = (data.get("content") or "").strip()
        citations = data.get("citations") or []

        meta = None
        if APPEND_CITATIONS and citations:
            meta = Metadata(custom_fields={"citations": citations})

        msg = Message(
            role=MessageRole.AGENT,
            content=TextContent(text=content or "Ответ не найден."),
            parent_message_id=getattr(message, "message_id", None),
            metadata=meta
        )
        return msg

if __name__ == "__main__":
    a2a_host = CONFIG.get("server", {}).get("a2a_host", "0.0.0.0")
    a2a_port = CONFIG.get("server", {}).get("a2a_port", 5050)
    logger.info(f"Starting A2A server on {a2a_host}:{a2a_port}")
    run_server(MyAgentA2A(), host=a2a_host, port=a2a_port, debug=False)
