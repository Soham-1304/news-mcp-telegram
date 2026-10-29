import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mcp_server.server import mcp

# Starlette ASGI application exposing /sse for remote clients
app = mcp.sse_app()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8001))
    print(f"📡 Starting Standalone MCP Server on http://0.0.0.0:{port}/sse ...")
    uvicorn.run(app, host="0.0.0.0", port=port)

