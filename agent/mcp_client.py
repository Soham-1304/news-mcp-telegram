import os
import json
import logging
from typing import List, Dict, Any, Optional
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger("news_agent.mcp_client")

# URL of the decoupled MCP Server (local or hosted on Render)
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "https://techno-news-mcp.onrender.com/sse")


class MCPRemoteClient:
    """
    Decoupled MCP Client that connects over SSE to the remote MCP Server.
    Discovers tools and executes requests purely over the MCP protocol.
    Includes graceful local fallback if the remote server is unreachable.
    """

    def __init__(self, sse_url: str = None):
        self.sse_url = sse_url or MCP_SERVER_URL

    async def call_remote_tool(self, name: str, arguments: Dict[str, Any] = None) -> Any:
        """Invokes a tool on the remote MCP Server via SSE."""
        arguments = arguments or {}
        logger.info(f"Connecting to remote MCP server at {self.sse_url} to call '{name}'...")
        
        async with sse_client(self.sse_url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.call_tool(name, arguments=arguments)
                
                if response.content:
                    first_content = response.content[0]
                    if hasattr(first_content, "text"):
                        return first_content.text
                return str(response)

    def call_tool_sync(self, name: str, arguments: Dict[str, Any] = None) -> Any:
        """Synchronous wrapper with automatic resilient fallback."""
        arguments = arguments or {}
        try:
            import asyncio
            return asyncio.run(self.call_remote_tool(name, arguments))
        except Exception as e:
            logger.warning(f"Remote MCP server '{name}' failed ({e}). Falling back to local execution.")
            from mcp_server.server import get_daily_headlines, get_source_news, search_news, read_article_full_text
            if name == "get_daily_headlines":
                return get_daily_headlines(**arguments)
            elif name == "search_news":
                return search_news(**arguments)
            elif name == "get_source_news":
                return get_source_news(**arguments)
            elif name == "read_article_full_text":
                return read_article_full_text(**arguments)
            raise e


mcp_client = MCPRemoteClient()


# -----------------------------------------------------------------------------
# LangChain Tools backed by the Real Remote MCP Server over SSE
# -----------------------------------------------------------------------------

class SearchNewsRemoteInput(BaseModel):
    query: str = Field(..., description="Keywords or topic to search across tech/AI news sources via remote MCP")


class ReadArticleRemoteInput(BaseModel):
    url: str = Field(..., description="URL of the news article to extract full text from via remote MCP")


class SourceNewsRemoteInput(BaseModel):
    source: str = Field(..., description="Source name: 'intheworldofai', 'deeplearning', 'guardian', 'mit', or 'techcrunch'")
    limit: int = Field(default=5, description="Number of articles to fetch")


@tool("search_news_tool", args_schema=SearchNewsRemoteInput)
def search_news_remote(query: str) -> str:
    """Search tech and AI news articles across remote MCP Server."""
    return mcp_client.call_tool_sync("search_news", {"query": query})


@tool("read_article_tool", args_schema=ReadArticleRemoteInput)
def read_article_remote(url: str) -> str:
    """Extract and read full text of a news article via the remote MCP Server."""
    return mcp_client.call_tool_sync("read_article_full_text", {"url": url})


@tool("get_source_news_tool", args_schema=SourceNewsRemoteInput)
def get_source_news_remote(source: str, limit: int = 5) -> str:
    """Fetch latest articles specifically from one source via remote MCP."""
    return mcp_client.call_tool_sync("get_source_news", {"source": source, "limit": limit})


REMOTE_MCP_TOOLS = [search_news_remote, read_article_remote, get_source_news_remote]
