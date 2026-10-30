# Techno: AI & Tech News MCP Server + Telegram Autonomous Agent

An autonomous AI agent and Model Context Protocol (MCP) server that aggregates, deduplicates, and delivers daily morning tech and AI intelligence briefings directly to your Telegram with conversational follow-up memory.

---

## 🌟 Key Features

1. **4 Curated Tech & AI Publications**:
   - **DeepLearning.AI** (*The Batch* – Research & editorial breakdowns by Andrew Ng's team)
   - **The Guardian** (*AI & Technology* – Policy, ethics, and global developments)
   - **MIT Technology Review** (*Emerging Technology* – Frontier science, labs, and deep tech)
   - **TechCrunch AI** (*Industry & Startups* – Funding, products, GPUs, and enterprise AI)

2. **Freshness & Deduplication Handshake (SQLite + RapidFuzz)**:
   - Evaluates article publication timestamps (within 48 hours).
   - Exact hash & URL matching against previously delivered news.
   - Column metadata matching: `(source, writer, topic, publication_date)`.
   - **Fuzzy matching** ($\ge 85\%$ token similarity) to filter out overlapping or rewritten stories across days and sources.

3. **LangChain & LangGraph Cognitive Architecture**:
   - StateGraph workflow with cyclic tool execution.
   - Persistent conversation memory backed by `SqliteSaver` (thread-scoped per Telegram chat ID).
   - High-signal synthesis prompt that formats briefings cleanly with emojis, bullet points, and source hyperlinks.

4. **Telegram Bot (`@techn0o_bot`) with Cron Automation**:
   - **Daily Morning Cron**: Automatically pushes the newsletter every morning at **07:00 AM IST** (configurable in `.env`).
   - **Manual On-Demand Trigger**: Send `/digest` or `/news` anytime to get the latest fresh stories.
   - **Interactive Chat**: Ask follow-up questions about any story or request a deep dive (e.g. *"Can you explain how DeepSeek-R1 achieves parity with o1 at 1/3 the cost?"*).
   - **Topic Search**: `/search <query>` to search all feeds on-demand.

---

## 🏗️ Architecture Flow

```
   ┌─────────────────────────────────────────────────────────────┐
   │                       News Sources                          │
   │  [DeepLearning.AI]  [The Guardian]  [MIT Tech]  [TechCrunch] │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                  FastMCP Server & Scrapers                  │
   │  Tools: get_daily_headlines, search_news, read_article      │
   └──────────────────────────────┬──────────────────────────────┘
                                  │ Raw Feeds
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │            SQLite Freshness & Deduplication Engine          │
   │   • Age filter (<48h)  • Hash & URL checks                  │
   │   • Column matching    • RapidFuzz title similarity (≥85%)  │
   │   • Archive DB: data/news_history.db                        │
   └──────────────────────────────┬──────────────────────────────┘
                                  │ Fresh, Non-duplicate News
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │              LangGraph Workflow & Memory Checkpointer       │
   │   • LLM: Groq (openai/gpt-oss-120b)                         │
   │   • Checkpointer: SqliteSaver (data/agent_memory.db)        │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                 Telegram Bot Interface & Cron               │
   │   • Daily JobQueue: 07:00 AM IST                            │
   │   • Commands: /start, /digest, /search, /clear              │
   │   • Multi-turn conversational memory for follow-up Q&A      │
   └─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quickstart & Setup

### 1. Requirements & Virtual Environment
Ensure Python 3.10+ is installed:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment Variables (`.env`)
Configure your keys in `.env`:
```ini
GROQ_API_KEY=gsk_...
DEFAULT_MODEL=openai/gpt-oss-120b

TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_BOT_USERNAME=techn0o_bot

SCHEDULE_TIME=07:00
SCHEDULE_TIMEZONE=Asia/Kolkata

MAX_ARTICLE_AGE_HOURS=48
FUZZY_MATCH_THRESHOLD=85
```

### 3. Running the System

#### Option A: Run the Telegram Bot with Scheduler
```bash
python -m bot.main
```
Once started:
1. Open Telegram and search for `@techn0o_bot`.
2. Click **Start** (or send `/start`).
3. Send `/digest` to receive your first intelligence briefing immediately!
4. Ask any follow-up question (e.g., *"Summarize the MIT story"*).

#### Option B: Run the Standalone MCP Server
To expose the news tools via standard MCP:
```bash
python -m mcp_server.run_server stdio
# or for SSE:
python -m mcp_server.run_server sse
```

---

## 💬 Telegram Bot Commands

| Command | Action |
| :--- | :--- |
| `/start` | Subscribes your chat ID and welcomes you |
| `/digest` or `/news` | Generates and sends today's fresh briefing immediately |
| `/search <query>` | Searches articles matching topics or keywords |
| `/clear` | Clears conversation memory for a fresh context |
| `<any message>` | Interactive chat / follow-ups with full conversation memory |

---

## ☁️ Deployment / Hosting Options

1. **Local Daemon (macOS / Linux)**:
   Run with `nohup` or `tmux` / `systemd`:
   ```bash
   nohup /Users/sohamkarandikar/Documents/LLM_RAG_AI/.venv/bin/python -m bot.main > bot.log 2>&1 &
   ```
2. **Cloud Worker (Railway / Render / Fly.io)**:
   Because the bot uses long-polling (`app.run_polling`), **no inbound ports or SSL certificates are required**. Simply deploy the repo with `python -m bot.main` as a background worker process.

