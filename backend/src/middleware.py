import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import structlog

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. 优先沿用上游传来的 request_id (网关/链路追踪场景)，没有就生成
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        forwarded_for = request.headers.get("X-Forwarded-For")
        client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "unknown")
        user_agent = request.headers.get("User-Agent", "unknown")

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            client_ip=client_ip,
            user_agent=user_agent,
        )

        # 4. 吧request_id 回写到响应头，前端/排查时候能够拿到
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
