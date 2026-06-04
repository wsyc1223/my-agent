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

langfuse_handler = CallbackHandler()


