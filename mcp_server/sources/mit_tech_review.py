import logging
from datetime import datetime, timezone
from typing import List
import feedparser
from mcp_server.sources.base import BaseNewsSource, Article

logger = logging.getLogger("news_agent.mcp.sources.mit")

class MITTechReviewSource(BaseNewsSource):
    name = "MIT Technology Review"
    FEED_URL = "https://www.technologyreview.com/feed/"

    def fetch_articles(self, limit: int = 10) -> List[Article]:
        articles = []
        try:
            feed = feedparser.parse(self.FEED_URL)
            for entry in feed.entries[:limit]:
                title = entry.get("title", "").strip()
                url = entry.get("link", "").strip()
                writer = entry.get("author") or entry.get("dc_creator") or "MIT Technology Review"
                
                published_at = ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    published_at = dt.isoformat()
                elif hasattr(entry, "published"):
                    published_at = str(entry.published)

                summary = entry.get("summary", "") or entry.get("description", "")
                if "<" in summary and ">" in summary:
                    import re
                    summary = re.sub(r"<[^>]+>", "", summary).strip()

                topic = "AI & Emerging Tech"
                tags = [t.get("term") for t in entry.get("tags", []) if t.get("term")]
                if tags:
                    topic = ", ".join(tags[:3])

                articles.append(Article(
                    title=title,
                    url=url,
                    source=self.name,
                    writer=writer,
                    topic=topic,
                    published_at=published_at,
                    location="Cambridge, MA",
                    summary=summary[:400]
                ))
        except Exception as e:
            logger.error(f"Error fetching MIT Technology Review articles: {e}")
        return articles

