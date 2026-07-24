class AgentError(Exception):
    """ 基类。 code 机器可读，message 用户安全中文， recoverable 控制前端是否提示重试"""
    code: str = "INTERNAL_ERROR"
    recoverable: bool = False
    http_status: int = 500 # 默认 500， 子类按语义覆盖

    def __init__(self, message: str = "", *, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_sse_frame(self, *, partial: bool = False) -> dict:
        return {
            "type": "error",
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
            "partial": partial
        }

    def to_http_response(self) -> dict:
        """ 对外 HTTP 响应体。与 to_sse_frame 同构(去掉 type/partial), 加上 HTTP 由status_code 表达"""
        return {"code": self.code, "message": self.message, "recoverable": self.recoverable}

class LLMError(AgentError):
    """ 大模型调用相关的错误的基类 """
    code = "LLM_ERROR"

# 429 限流， 可重试
class LLMRateLimitError(LLMError):
    code = "LLM_RATE_LIMIT"
    recoverable = True
    http_status = 503 # 上游限流 -> 服务暂不可用， 非客户端请求过多(非429)

# 超时， 可重试
class LLMTimeoutError(LLMError):
    code = "LLM_TIMEOUT"
    recoverable = True
    http_status = 504 # 网关超时

# 500/503 服务端错误， 可重试
class LLMServerError(LLMError):
    code = "LLM_SERVER"
    recoverable = True
    http_status = 502 # 上游 5xx -> Bad Gateway

# 400 上下文超限， 不重试，走剪裁降级
class LLMContextOverflowError(LLMError):
    code = "LLM_CONTEXT_OVERFLOW"
    recoverable = False
    http_status = 500 # 内部降级已处理(B4), 到 handler 说明降级也失败，算内部错误

# 402 余额不足，不重试，告警
class LLMBalanceError(LLMError):
    code = "LLM_BALANCE"
    recoverable = False
    http_status = 503 # 服务端资源耗尽，客户端可稍后重试(充值后)

# 401 鉴权失败，不重试
class LLMAuthError(LLMError):
    code = "LLM_AUTH"
    recoverable = False
    http_status = 500 # 服务端 LLM key 配置问题，不能给客户端 401 (那语义是客户端未鉴权)

class ToolError(AgentError):
    code = "TOOL_ERROR"
    http_status = 500

class InfraError(AgentError):
    code = "INFRA_ERROR"
    http_status = 503

class BusinessError(AgentError):
    code = "BIZ_ERROR"
    http_status = 400

class LLMCircuitOpenError(LLMError):
    """ 熔断器开启时快速失败。 recoverable=True 表示前端可提示用户稍后重试。"""
    code = "LLM_CIRCUIT_OPEN"
    recoverable = True
    http_status = 503 # 熔断中，稍后重试

class LLMRecursionLimitError(LLMError):
    """ 步骤超限异常 """
    code = "RECURSION_LIMIT_EXCEEDED"
    recoverable = True
    http_status = 500

def ensure_agent_error(exc: Exception) -> "AgentError":
    """ 把任意异常归一成为 AgentError。 已是 AgentError 的原样返回；其余包装为通用的内部错误。"""
    if isinstance(exc, AgentError):
        return exc

    if type(exc).__name__ == "GraphRecursionError":
        return LLMRecursionLimitError("系统执行步骤超限，请尝试简化您的问题以防止死循环", detail=str(exc))
    return AgentError("服务内部错误，请稍后重试", detail=str(exc))
