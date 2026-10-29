import json
import logging
from typing import List, Dict, Any, Tuple
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.config import (
    NEWS_DB_PATH,
    MAX_ARTICLE_AGE_HOURS,
    FUZZY_MATCH_THRESHOLD
)
from storage.deduplicator import NewsDeduplicator
from agent.mcp_client import (
    mcp_client,
    search_news_remote,
    read_article_remote,
    get_source_news_remote,
    REMOTE_MCP_TOOLS
)

logger = logging.getLogger("news_agent.tools")

deduplicator = NewsDeduplicator(
    db_path=NEWS_DB_PATH,
    max_age_hours=MAX_ARTICLE_AGE_HOURS,
    fuzzy_threshold=FUZZY_MATCH_THRESHOLD
)

# Standard tool aliases for bot handlers
search_news_tool = search_news_remote
read_article_tool = read_article_remote
get_source_news_tool = get_source_news_remote


def get_fresh_articles_for_digest(chat_id: int = None, limit_per_source: int = 4) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Decoupled Handshake:
    1. Makes an RPC call over the network (SSE) to the standalone MCP Server.
    2. Receives raw serialized headlines.
    3. Runs SQLite deduplication & freshness filtering.
    """
    try:
        logger.info("Calling standalone MCP Server tool 'get_daily_headlines' over protocol...")
        raw_json = mcp_client.call_tool_sync("get_daily_headlines", {"limit_per_source": limit_per_source})
        raw_articles = json.loads(raw_json)
    except Exception as e:
        logger.warning(f"Remote MCP server call failed ({e}). Falling back to direct source manager.")
        from mcp_server.sources.manager import NewsSourceManager
        mgr = NewsSourceManager(cache_ttl_seconds=300)
        raw_articles = [a.to_dict() for a in mgr.get_all_latest_articles(limit_per_source=limit_per_source)]

    fresh, rejected = deduplicator.filter_fresh_and_unique(raw_articles, chat_id=chat_id)
    return fresh, rejected


def record_delivered_articles(articles: List[Dict[str, Any]], chat_id: int = None) -> None:
    """Persists sent articles into SQLite to prevent future repetition."""
    deduplicator.record_delivered(articles, chat_id=chat_id)


# Tools exposed to the LangGraph LLM Agent
AGENT_TOOLS = REMOTE_MCP_TOOLS
