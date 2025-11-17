from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any, Dict
from langchain_core.runnables import RunnableLambda

# Import the compiled runnable graph directly
from config import CONFIG
from chain_graph import build_agent_graph
from utils.logger import get_logger

logger = get_logger()

app = FastAPI(title="Agent Graph - Sync API")

class InvokeRequest(BaseModel):
    question: str

# filter the output to exclude internal state tags
def _select_api_output(state: Dict[str, Any]) -> Dict[str, Any]:
    # logger.debug("Selecting API output from state: %s", state)
    if state.get("error"):
        return {"error": state["error"]}
    
    res = {"content": state.get("content", "")}
    c = state.get("citations")
    if c:
        res["citations"] = c
    return res

# Build compiled runnable for sync invoke and project fields
runnable = build_agent_graph(CONFIG, rag_tool=None) | RunnableLambda(_select_api_output)

@app.post("/invoke")
async def invoke(body: InvokeRequest) -> Dict[str, Any]:
    try:
        out = await runnable.ainvoke({"question": body.question})

        # If the graph produced an error payload, return HTTP 500 with that body
        if isinstance(out, dict) and out.get("error"):
            return JSONResponse(status_code=500, content=out)

        return out if isinstance(out, dict) else {"content": str(out)}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": str(e)}},
        )
