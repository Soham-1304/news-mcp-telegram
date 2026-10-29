import os
import sqlite3
import logging
from datetime import datetime
from typing import Annotated, Sequence, TypedDict, Dict, Any, List

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.sqlite import SqliteSaver

from agent.config import (
    GROQ_API_KEY,
    DEFAULT_MODEL,
    MEMORY_DB_PATH
)
from agent.prompts import NEWSLETTER_PROMPT, CHAT_SYSTEM_PROMPT
from agent.tools import (
    AGENT_TOOLS,
    get_fresh_articles_for_digest,
    record_delivered_articles
)

logger = logging.getLogger("news_agent.workflow")

# -----------------------------------------------------------------------------
# 1. State Definition
# -----------------------------------------------------------------------------
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


# -----------------------------------------------------------------------------
# 2. LLM Setup with Priority: 20b -> 27b -> 120b (Ultra-resilient)
# -----------------------------------------------------------------------------
def get_resilient_llm():
    primary_20b = ChatGroq(
        api_key=GROQ_API_KEY,
        model="openai/gpt-oss-20b",
        temperature=0.3,
        max_retries=0
    )
    fallback_qwen = ChatGroq(
        api_key=GROQ_API_KEY,
        model="qwen/qwen3.8-27b",
        temperature=0.3,
        max_retries=0
    )
    fallback_120b = ChatGroq(
        api_key=GROQ_API_KEY,
        model="openai/gpt-oss-120b",
        temperature=0.3,
        max_retries=1
    )

    return primary_20b.with_fallbacks([fallback_qwen, fallback_120b])


llm = get_resilient_llm()
llm_with_tools = llm.bind_tools(AGENT_TOOLS)


# -----------------------------------------------------------------------------
# 3. Graph Nodes
# -----------------------------------------------------------------------------
def call_model(state: AgentState) -> Dict[str, Any]:
    raw_messages = list(state["messages"])
    
    # Maintain a sliding window of the last 6 conversational messages to stay under TPM limits
    windowed_messages = raw_messages[-6:] if len(raw_messages) > 6 else raw_messages
    
    # Always ensure system prompt leads the context
    if not windowed_messages or not isinstance(windowed_messages[0], SystemMessage):
        messages = [SystemMessage(content=CHAT_SYSTEM_PROMPT)] + windowed_messages
    else:
        messages = windowed_messages
    
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


# -----------------------------------------------------------------------------
# 4. Compile StateGraph with SQLite Memory Checkpointer
# -----------------------------------------------------------------------------
def build_agent_graph():
    os.makedirs(os.path.dirname(MEMORY_DB_PATH), exist_ok=True)
    db_conn = sqlite3.connect(MEMORY_DB_PATH, check_same_thread=False)
    checkpointer = SqliteSaver(db_conn)
    checkpointer.setup()

    builder = StateGraph(AgentState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(AGENT_TOOLS))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")

    return builder.compile(checkpointer=checkpointer), checkpointer


agent_graph, memory_checkpointer = build_agent_graph()


# -----------------------------------------------------------------------------
# 5. High-Level Agent API (Token-Optimized to prevent 429 Rate Limits)
# -----------------------------------------------------------------------------
def generate_newsletter(chat_id: int = None, limit_per_source: int = 4, **kwargs) -> str:
    """
    Executes daily news briefing:
    1. Runs progressive crawl loop with SQLite deduplication.
    2. Selects top 5-6 fresh, unread articles with condensed snippets (<1000 tokens).
    3. Synthesizes a structured morning newsletter without exhausting TPM limits.
    4. Commits delivered articles to SQLite.
    """
    logger.info(f"Generating newsletter for chat_id={chat_id}")
    
    fresh_articles, rejected = get_fresh_articles_for_digest(chat_id=chat_id, limit_per_source=limit_per_source)
    
    if not fresh_articles:
        return (
            "✨ <b>All Caught Up!</b>\n\n"
            "You have already received the latest news from In The World of AI, DeepLearning.AI, The Guardian, "
            "MIT Technology Review, and TechCrunch AI.\n\n"
            "Our deduplication filter prevented repeating any previously delivered stories.\n"
            "Feel free to ask me questions about today's earlier news or use <code>/reset_history</code> to test from scratch!"
        )

    # Select top 5-6 articles and condense snippets to keep token usage well under 1,000 tokens!
    selected_articles = fresh_articles[:6]
    articles_text = []
    for i, a in enumerate(selected_articles, 1):
        clean_summary = (a.get("summary") or "").strip()[:180]
        articles_text.append(
            f"[{i}] {a['title']}\n"
            f"    Source: {a['source']} | URL: {a['url']}\n"
            f"    Snippet: {clean_summary}...\n"
        )
    
    current_date = datetime.now().strftime("%B %d, %Y")
    formatted_prompt = NEWSLETTER_PROMPT.format(
        current_date=current_date,
        articles_text="\n".join(articles_text)
    )

    compiler_llm = get_resilient_llm()
    response = compiler_llm.invoke([
        SystemMessage(content="You are a professional AI news editor. Output clean, high-signal Telegram newsletter text."),
        HumanMessage(content=formatted_prompt)
    ])
    newsletter_text = response.content

    record_delivered_articles(selected_articles, chat_id=chat_id)

    if chat_id:
        config = {"configurable": {"thread_id": str(chat_id)}}
        # Efficiently save delivery memory directly into checkpointer without triggering an extra LLM call
        delivered_titles = ", ".join([f"'{a['title']}'" for a in selected_articles[:4]])
        agent_graph.update_state(
            config,
            {
                "messages": [
                    AIMessage(content=f"Delivered morning digest on {current_date} covering: {delivered_titles}.")
                ]
            },
            as_node="agent"
        )

    return newsletter_text


def chat_with_agent(chat_id: int, user_message: str) -> str:
    """
    Handles user chat, topic queries, and follow-ups with full conversational memory.
    """
    config = {"configurable": {"thread_id": str(chat_id)}}
    inputs = {"messages": [HumanMessage(content=user_message)]}
    
    result = agent_graph.invoke(inputs, config=config)
    messages = result.get("messages", [])
    
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content
            
    return "I processed your request, but found no matching news reports. What specific topic would you like to search?"
