import uvicorn
from .config import CONFIG

def main():
    server = CONFIG.get("server", {})
    host = server.get("host", "0.0.0.0")
    port = int(server.get("port", 8081))
    reload = bool(server.get("reload", False))
    uvicorn.run("agentservice.app:app", host=host, port=port, reload=reload)

if __name__ == "__main__":
    main()
