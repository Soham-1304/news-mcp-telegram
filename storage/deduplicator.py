import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Tuple
import dateparser
from rapidfuzz import fuzz

from storage.database import get_connection

logger = logging.getLogger("news_agent.storage.deduplicator")


def compute_article_hash(title: str, source: str, published_at: str = "") -> str:
    """Compute an MD5 hash of title, source, and date for exact deduplication."""
    norm_text = f"{source.strip().lower()}::{title.strip().lower()}::{published_at.strip()}"
    return hashlib.md5(norm_text.encode("utf-8")).hexdigest()


class NewsDeduplicator:
    """
    Freshness & Deduplication Engine.
    Ensures the user never receives stale, old, duplicate, or slightly re-worded news articles.
    """

    def __init__(
        self,
        db_path: str = None,
        max_age_hours: int = 48,
        fuzzy_threshold: float = 85.0,
        history_window_days: int = 14,
    ):
        self.db_path = db_path
        self.max_age_hours = max_age_hours
        self.fuzzy_threshold = fuzzy_threshold
        self.history_window_days = history_window_days

    def is_fresh(self, published_at_str: str, source: str = "") -> bool:
        """
        Check if the article was published within the allowed freshness window.
        Daily news feeds (TechCrunch, Guardian, MIT) must be within max_age_hours (e.g. 48h).
        Weekly digests (DeepLearning.AI) are allowed up to 7 days (168h).
        """
        if not published_at_str:
            return True

        try:
            pub_date = dateparser.parse(published_at_str)
            if not pub_date:
                return True

            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
            
            now = datetime.now(timezone.utc)
            age = now - pub_date

            # Allow up to 7 days for weekly publications like The Batch
            allowed_hours = 168 if "deeplearning" in source.lower() or "batch" in source.lower() else self.max_age_hours
            
            if age > timedelta(hours=allowed_hours):
                logger.info(f"Stale article dropped: {age.days} days old (allowed: {allowed_hours}h)")
                return False
                
            return True
        except Exception as e:
            logger.warning(f"Error checking date freshness for '{published_at_str}': {e}")
            return True

    def get_recent_history(self, chat_id: int = None) -> List[Dict[str, Any]]:
        """Fetch previously delivered news articles within the history window."""
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=self.history_window_days)).isoformat()
        
        conn = get_connection(self.db_path)
        try:
            query = """
                SELECT id, url, content_hash, title, source, writer, topic, published_at, location, delivered_at
                FROM delivered_news
                WHERE delivered_at >= ?
            """
            params = [cutoff_date]
            if chat_id:
                query += " AND (telegram_chat_id = ? OR telegram_chat_id IS NULL)"
                params.append(chat_id)

            cursor = conn.cursor()
            rows = cursor.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def filter_fresh_and_unique(
        self,
        articles: List[Dict[str, Any]],
        chat_id: int = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Filters incoming articles against database history and publication dates.
        Returns:
            (fresh_articles, duplicate_or_stale_articles)
        """
        history = self.get_recent_history(chat_id)
        
        existing_urls = {h["url"].strip().lower() for h in history if h.get("url")}
        existing_hashes = {h["content_hash"] for h in history if h.get("content_hash")}
        
        existing_meta_combos = set()
        for h in history:
            pub_date = h.get("published_at", "")[:10]  # YYYY-MM-DD
            combo = (
                (h.get("source") or "").strip().lower(),
                (h.get("writer") or "").strip().lower(),
                (h.get("topic") or "").strip().lower(),
                pub_date
            )
            if combo[0] and combo[1]:
                existing_meta_combos.add(combo)

        fresh_articles = []
        rejected_articles = []

        for art in articles:
            url = (art.get("url") or "").strip().lower()
            title = (art.get("title") or "").strip()
            source = (art.get("source") or "").strip()
            writer = (art.get("writer") or "").strip()
            topic = (art.get("topic") or "").strip()
            published_at = (art.get("published_at") or "").strip()

            # 1. Freshness check
            if not self.is_fresh(published_at, source=source):
                logger.info(f"Article dropped (stale): '{title}' from {source} (pub: {published_at})")
                rejected_articles.append({**art, "reason": "stale_timestamp"})
                continue

            # 2. Exact URL match
            if url and url in existing_urls:
                logger.info(f"Article dropped (URL match): '{title}' ({url})")
                rejected_articles.append({**art, "reason": "exact_url_delivered"})
                continue

            # 3. Content Hash check
            art_hash = compute_article_hash(title, source, published_at)
            if art_hash in existing_hashes:
                logger.info(f"Article dropped (Hash match): '{title}'")
                rejected_articles.append({**art, "reason": "exact_hash_delivered"})
                continue

            # 4. Column Match: (source, writer, topic, date)
            pub_date_only = published_at[:10]
            if writer and source:
                meta_tuple = (source.lower(), writer.lower(), topic.lower(), pub_date_only)
                if meta_tuple in existing_meta_combos:
                    logger.info(f"Article dropped (Metadata match): '{title}' by {writer} on {source}")
                    rejected_articles.append({**art, "reason": "column_metadata_match"})
                    continue

            # 5. Fuzzy Match on Title using RapidFuzz
            is_fuzzy_duplicate = False
            for h in history:
                prev_title = h.get("title", "")
                score = fuzz.token_set_ratio(title.lower(), prev_title.lower())
                if score >= self.fuzzy_threshold:
                    logger.info(
                        f"Article dropped (Fuzzy {score:.1f}% match): '{title}' matches '{prev_title}'"
                    )
                    rejected_articles.append({
                        **art,
                        "reason": f"fuzzy_duplicate_{score:.1f}%",
                        "matched_with": prev_title
                    })
                    is_fuzzy_duplicate = True
                    break

            if is_fuzzy_duplicate:
                continue

            art["content_hash"] = art_hash
            fresh_articles.append(art)
            if url:
                existing_urls.add(url)
            existing_hashes.add(art_hash)

        logger.info(f"Deduplication complete: {len(fresh_articles)} fresh, {len(rejected_articles)} filtered.")
        return fresh_articles, rejected_articles

    def record_delivered(self, articles: List[Dict[str, Any]], chat_id: int = None) -> None:
        """Record successfully sent articles into the SQLite database."""
        if not articles:
            return

        conn = get_connection(self.db_path)
        try:
            with conn:
                for art in articles:
                    url = art.get("url", "")
                    content_hash = art.get("content_hash") or compute_article_hash(
                        art.get("title", ""), art.get("source", ""), art.get("published_at", "")
                    )
                    conn.execute("""
                        INSERT OR IGNORE INTO delivered_news 
                        (url, content_hash, title, source, writer, topic, published_at, location, summary, telegram_chat_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        url,
                        content_hash,
                        art.get("title", ""),
                        art.get("source", ""),
                        art.get("writer", ""),
                        art.get("topic", ""),
                        art.get("published_at", ""),
                        art.get("location", ""),
                        art.get("summary", "")[:500],
                        chat_id
                    ))
            logger.info(f"Recorded {len(articles)} delivered articles in SQLite.")
        finally:
            conn.close()
