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

search_news_tool = search_news_remote
read_article_tool = read_article_remote
get_source_news_tool = get_source_news_remote


def get_fresh_articles_for_digest(
    chat_id: int = None,
    target_count: int = 5,
    max_iter: int = 3
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Progressive Deep-Fetch Handshake Loop:
    If the top articles have already been delivered to this user,
    iteratively increases crawl depth (up to max_iter=3) to find unread, fresh stories.
    """
    fresh_accumulated = []
    rejected_accumulated = []
    
    # Progressively deeper limits: 4 -> 8 -> 15 articles per source
    depth_tiers = [4, 8, 15]

    for iteration in range(min(max_iter, len(depth_tiers))):
        current_limit = depth_tiers[iteration]
        logger.info(f"Deduplication loop iter {iteration + 1}/{max_iter} (depth={current_limit} per source)...")
        
        try:
            raw_json = mcp_client.call_tool_sync("get_daily_headlines", {"limit_per_source": current_limit})
            raw_articles = json.loads(raw_json)
        except Exception as e:
            logger.warning(f"Remote MCP call failed ({e}). Falling back to local manager.")
            from mcp_server.sources.manager import NewsSourceManager
            mgr = NewsSourceManager(cache_ttl_seconds=300)
            raw_articles = [a.to_dict() for a in mgr.get_all_latest_articles(limit_per_source=current_limit)]

        fresh, rejected = deduplicator.filter_fresh_and_unique(raw_articles, chat_id=chat_id)
        
        # Merge newly discovered fresh articles
        existing_urls = {a["url"] for a in fresh_accumulated}
        for f in fresh:
            if f["url"] not in existing_urls:
                fresh_accumulated.append(f)
                existing_urls.add(f["url"])

        rejected_accumulated.extend(rejected)

        # If we have enough fresh unread articles for a solid briefing, stop early!
        if len(fresh_accumulated) >= target_count:
            logger.info(f"Found {len(fresh_accumulated)} fresh articles at iteration {iteration + 1}. Proceeding.")
            break

    return fresh_accumulated, rejected_accumulated


def record_delivered_articles(articles: List[Dict[str, Any]], chat_id: int = None) -> None:
    """Persists sent articles into SQLite to prevent future repetition."""
    deduplicator.record_delivered(articles, chat_id=chat_id)


AGENT_TOOLS = REMOTE_MCP_TOOLS
