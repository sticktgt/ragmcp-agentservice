from __future__ import annotations
from typing import Optional, Dict, Any
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from utils.logger import get_logger

logger = get_logger()

# Module-level singletons
_mcp_client: Optional[MultiServerMCPClient] = None
_mcp_tool: Optional[Any] = None
_mcp_lock = asyncio.Lock()

async def get_mcp_tool(cfg: Dict[str, Any]) -> Optional[Any]:
    """
    Lazily initialize MultiServerMCPClient and pick the configured tool.
    Returns a LangChain Tool-like object with .ainvoke(...)
    """
    global _mcp_client, _mcp_tool
    if _mcp_tool is not None:
        return _mcp_tool

    async with _mcp_lock:
        if _mcp_tool is not None:
            return _mcp_tool

        mcp_cfg = (cfg.get("mcp") or {})
        servers = mcp_cfg.get("servers") or {
            "rag": {"transport": "streamable_http", "url": mcp_cfg.get("url")}
        }
        tool_name = mcp_cfg.get("toolName") or "rag.search"
        timeout = int(mcp_cfg.get("timeoutSec", 15))

        logger.info("Initializing MCP client (servers=%s)", list(servers.keys()))
        _mcp_client = MultiServerMCPClient(servers)

        try:
            tools = await asyncio.wait_for(_mcp_client.get_tools(), timeout=timeout)
        except Exception as e:
            logger.error("MCP get_tools failed: %s", e)
            return None

        _mcp_tool = next((t for t in tools if getattr(t, "name", None) == tool_name), None)
        if not _mcp_tool:
            logger.warning("MCP tool '%s' not found; continuing without RAG.", tool_name)
        else:
            logger.info("MCP tool '%s' ready.", tool_name)
        return _mcp_tool
