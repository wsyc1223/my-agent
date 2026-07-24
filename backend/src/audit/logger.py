import uuid
import structlog
from typing import Optional, Dict, Any
from src.db.session import AsyncSessionLocal
from src.audit.repository import AuditLogRepository

logger = structlog.get_logger(__name__)

async def audit_log(
    action: str,
    resource: str,
    user_id: Optional[uuid.UUID] = None,
    conversation_id: Optional[uuid.UUID] = None,
    resource_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    success: bool = True,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    """
    记录安全审计日志辅助函数。
    1. 自动从 structlog contextvars 中提取 client_ip 和 user_agent（如果调用时未显式提供）。
    2. 使用独立的数据库 Session 异步写入 audit_logs 表。
    3. 强容错处理：若审计日志写入失败，仅记日志，绝不向外抛异常影响主接口响应。
    """
    ctx = structlog.contextvars.get_contextvars()
    final_ip = ip_address or ctx.get("client_ip", "unknown")
    final_ua = user_agent or ctx.get("user_agent", "unknown")

    try:
        async with AsyncSessionLocal() as session:
            repo = AuditLogRepository(session)
            await repo.create(
                action=action,
                resource=resource,
                user_id=user_id,
                conversation_id=conversation_id,
                resource_id=resource_id,
                ip_address=final_ip,
                user_agent=final_ua,
                success=success,
                detail=detail,
            )
    except Exception as e:
        logger.error(
            "audit_log_write_failed",
            action=action,
            resource=resource,
            user_id=str(user_id) if user_id else None,
            error=str(e),
        )
