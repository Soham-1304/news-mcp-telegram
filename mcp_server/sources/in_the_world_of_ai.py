import logging
import re
from datetime import timezone
from typing import List
import requests
from bs4 import BeautifulSoup
import dateparser
from mcp_server.sources.base import BaseNewsSource, Article

logger = logging.getLogger("news_agent.mcp.sources.in_the_world_of_ai")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

class InTheWorldOfAISource(BaseNewsSource):
    name = "In The World of AI"
    BASE_URL = "https://intheworldofai.com"

    def fetch_articles(self, limit: int = 6) -> List[Article]:
        articles = []
        try:
            resp = requests.get(self.BASE_URL, headers=HEADERS, timeout=12)
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch {self.BASE_URL}: status {resp.status_code}")
                return articles

            soup = BeautifulSoup(resp.text, "html.parser")
            seen_urls = set()

            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not href.startswith("/p/"):
                    continue

                full_url = f"{self.BASE_URL}{href}"
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                text = a.get_text(" | ", strip=True)

                # Extract publication date
                date_match = re.search(r"([A-Z][a-z]{2} \d{1,2},? \d{4})", text)
                date_str = date_match.group(1) if date_match else ""
                parsed_dt = dateparser.parse(date_str) if date_str else None
                published_at = parsed_dt.replace(tzinfo=timezone.utc).isoformat() if parsed_dt else ""

                # Extract clean title
                title_el = a.find(["h2", "h3", "h4"])
                raw_title = title_el.get_text(strip=True) if title_el else text
                clean_title = re.sub(r"^[A-Z][a-z]{2} \d{1,2},? \d{4}.*?read", "", raw_title).strip(" |•\n\t")
                if not clean_title or len(clean_title) < 5:
                    clean_title = raw_title

                p_el = a.find("p")
                summary = p_el.get_text(strip=True) if p_el else f"Breaking AI updates from World of AI: {clean_title}"

                articles.append(Article(
                    title=clean_title,
                    url=full_url,
                    source=self.name,
                    writer="World of AI Editorial",
                    topic="Frontier AI & Industry Scoops",
                    published_at=published_at,
                    location="Global",
                    summary=summary[:350]
                ))

                if len(articles) >= limit:
                    break

        except Exception as e:
            logger.error(f"Error scraping InTheWorldOfAI: {e}", exc_info=True)

        return articles

