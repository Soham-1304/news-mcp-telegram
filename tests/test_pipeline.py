import os
import sys
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from storage.database import initialize_db
from storage.deduplicator import NewsDeduplicator
from mcp_server.sources.manager import NewsSourceManager
from bot.telegram_bot import create_bot_application


@pytest.fixture(scope="session")
def setup_test_db():
    test_db = os.path.join(PROJECT_ROOT, "data", "test_suite_news.db")
    initialize_db(test_db)
    yield test_db
    if os.path.exists(test_db):
        os.remove(test_db)


def test_news_sources_fetch():
    """Verify that all 4 news sources fetch real articles."""
    manager = NewsSourceManager(cache_ttl_seconds=60)
    for src_key in ["guardian", "mit", "techcrunch", "deeplearning"]:
        articles = manager.get_articles_from_source(src_key, limit=2)
        assert len(articles) > 0, f"Source '{src_key}' returned zero articles"
        first = articles[0]
        assert first.title, f"Missing title for {src_key}"
        assert first.url.startswith("http"), f"Invalid URL for {src_key}: {first.url}"
        assert first.source, f"Missing source name for {src_key}"


def test_deduplicator_fuzzy_and_exact(setup_test_db):
    """Verify exact hash, column matching, and fuzzy matching deduplication."""
    dedup = NewsDeduplicator(db_path=setup_test_db, fuzzy_threshold=85.0)

    article_a = {
        "title": "Anthropic releases Claude 3.7 Sonnet with hybrid reasoning",
        "url": "https://techcrunch.com/claude-37",
        "source": "TechCrunch AI",
        "writer": "Kyle Wiggers",
        "topic": "AI Models",
        "published_at": "2026-10-29T08:00:00Z"
    }

    # Pass 1: Fresh
    fresh, rejected = dedup.filter_fresh_and_unique([article_a])
    assert len(fresh) == 1
    assert len(rejected) == 0

    # Record delivery
    dedup.record_delivered(fresh)

    # Pass 2: Exact duplicate should be caught
    fresh2, rejected2 = dedup.filter_fresh_and_unique([article_a])
    assert len(fresh2) == 0
    assert len(rejected2) == 1

    # Pass 3: Fuzzy duplicate from another source should be caught
    article_fuzzy = {
        "title": "Anthropic releases Claude 3.7 Sonnet with hybrid reasoning capabilities",
        "url": "https://theguardian.com/claude-37-different-url",
        "source": "The Guardian",
        "writer": "Dan Milmo",
        "topic": "Technology",
        "published_at": "2026-10-29T10:00:00Z"
    }
    fresh3, rejected3 = dedup.filter_fresh_and_unique([article_fuzzy])
    assert len(fresh3) == 0
    assert len(rejected3) == 1
    assert "fuzzy_duplicate" in rejected3[0]["reason"]


def test_telegram_bot_build():
    """Verify Telegram ApplicationBuilder constructs properly."""
    app = create_bot_application()
    assert app is not None
    assert app.job_queue is not None

