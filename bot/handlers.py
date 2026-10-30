import re
import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from agent.workflow import generate_newsletter, chat_with_agent
from agent.tools import search_news_tool
from agent.config import SCHEDULE_TIME, SCHEDULE_TIMEZONE
from bot.formatter import clean_and_format_for_telegram, chunk_message, html_to_plain_text_with_links
from storage.database import get_connection, add_subscriber

logger = logging.getLogger("news_agent.bot.handlers")

STANDALONE_DIGEST_PHRASES = {
    "more news",
    "find more news",
    "give me more news",
    "show more news",
    "daily news",
    "daily digest",
    "daily briefing",
    "morning digest",
    "morning briefing",
    "today's news",
    "todays news",
    "news digest",
}


async def send_formatted_message(update: Update, text: str, reply_to_message: bool = False):
    clean_html = clean_and_format_for_telegram(text)
    chunks = chunk_message(clean_html, max_chars=3900)

    for i, chunk in enumerate(chunks):
        try:
            if reply_to_message and i == 0 and update.message:
                await update.message.reply_text(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            elif update.effective_chat:
                await update.effective_chat.send_message(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:
            logger.warning(f"HTML send failed ({e}), sending plain text with preserved links")
            plain_text = html_to_plain_text_with_links(chunk)
            if reply_to_message and i == 0 and update.message:
                await update.message.reply_text(plain_text)
            elif update.effective_chat:
                await update.effective_chat.send_message(plain_text)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    add_subscriber(chat_id)
    if "subscribed_chats" not in context.application.bot_data:
        context.application.bot_data["subscribed_chats"] = set()
    context.application.bot_data["subscribed_chats"].add(chat_id)

    welcome_text = (
        f"👋 <b>Welcome, {user.first_name}!</b> I am <b>Techno</b>, your AI & Tech News Intelligence Agent.\n\n"
        f"📡 <b>What I do:</b>\n"
        f"• Track <b>In The World of AI</b>, <b>DeepLearning.AI</b>, <b>The Guardian</b>, <b>MIT Technology Review</b>, and <b>TechCrunch AI</b>.\n"
        f"• Run an intelligent <b>SQLite Deduplication & Fuzzy Matching</b> handshake so you never see repeat stories.\n"
        f"• Deliver a crisp intelligence briefing every morning at <b>{SCHEDULE_TIME} ({SCHEDULE_TIMEZONE})</b>.\n"
        f"• Answer questions on specific topics (e.g. <i>'What are Google Q3 earnings?'</i> or <i>'Tell me about Gemini 4 Carbon'</i>)!\n\n"
        f"⚡ <b>Commands:</b>\n"
        f"• <code>/digest</code> or <code>/news</code> - Get today's general briefing\n"
        f"• <code>/search &lt;topic&gt;</code> - Search news across all sources\n"
        f"• <code>/reset_history</code> - Clear seen news history (for testing)\n"
        f"• <code>/clear</code> - Reset conversation memory\n"
        f"• Or simply <b>ask me any question</b> directly!"
    )
    await send_formatted_message(update, welcome_text)


async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    status_msg = await update.message.reply_text("🔄 <i>Gathering and synthesizing fresh intelligence...</i>", parse_mode=ParseMode.HTML)
    
    try:
        newsletter = generate_newsletter(chat_id=chat_id)
        await status_msg.delete()
        await send_formatted_message(update, newsletter)
    except Exception as e:
        logger.error(f"Error generating digest: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Failed to generate news digest: {e}")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Please provide a query, e.g.: <code>/search reasoning models</code>", parse_mode=ParseMode.HTML)
        return
    
    query = " ".join(context.args)
    status_msg = await update.message.reply_text(f"🔍 Searching news for <b>'{query}'</b>...", parse_mode=ParseMode.HTML)
    
    try:
        results = search_news_tool.invoke({"query": query})
        await status_msg.delete()
        await send_formatted_message(update, f"📰 <b>Search Results for '{query}':</b>\n\n{results}")
    except Exception as e:
        logger.error(f"Error in search command: {e}")
        await status_msg.edit_text(f"❌ Search error: {e}")


async def reset_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resets delivered news SQLite records so user can re-trigger briefing immediately."""
    chat_id = update.effective_chat.id
    conn = get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM delivered_news")
        await update.message.reply_text("🔄 <b>Delivered news history cleared!</b> You can now send <code>/digest</code> to get a fresh briefing.", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error clearing history: {e}")
        await update.message.reply_text(f"⚠️ Error resetting history: {e}")
    finally:
        conn.close()


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wipes conversational checkpoints for the current user to eliminate accumulated token context."""
    chat_id = update.effective_chat.id
    try:
        import sqlite3
        from agent.config import MEMORY_DB_PATH
        conn = sqlite3.connect(MEMORY_DB_PATH)
        with conn:
            conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (str(chat_id),))
            conn.execute("DELETE FROM writes WHERE thread_id = ?", (str(chat_id),))
        conn.close()
    except Exception as e:
        logger.warning(f"Note on clearing memory: {e}")

    await update.message.reply_text("🧹 <b>Conversation memory refreshed!</b> Fresh token window active.", parse_mode=ParseMode.HTML)


async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = (update.message.text or "").strip()
    norm_text = re.sub(r"[^\w\s]", "", user_text.lower()).strip()
    
    if norm_text in STANDALONE_DIGEST_PHRASES:
        logger.info(f"Triggering general digest for standalone phrase: '{norm_text}'")
        status_msg = await update.message.reply_text("🔄 <i>Digging deeper to find newer, unread stories for you...</i>", parse_mode=ParseMode.HTML)
        try:
            newsletter = generate_newsletter(chat_id=chat_id)
            await status_msg.delete()
            await send_formatted_message(update, newsletter)
            return
        except Exception as e:
            logger.error(f"Error generating more news: {e}", exc_info=True)
            await status_msg.edit_text(f"⚠️ Could not fetch more news: {e}")
            return

    await update.effective_chat.send_action("typing")
    try:
        reply = chat_with_agent(chat_id=chat_id, user_message=user_text)
        await send_formatted_message(update, reply, reply_to_message=True)
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Encountered an error: {e}")
