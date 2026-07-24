from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional

class ChatRequest(BaseModel):
    """ 普通聊天请求 """
    message: str
    conversation_id: UUID | None
    global_memory: Optional[bool] = False

class ConversationOut(BaseModel):
    """ 展示用户会话列表 """
    id: str
    title: str
    created_at: str | None

class TaskMetaDataOut(BaseModel):
    """ 任务元数据类 """
    id: UUID
    task_type: str
    status: str
    referred_message_id: Optional[int] = None
    report_id: Optional[UUID] = None
    error_message: Optional[str] = None

class MessageOut(BaseModel):
    """ 展示用户消息列表 """
    role: str
    content: str
    created_at: str | None
    task: TaskMetaDataOut | None

class ErrorResponse(BaseModel):
    detail: str
    error_code: int

class ResumeRequest(BaseModel):
    """ 断点重连请求 """
    thread_id: UUID
    approved: bool
    conversation_id: UUID

class RegisterRequest(BaseModel):
    """ 注册请求 """
    email: str
    password: str
    name: str | None = None

class LoginRequest(BaseModel):
    """ 登录请求 """
    email: str
    password: str

class AuthResponse(BaseModel):
    """ 用户凭证 """
    access_token: str
    token_type: str
    user_id: UUID
    name: str

class ReportRequest(BaseModel):
    """ 上传报告请求 """
    query: str = Field(..., min_length=2, max_length=2000)
    file_ids: list[UUID] | None = None
    session_id: UUID | None = None

class QueryRewriteOutput(BaseModel):
    standalone_query: str = Field(description="结合历史对话消解代词、补充语境后的独立单句查询")
    sub_queries: list[str] = Field(description="拆解出的2~3个原子级搜索子问题，用于提高召回覆盖率")
    need_retrieval: bool = Field(description="判断该提问是否需要检索文档知识库（闲聊或非文档问题为False）")

