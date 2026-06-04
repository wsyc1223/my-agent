from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional

class ChatRequest(BaseModel):
    message: str
    conversation_id: UUID | None

class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str | None

class MessageOut(BaseModel):
    role: str
    content: str
    created_at: str | None

class ErrorResponse(BaseModel):
    detail: str
    error_code: int

class ResumeRequest(BaseModel):
    thread_id: UUID
    approved: bool
    conversation_id: UUID

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str | None = None

class LoginRequest(BaseModel):
    email: str
    password: str

class AuthResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: UUID
    name: str
