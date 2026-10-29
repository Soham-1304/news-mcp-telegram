import logging
from typing import Optional
import requests
import trafilatura

logger = logging.getLogger("news_agent.mcp.extractor")

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9"
}

def extract_article_content(url: str, max_chars: int = 4000) -> Optional[str]:
    """
    Downloads and extracts clean readable text from a news article URL.
    Uses custom browser headers and trafilatura to bypass bot-checks and strip boilerplate.
    """
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)
        if resp.status_code != 200:
            logger.warning(f"Failed to fetch webpage ({resp.status_code}): {url}")
            return None
        
        text = trafilatura.extract(
            resp.text,
            url=url,
            include_comments=False,
            include_tables=True,
            no_fallback=False
        )
        if text:
            return text[:max_chars].strip()
        return None
    except Exception as e:
        logger.error(f"Error extracting content from {url}: {e}")
        return None
