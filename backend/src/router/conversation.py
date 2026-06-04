import uuid
from fastapi import APIRouter, HTTPException, Depends
from src.db.session import get_db
from src.utils.security import get_current_user
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.repository import ConversationRepository, MessageRepository
from src.schemas import MessageOut, ConversationOut
from src.db.model import User

router = APIRouter()


# 展示用户会话列表
@router.get("/conversations", response_model = list[ConversationOut])
async def list_conversations(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    user_id = user.id
    repo = ConversationRepository(db)
    convs = await repo.list_by_user(user_id)
    return [
        {
            "id": str(c.id),
            "title": c.title or "新对话",
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in convs
    ]


# 展示会话聊天记录
@router.get("/conversations/{conversation_id}/messages", response_model = list[MessageOut])
async def get_messages(conversation_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    user_id = user.id
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get(user_id, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_repo = MessageRepository(db)
    msgs = await msg_repo.get_history(conversation_id)
    return [
        {
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs
        if m.role in ("user", "assistant")
    ]
