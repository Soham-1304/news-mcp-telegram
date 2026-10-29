import os
import sys
import json
import logging
from typing import Optional

# Setup path so imports work cleanly
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except (ImportError, ModuleNotFoundError):
    from mcp.server.fastmcp import FastMCP

from mcp_server.sources.manager import NewsSourceManager

logger = logging.getLogger("news_agent.mcp.server")

# Initialize Server & Source Manager
mcp = FastMCP(
    "NewsAggregatorMCP",
    description="Multi-source Tech & AI News Server covering DeepLearning.AI, The Guardian, MIT Technology Review, and TechCrunch AI"
)

manager = NewsSourceManager(cache_ttl_seconds=900)


@mcp.tool()
def get_daily_headlines(limit_per_source: int = 4) -> str:
    """Fetch the latest top headlines across all 4 curated sources (DeepLearning.AI, The Guardian, MIT, TechCrunch).
    
    Returns a JSON string containing a list of articles with:
    - title
    - source
    - writer
    - topic
    - published_at
    - location
    - url
    - summary
    """
    articles = manager.get_all_latest_articles(limit_per_source=limit_per_source)
    return json.dumps([a.to_dict() for a in articles], indent=2)


@mcp.tool()
def get_source_news(source: str, limit: int = 5) -> str:
    """Fetch recent news articles from a specific source.
    
    Args:
        source: Publication name, e.g. 'deeplearning', 'guardian', 'mit', 'techcrunch'
        limit: Maximum number of articles to return (1-10)
    """
    articles = manager.get_articles_from_source(source, limit=limit)
    return json.dumps([a.to_dict() for a in articles], indent=2)


@mcp.tool()
def search_news(query: str, limit: int = 6) -> str:
    """Search tech and AI news articles by keywords, topics, companies, or concepts.
    
    Args:
        query: Topic or keywords to search for, e.g. 'reasoning models', 'Anthropic', 'robotics'
        limit: Maximum matching articles to return
    """
    articles = manager.search_articles(query, limit=limit)
    return json.dumps([a.to_dict() for a in articles], indent=2)


@mcp.tool()
def read_article_full_text(url: str) -> str:
    """Fetch the clean, full-text content of a specific news article by its URL.
    Use this when the user asks for deep explanations or detailed summaries of a specific story.
    
    Args:
        url: The web URL of the article
    """
    content = manager.read_article(url)
    if not content:
        return f"Could not retrieve full text from {url}. It may be paywalled or unreachable."
    return content


if __name__ == "__main__":
    mcp.run()

