import os
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is loaded from news-agent-telegram root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

# LLM Configurations
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openai/gpt-oss-20b")

# Telegram Bot Configurations
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8730943627")

# Schedule Settings
SCHEDULE_TIME = os.getenv("SCHEDULE_TIME", "07:00")
SCHEDULE_TIMEZONE = os.getenv("SCHEDULE_TIMEZONE", "Asia/Kolkata")

# SQLite Database Paths
NEWS_DB_PATH = str(PROJECT_ROOT / os.getenv("NEWS_DB_PATH", "data/news_history.db"))
MEMORY_DB_PATH = str(PROJECT_ROOT / os.getenv("MEMORY_DB_PATH", "data/agent_memory.db"))

# Deduplication Settings
MAX_ARTICLE_AGE_HOURS = int(os.getenv("MAX_ARTICLE_AGE_HOURS", "48"))
FUZZY_MATCH_THRESHOLD = float(os.getenv("FUZZY_MATCH_THRESHOLD", "85.0"))

