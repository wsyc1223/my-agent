import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    """
    统一系统环境配置类(Pydantic v2 BaseSettings)
    自动读取 backend/.env 中的 变量， 并完成类型强制转换
    """

    # === 大模型 API 配置（自动校验类型）===
    DEEPSEEK_API_KEY: str = Field(..., description="DeepSeek API 秘钥")
    DEEPSEEK_BASE_URL: str = Field("https://api.deepseek.com", description="DeepSeek 服务地址")

    # === LLM 调用鲁棒性参数 ===
    LLM_TIMEOUT: float = Field(60.0, description="单次 LLM 调用超时 （秒）")
    LLM_MAX_ATTEMPTS: int = Field(2, description="LLM HTTP 层重试次数 （openai SDK 内置， 含首次共 attempts+1次）")
    LLM_CONTEXT_TRIM_TOKENS: int = Field(8000, description="上下文超限时裁剪到的 token 预算（留出输出空间）")
    LLM_BREAKER_FAILURE_THRESHOLD: int = Field(5, description="连续失败多少次熔断")
    LLM_BREAKER_RECOVERY_TIMEOUT: float = Field(30.0, description="熔断后冷却数秒，过后转半开")

    # === 研究任务整体超时 ===
    RESEARCH_TASK_TIMEOUT: float = 300.0

    # === 通义千问 API 配置 ===
    QWEN_BASE_URL: str | None = Field(None, alias="QWEN-BASE-URL")
    QWEN_API_KEY: str | None = Field(None, alias="QWEN-API-KEY")

    # === 数据库配置 ===
    DATABASE_URL: str = Field(..., description="PostgreSQL 异步连接串")
    DATABASE_URL_PSYCOPG: str = Field(..., description="PostgreSQL 传统同步连接串")

    # === 换存 ===
    REDIS_URL: str = Field("redis://localhost:6379/0", description="Redis 连接地址")

    # === 安全配置 ===
    JWT_SECRET_KEY: str = Field(..., description="JWT 加密秘钥")

    # === 可观测性配置（langfuse）===
    LANGFUSE_PUBLIC_KEY: str = Field(..., description="Langfuse 公钥")
    LANGFUSE_SECRET_KEY: str = Field(..., description="Langfuse 私钥")
    LANGFUSE_BASE_URL: str = Field("https://jp.cloud.langfuse.com", description="Langfuse 服务端地址")

    TAVILY_API_KEY: str = Field(..., description="Tavily 搜索引擎 API 秘钥")

    # === 限流配置 ===
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_AUTH: str = "10/minute"
    RATE_LIMIT_CHAT: str = "20/minute"
    RATE_LIMIT_UPLOAD: str = "5/minute"

    # 指定加载 .env 文件的配置
    model_config = SettingsConfigDict(
        # 指向 backend/.env
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore" # 忽略多余的环境变量防止报错
    )

settings = Settings()
