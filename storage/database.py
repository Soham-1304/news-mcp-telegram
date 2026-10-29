import os
import sqlite3
import logging
from typing import Optional

logger = logging.getLogger("news_agent.storage.database")

def get_db_path(db_setting: Optional[str] = None) -> str:
    """Return the absolute path to the SQLite database file."""
    if not db_setting:
        db_setting = os.getenv("NEWS_DB_PATH", "data/news_history.db")
    
    # If relative path, resolve relative to project root
    if not os.path.isabs(db_setting):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_path = os.path.join(project_root, db_setting)
    else:
        full_path = db_setting
        
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    return full_path


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Get a SQLite connection configured with WAL mode and row factory."""
    path = get_db_path(db_path)
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def initialize_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables for delivered news and audit records."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS delivered_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    content_hash TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    writer TEXT DEFAULT '',
                    topic TEXT DEFAULT '',
                    published_at TEXT DEFAULT '',
                    location TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    telegram_chat_id INTEGER
                );
            """)
            
            # Indexes for ultra-fast lookup
            conn.execute("CREATE INDEX IF NOT EXISTS idx_delivered_url ON delivered_news (url);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_delivered_hash ON delivered_news (content_hash);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_delivered_source_date ON delivered_news (source, published_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_delivered_chat ON delivered_news (telegram_chat_id);")
            
        logger.info("Delivered news database initialized successfully.")
    finally:
        conn.close()

