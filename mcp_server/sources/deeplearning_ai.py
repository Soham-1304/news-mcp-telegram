import logging
import re
from datetime import datetime, timezone
from typing import List
import requests
from bs4 import BeautifulSoup
import dateparser

from mcp_server.sources.base import BaseNewsSource, Article

logger = logging.getLogger("news_agent.mcp.sources.deeplearning")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

class DeepLearningAISource(BaseNewsSource):
    name = "DeepLearning.AI (The Batch)"
    BATCH_URL = "https://www.deeplearning.ai/the-batch/"

    def fetch_articles(self, limit: int = 6) -> List[Article]:
        articles = []
        try:
            resp = requests.get(self.BATCH_URL, headers=HEADERS, timeout=12)
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch DeepLearning.AI homepage: {resp.status_code}")
                return articles

            soup = BeautifulSoup(resp.text, "html.parser")
            
            # 1. Identify the latest weekly batch tag URL (e.g. /the-batch/tag/oct-23-2026)
            latest_tag_url = None
            latest_date_str = None
            
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/the-batch/tag/" in href:
                    match = re.search(r"/the-batch/tag/([a-z]{3}-\d{1,2}-\d{4})", href)
                    if match:
                        latest_tag_url = f"https://www.deeplearning.ai{href}"
                        latest_date_str = match.group(1).replace("-", " ")
                        break

            if not latest_tag_url:
                logger.warning("Could not find latest weekly Batch tag URL")
                return articles

            # Parse date
            parsed_dt = dateparser.parse(latest_date_str)
            if parsed_dt:
                published_at = parsed_dt.replace(tzinfo=timezone.utc).isoformat()
            else:
                published_at = datetime.now(timezone.utc).isoformat()

            logger.info(f"Fetching latest DeepLearning.AI issue from {latest_tag_url} ({latest_date_str})")
            
            # 2. Fetch the latest issue's individual articles
            tag_resp = requests.get(latest_tag_url, headers=HEADERS, timeout=12)
            if tag_resp.status_code != 200:
                return articles

            tag_soup = BeautifulSoup(tag_resp.text, "html.parser")
            seen_titles = set()

            for art in tag_soup.find_all("article"):
                title_el = art.find(["h2", "h3", "h4"])
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title or len(title) < 8 or "The Batch News & Insights" in title or "Leadership Framework" in title:
                    continue

                if title in seen_titles:
                    continue
                seen_titles.add(title)

                p_el = art.find("p")
                summary = p_el.get_text(strip=True) if p_el else "Weekly deep learning research and architecture analysis."

                articles.append(Article(
                    title=title,
                    url=latest_tag_url,
                    source=self.name,
                    writer="Andrew Ng / The Batch Editorial",
                    topic="Deep Learning & Foundation Models",
                    published_at=published_at,
                    location="Palo Alto, CA",
                    summary=summary[:400]
                ))
                if len(articles) >= limit:
                    break

        except Exception as e:
            logger.error(f"Error scraping DeepLearning.AI: {e}", exc_info=True)
            
        return articles
