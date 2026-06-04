from fastapi import APIRouter, HTTPException, Depends
from src.schemas import ChatRequest, ResumeRequest
from src.service.agent import chat_stream, resume 
from src.db.session import get_db
from src.utils.security import get_current_user
from src.db.model import User
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.repository import ConversationRepository
import uuid

router = APIRouter()

@router.post("/agent/chat/stream")
async def stream(req: ChatRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return await chat_stream(req.message, user.id, db, req.conversation_id)
    except Exception as e:
        raise HTTPException(status_code = 500, detail = str(e))

@router.post("/agent/resume")
async def resume_route(req: ResumeRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)): 
    try:
        # 查验被 resume 的会话是不是当前用户的会话
        conv_repo = ConversationRepository(db)
        conv = await conv_repo.get(user.id, req.conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话未找到，无权操作此会话")

        return await resume(req.thread_id, req.approved, db, req.conversation_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code = 500, detail = str(e)) 
