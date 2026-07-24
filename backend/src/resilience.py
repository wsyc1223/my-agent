"""  LLM 调用鲁棒性: Deepseek(OpenAI 兼容) 异常 -> 自定义异常映射。 """
import asyncio
import time
import structlog
from langchain_core.messages import trim_messages
from src.config import settings
from langgraph.types import RetryPolicy
import openai
from src.exceptions import (
    LLMError, LLMRateLimitError, LLMTimeoutError, LLMServerError,
    LLMContextOverflowError, LLMBalanceError, LLMAuthError, LLMCircuitOpenError
)

logger = structlog.get_logger(__name__)

# 上下文超限的错误消息特征串 (OpenAI/Deepseek 返回的 400 文案里面会出现)
_CONTEXT_OVERFLOW_MARKERS = ("context length", "context_window", "maximum context", "too long")

def map_openai_error(exc: BaseException) -> LLMError:
    """ 把 openai SDK 异常映射到自定义的 LLM 异常。 未识别统一归为 LLMError。"""
    # 1. 超时: APITimeoutError 是 APIConnectionError 的子类， 必须先判断
    if isinstance(exc, (openai.APITimeoutError, asyncio.TimeoutError)):
        return LLMTimeoutError("LLM 调用超时", detail=str(exc))

    # 2. 鉴权失败 （401)
    if isinstance(exc, openai.AuthenticationError):
        return LLMAuthError("LLM 鉴权失败", detail=str(exc))

    # 3. 限流 （429）
    if isinstance(exc, openai.RateLimitError):
        return LLMRateLimitError("LLM 触发限流", detail=str(exc))

    # 4. 400: 判断是否上下文超限
    if isinstance(exc, openai.BadRequestError):
        msg = str(exc).lower()
        if any(m in msg for m in _CONTEXT_OVERFLOW_MARKERS):
            return LLMContextOverflowError("LLM 上下文超限", detail=str(exc))
        return LLMError("LLM 请求参数错误", detail=str(exc))

    # 5. 5xx 服务端错误 (专属类)
    if isinstance(exc, openai.InternalServerError):
        return LLMServerError("LLM 服务端错误", detail=str(exc))

    # 6. 网络连接错误 (非超时), 瞬时抖动, 归为可重试
    if isinstance(exc, openai.APIConnectionError):
        return LLMServerError("LLM 网络连接失败", detail=str(exc))

    # 7. 其他带状态码的: 402 余额等无专属类的走这里， 按 status_code 细分
    if isinstance(exc, openai.APIStatusError):
        status = getattr(exc, "status_code", None)
        if status == 402:
            return LLMBalanceError("LLM 账户余额不足", detail=str(exc))
        if status is not None and 500 <= status < 600:
            return LLMServerError("LLM 服务端错误", detail=str(exc))
        return LLMError("LLM 调用失败", detail=str(exc))

    # 8. 兜底( APIError 等)
    return LLMError("LLM 调用失败", detail=str(exc))

class CircuitBreaker:
    """ 轻量进程内熔断器: closed/open/half-open 三态。"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int, recovery_timeout: float):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = self.CLOSED
        self.failure_count = 0
        self.opened_at = 0.0

    def allow_request(self) -> bool:
        """ CLOSED/半开冷却到期 -> 放行; OPEN 未到期 -> 拦截。"""
        if self.state == self.OPEN:
            if time.monotonic() - self.opened_at >= self.recovery_timeout:
                self.state = self.HALF_OPEN # 冷却到期， 转半开放一个试探
                return True
            return False
        return True # CLOSSED 或 HALF_OPEN 都放行

    def record_success(self):
        self.failure_count = 0
        self.state = self.CLOSED

    def record_failure(self):
        self.failure_count += 1
        if self.state == self.HALF_OPEN:
            # 半开试探失败 -> 回到 OPEN 重新冷却
            self.state = self.OPEN
            self.opened_at = time.monotonic()
        elif self.failure_count >= self.failure_threshold:
            # 正常闭合期异常次数达到上限，拉闸
            self.state = self.OPEN
            self.opened_at = time.monotonic()

LLM_BREAKER = CircuitBreaker(
    failure_threshold=settings.LLM_BREAKER_FAILURE_THRESHOLD,
    recovery_timeout=settings.LLM_BREAKER_RECOVERY_TIMEOUT,
)

_BREAKER_TRIPPABLE = (LLMRateLimitError, LLMTimeoutError, LLMServerError)


async def safe_ainvoke(llm, *args, **kwargs):
    """ 调用 LLM, 把 openai 异常映射为自定义异常，供节点 RetryPolicy 按类型重试，
    仅做异常翻译，不做重试--重试由 LangGraph RetryPolicy 在节点层处理"""
    if not LLM_BREAKER.allow_request():
        # 熔断开启: 快速失败，不调 LLM、 不重试 (CircuitOpenError 不在 retry_on)
        raise LLMCircuitOpenError("LLM 熔断器开启， 请稍后重试")
    try:
        result = await llm.ainvoke(*args, **kwargs)
    except openai.OpenAIError as e:
        # 出现异常，匹配是否是 sdk 的错误
        mapped = map_openai_error(e)
        if isinstance(mapped, _BREAKER_TRIPPABLE):
            LLM_BREAKER.record_failure()
        raise mapped from e
    except asyncio.TimeoutError as e:
        mapped = map_openai_error(e)
        if isinstance(mapped, _BREAKER_TRIPPABLE):
            LLM_BREAKER.record_failure()
        raise mapped from e

    LLM_BREAKER.record_success()
    return result

async def ainvoke_with_context_recovery(llm, messages, *, trim_tokens: int | None = None):
    """ 调 LLM， 上下文超限时裁剪消息重试一次。
    - 仅对 LLMContextOverflowError 触发裁剪重试 (确定性错误， RetryPolicy 不会重试它)
    - 对其他错误 (429/5xx/timeout) 透传给 safe_ainvoke -> RetryPolicy 处理。
    - 只重试一次，避免循环。"""
    try:
        return await safe_ainvoke(llm, messages)
    except LLMContextOverflowError:
        budget = trim_tokens if trim_tokens is not None else settings.LLM_CONTEXT_TRIM_TOKENS
        trimmed = trim_messages(
            messages,
            max_tokens=budget,
            token_counter="approximate",   # 紧急降级用近似计数，避免再调一次 LLM 算 token
            strategy="last",               # 保留最近的消息
            include_system=True,           # 保留 SystemMessage（prompt 指令不能丢）
            start_on="human",              # 裁剪后从 HumanMessage 开始，顺带缓解工具调用配对断裂
        )
        logger.warning(
            "context_overflow_trimmed",
            original_count=len(messages),
            trimmed_count=len(trimmed),
            budget=budget,
        )
        return await safe_ainvoke(llm, trimmed)


# 节点级重试策略: 只重试“瞬时可恢复”的 LLM 异常， 确定性错误 (余额/鉴权/上下文超限) 立即失败
LLM_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    retry_on=(LLMRateLimitError, LLMTimeoutError, LLMServerError)
)
