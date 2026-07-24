import structlog
from src.schemas import QueryRewriteOutput
from src.config import settings
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage


async def rewrite_user_query(query: str, chat_history: list) -> QueryRewriteOutput:
    recent_history = chat_history[-6:] if len(chat_history) > 6 else char_history

