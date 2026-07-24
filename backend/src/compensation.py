import structlog
import redis.asyncio as aioredis
from src.config import settings

logger = structlog.get_logger(__name__)

async def mark_needs_sync(conversation_id: str, source: str = "chat_stream"):
    """ 在 Redis 中添加需要补正同步的会话标签，设置 24 小时 TTL"""
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        key = f"need_sync:{conversation_id}"
        await r.setex(key, 86400, f"failed_at_{source}")
        await r.aclose()
    except Exception as e:
        logger.warning("mark_needs_sync_redis_failed", conversation_id=conversation_id,error=str(e))
