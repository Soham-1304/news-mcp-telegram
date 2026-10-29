import time
import logging
from typing import List, Dict, Any, Optional
from mcp_server.sources.base import Article
from mcp_server.sources.in_the_world_of_ai import InTheWorldOfAISource
from mcp_server.sources.deeplearning_ai import DeepLearningAISource
from mcp_server.sources.guardian import GuardianSource
from mcp_server.sources.mit_tech_review import MITTechReviewSource
from mcp_server.sources.techcrunch import TechCrunchAISource
from mcp_server.sources.extractor import extract_article_content

logger = logging.getLogger("news_agent.mcp.sources.manager")

class NewsSourceManager:
    """Manages multi-source fetching, caching, and querying across curated tech & AI publications."""

    def __init__(self, cache_ttl_seconds: int = 600):
        self.sources = {
            "intheworldofai": InTheWorldOfAISource(),
            "deeplearning": DeepLearningAISource(),
            "guardian": GuardianSource(),
            "mit": MITTechReviewSource(),
            "techcrunch": TechCrunchAISource(),
        }
        self.cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, Any] = {}
        self._last_fetch_time: Dict[str, float] = {}

    def get_articles_from_source(self, source_key: str, limit: int = 10) -> List[Article]:
        source_key = source_key.lower().strip()
        now = time.time()
        
        target_source = None
        for key, src in self.sources.items():
            if key in source_key or source_key in key or source_key in src.name.lower():
                target_source = (key, src)
                break

        if not target_source:
            logger.warning(f"Unknown news source requested: {source_key}")
            return []

        key, src = target_source
        if key in self._cache and (now - self._last_fetch_time.get(key, 0)) < self.cache_ttl:
            logger.debug(f"Returning cached articles for {key}")
            return self._cache[key][:limit]

        articles = src.fetch_articles(limit=limit)
        self._cache[key] = articles
        self._last_fetch_time[key] = now
        return articles[:limit]

    def get_all_latest_articles(self, limit_per_source: int = 4) -> List[Article]:
        """Fetch latest articles dynamically across all configured news channels."""
        all_articles = []
        for key, src in self.sources.items():
            all_articles.extend(self.get_articles_from_source(key, limit=limit_per_source))
        return all_articles

    def search_articles(self, query: str, limit: int = 10) -> List[Article]:
        """Search all cached articles or fetch fresh ones matching keywords."""
        all_articles = self.get_all_latest_articles(limit_per_source=6)
        query_terms = [q.strip().lower() for q in query.split() if len(q.strip()) > 2]
        
        matched = []
        for art in all_articles:
            searchable_text = f"{art.title} {art.summary} {art.topic} {art.writer} {art.source}".lower()
            if any(term in searchable_text for term in query_terms):
                matched.append(art)
        
        return matched[:limit] if matched else all_articles[:limit]

    def read_article(self, url: str) -> Optional[str]:
        """Extracts full body text of an article for deep dives."""
        return extract_article_content(url)
