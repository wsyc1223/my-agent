from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func, BigInteger, UniqueConstraint
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

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"
    id = Column(BigInteger, primary_key = True, autoincrement=True)
    conversation_id = Column(UUID, ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    tool_calls = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    embedding = Column(Vector(768), nullable=True)

    conversation = relationship("Conversation", back_populates="messages")
