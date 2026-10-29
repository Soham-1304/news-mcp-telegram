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

    def search_articles(self, query: str, limit: int = 6) -> List[Article]:
        """
        Search all curated cached articles first.
        If fewer than 3 matches found, queries live web news (DuckDuckGo) to ensure
        specific inquiries (e.g. 'Google Q3 earnings', 'Gemini Carbon') always return precise results.
        """
        all_articles = self.get_all_latest_articles(limit_per_source=6)
        query_terms = [q.strip().lower() for q in query.split() if len(q.strip()) > 2]
        
        matched = []
        seen_urls = set()

        # 1. Search curated channels
        for art in all_articles:
            searchable_text = f"{art.title} {art.summary} {art.topic} {art.writer} {art.source}".lower()
            if any(term in searchable_text for term in query_terms):
                matched.append(art)
                seen_urls.add(art.url)

        # 2. If specific query needs more depth, query live news
        if len(matched) < limit:
            try:
                from duckduckgo_search import DDGS
                ddgs = DDGS()
                live_results = list(ddgs.news(query, max_results=(limit - len(matched))))
                for r in live_results:
                    url = r.get("url", "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    matched.append(Article(
                        title=r.get("title", ""),
                        url=url,
                        source=r.get("source", "Live Wire"),
                        writer=r.get("source", "Staff"),
                        topic="Targeted News Query",
                        published_at=r.get("date", ""),
                        location="Global",
                        summary=r.get("body", "")[:350]
                    ))
            except Exception as e:
                logger.warning(f"Live news search fallback failed: {e}")

        return matched[:limit]

    def read_article(self, url: str) -> Optional[str]:
        return extract_article_content(url)
