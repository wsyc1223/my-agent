import uvicorn
import structlog

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from src.limiter import limiter

from contextlib import asynccontextmanager

from src.graph import pool, checkpointer
from src.logging_config import configure_logging
from src.exceptions import AgentError
from src.middleware import CorrelationIdMiddleware

from src.router.agent import router as agent_router
from src.router.conversation import router as conversation_router
from src.router.auth import router as auth_router
from src.router.file import router as file_router

configure_logging()
logger = structlog.get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    await checkpointer.setup()
    yield
    await pool.close()

app = FastAPI(lifespan=lifespan)

# 自定义限流响应错误
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    logger.warning("rate_limit_exceeded", path=request.url.path, ip=request.client.host if request.client else "unknown")
    return JSONResponse(
        status_code=429,
        content={"code": "RATE_LIMIT_EXCEEDED", "message": "请求过于频繁，请稍后重试", "recoverable": True},
    )

# ===== AgentError 专属 handler: 最精确匹配, 优先于 Exception handler =====
@app.exception_handler(AgentError)
async def agent_error_handler(request: Request, exc: AgentError):
    # 对外按 to_http_response 脱敏； detail 只进日志(带 request_id/conversation_id 由 contextvars 自动带)
    logger.warning("agent_error", code=exc.code, recoverable=exc.recoverable, detail=exc.detail, path=request.url.path)
    return JSONResponse(status_code=exc.http_status, content=exc.to_http_response())

# ===== 参数校验 handler: 422 标准格式 =====
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    logger.info("validation_error", path=request.url.path, errors=exc.errors())
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": "请求参数校验失败", "errors": exc.errors()},
    )

# ==== 兜底 handler: 对外只给通用信息, 栈只进日志 ====
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # logger.exception 自动带 traceback, 不用手拼; 对外绝不返回 str(exc)
    logger.exception("unhandled_error", path=request.url.path, exc_type=type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "服务内部错误，请稍后重试", "recoverable": False},
    )

app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(CorrelationIdMiddleware)

app.include_router(agent_router)
app.include_router(conversation_router)
app.include_router(auth_router)
app.include_router(file_router)
