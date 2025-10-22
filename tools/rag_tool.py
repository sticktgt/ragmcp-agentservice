from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from langchain_core.tools import tool
import os   

class RagArgs(BaseModel):
    query: str
    k: int = 6
    rerank: Optional[bool] = None
    top_n: Optional[int] = None
    filters: Optional[Dict[str, Any]] = None

class RagItem(BaseModel):
    title: Optional[str] = None
    uri: Optional[str] = None
    snippet: str
    score: Optional[float] = None
    page: Optional[int] = None

def _display_title_from_prov(prov: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    mode = ((cfg.get("mcp", {}) or {}).get("citationDisplay") or "basename").lower()
    show_page = bool((cfg.get("mcp", {}) or {}).get("showPage", True))

    # provenance candidates the MCP service already returns
    orig = prov.get("original_name") or prov.get("title")
    fpath = prov.get("file_path") or prov.get("path") or ""
    page = prov.get("page_number") or prov.get("page")

    # choose base label
    if mode == "full":
        base = fpath or orig or "document"
    elif mode == "relative":
        prefix = (cfg.get("mcp", {}) or {}).get("pathPrefixStrip") or ""
        rel = fpath
        if prefix and rel.startswith(prefix):
            rel = rel[len(prefix):].lstrip("/\\")
        base = rel or orig or os.path.basename(fpath) or "document"
    else:  # basename (default)
        base = orig or os.path.basename(fpath) or "document"

    # add page
    if show_page and page:
        base = f"{base} (p.{page})"
    return base

def normalize_mcp_hits(
    hits: List[Dict[str, Any]],
    cfg: Dict[str, Any]
) -> List[RagItem]:
    out: List[RagItem] = []
    for h in hits or []:
        prov = dict(h.get("provenance") or {})
        title = _display_title_from_prov(prov, cfg)
        page = prov.get("page_number") or prov.get("page")
        out.append(RagItem(
            snippet=h.get("text") or "",
            title=title,
            uri=None,                   # for the future use
            score=h.get("score"),
            page=page,
        ))
    return out

