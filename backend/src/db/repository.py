import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from src.db.model import Conversation, Message
from sqlalchemy import text

class ConversationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: str, title: str | None = None) -> Conversation:
        conv = Conversation(
            id=uuid.uuid4(),
            user_id=user_id,
            title=title
        )
        self.session.add(conv)
        await self.session.commit()
        await self.session.refresh(conv)
        return conv 

    async def get(self, user_id:str, conversation_id: uuid.UUID) -> Conversation | None:
        conv = await self.session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user_id:
            return None
        else:
            return conv

    async def list_by_user(self, user_id: str) -> list[Conversation]:
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(desc(Conversation.updated_at))
        )
        return list(result.scalars().all())

    async def update_title(self,user_id:str, conversation_id: uuid.UUID, title: str) -> None:
        conv = await self.session.get(Conversation, conversation_id)
        if conv and conv.user_id == user_id:
            conv.title = title
            await self.session.commit()


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, conversation_id: uuid.UUID, role: str, content: str, tool_calls: dict | None = None) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
        )
        self.session.add(msg)
        await self.session.commit()
        await self.session.refresh(msg)
        return msg

    async def get_history(self, conversation_id: uuid.UUID) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return list(result.scalars().all())

    async def count(self, conversation_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(Message).where(Message.conversation_id == conversation_id)
        )
        return len(list(result.scalars().all()))
    
    async def set_embedding(self, message_id: int, embedding: list[float]) -> None:
        await self.session.execute(
            text("UPDATE messages SET embedding = cast(:emb as vector) WHERE id = :mid"),
            {"emb": str(embedding), "mid": message_id}
        )
        await self.session.commit()
