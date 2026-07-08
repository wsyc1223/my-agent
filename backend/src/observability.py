import logging
from src.config import settings
import os
from langfuse.langchain import CallbackHandler

logger = logging.getLogger(__name__)

LANGFUSE_PUBLIC_KEY = settings.LANGFUSE_PUBLIC_KEY
LANGFUSE_SECRET_KEY = settings.LANGFUSE_SECRET_KEY
LANGFUSE_BASE_URL = settings.LANGFUSE_BASE_URL

os.environ.setdefault("LANGFUSE_PUBLIC_KEY", LANGFUSE_PUBLIC_KEY)
os.environ.setdefault("LANGFUSE_SECRET_KEY", LANGFUSE_SECRET_KEY)
os.environ.setdefault("LANGFUSE_BASE_URL", LANGFUSE_BASE_URL)

def get_langfuse_handler(trace_id: str = None, user_id: str = None, tags: list[str] = None) -> CallbackHandler:
    """
    工厂函数：每次调用返回一个全新的 CallbackHandler 实例，用于防止并发 Trace 串扰。
    """
    trace_context = {}
    if trace_id:
        trace_context["trace_id"] = trace_id

    return CallbackHandler(
        trace_context=trace_context
    )
