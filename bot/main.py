import os
import sys
import logging

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from storage.database import initialize_db
from agent.config import (
    TELEGRAM_BOT_TOKEN,
    GROQ_API_KEY,
    DEFAULT_MODEL,
    SCHEDULE_TIME,
    SCHEDULE_TIMEZONE
)
from bot.telegram_bot import create_bot_application

# Configure Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("news_agent.main")


def main():
    print("=" * 65)
    print("🚀 TECHNO: Autonomous News MCP & Telegram AI Agent Starting...")
    print("=" * 65)
    
    # 1. Initialize SQLite Database
    logger.info("Initializing SQLite persistence layer...")
    initialize_db()
    
    # 2. Check credentials
    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY is not set in .env! Please add it.")
        sys.exit(1)
        
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set in .env! Please add it.")
        sys.exit(1)
        
    logger.info(f"Model Provider: Groq ({DEFAULT_MODEL})")
    logger.info(f"Morning Cron Schedule: {SCHEDULE_TIME} ({SCHEDULE_TIMEZONE})")
    logger.info("Starting Telegram Bot polling loop... Press Ctrl+C to stop.")
    
    # 3. Start Telegram Bot
    app = create_bot_application()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

