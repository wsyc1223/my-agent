from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func, BigInteger, UniqueConstraint, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
from pgvector.sqlalchemy import Vector
import uuid

def generator_name():
    return f"用户_{uuid.uuid4().hex[:8].upper()}"

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, default=generator_name)
    avatar_url = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    credentials = relationship("UserCredential", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")

class UserCredential(Base):
    __tablename__ = "user_credentials"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    provider = Column(String(20), nullable=False)
    identifier = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    user = relationship("User", back_populates="credentials")

    __table_args__ = (
        UniqueConstraint('provider', 'identifier', name='uq_provider_identifier'),
        UniqueConstraint('user_id', 'provider', name='uq_user_id_provider')
    )

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(256), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    global_memory = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")
    reports = relationship("FileReport", back_populates="conversation")
    tasks = relationship("AsyncTask", back_populates="conversation", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"
    id = Column(BigInteger, primary_key = True, autoincrement=True)
    conversation_id = Column(UUID, ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=True)
    tool_calls = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    embedding = Column(Vector(768), nullable=True)

    # 如果此次消息触发了后台子任务，则需要添加关联的消息id和任务id
    referred_message_id = Column(BigInteger, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    associated_task_id = Column(UUID, ForeignKey("async_tasks.id", ondelete="SET NULL"), nullable=True)

    conversation = relationship("Conversation", back_populates="messages")
    associated_task = relationship("AsyncTask", foreign_keys=[associated_task_id])


class FileDocument(Base):
    __tablename__ = "file_documents"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    # 强制关联用户 ID， 实现多租户隔离
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=True)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="indexed")
    error_message = Column(Text, nullable=True)
    full_content = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User")
    # 联级删除：文件删除后，其所有切块自动在数据库里面删除
    chunks = relationship("FileChunk", back_populates="document", cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint('user_id', 'sha256', name='_user_sha256_uc'),
    )

class FileChunk(Base):
    __tablename__ = "file_chunks"

    id = Column(BigInteger, primary_key=True, autoincrement=True) 
    document_id = Column(UUID, ForeignKey("file_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(BigInteger, nullable=False)
    content = Column(Text, nullable=False)
    token_estimate = Column(BigInteger, nullable=False, default=0)
    start_line = Column(BigInteger, nullable=True)
    end_line = Column(BigInteger, nullable=True)
    embedding = Column(Vector(768), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    document = relationship("FileDocument", back_populates="chunks")


class AsyncTask(Base):
    """ 通用任务控制表 """
    __tablename__ = "async_tasks"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(UUID, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True) # 关联的会话id
    trigger_message_id = Column(BigInteger, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True) # 关联的消息id

    task_type = Column(String(50), nullable=False, default="deep_research")
    status = Column(String(20), nullable=False, default="running")
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    conversation = relationship("Conversation", back_populates="tasks")
    trigger_message = relationship("Message", foreign_keys=[trigger_message_id])

    # 和具体结果一对一关联
    file_report = relationship("FileReport", back_populates="task", uselist=False, cascade="all, delete-orphan")

class FileReport(Base):
    __tablename__ = "file_reports"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    trigger_message_id = Column(BigInteger, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    conversation_id = Column(UUID, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    task_id = Column(UUID, ForeignKey("async_tasks.id", ondelete="SET NULL"), nullable=True, unique=True, index=True)

    is_saved = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="running") # running, success, error
    report_md = Column(Text, nullable=True) # 报告内容
    selected_chunk_ids = Column(JSONB, nullable=True) # 记录引用的 chunk ID 列表， 用于追溯来源
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    conversation = relationship("Conversation", back_populates="reports")
    task = relationship("AsyncTask", back_populates="file_report")

class AuditLog(Base):
    """ 安全审计日志表 """
    __tablename__ = "audit_logs"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    conversation_id = Column(UUID, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)

    action = Column(String(50), nullable=False, index=True)
    resource = Column(String(50), nullable=False)
    resource_id = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False, default=True)
    detail = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)

    user = relationship("User")
    conversation = relationship("Conversation")
