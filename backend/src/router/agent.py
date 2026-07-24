from fastapi import APIRouter, HTTPException, Depends, Request
from src.schemas import ChatRequest, ResumeRequest
from src.service.agent import chat_stream, resume 
from src.db.session import get_db
from src.utils.security import get_current_user
from src.db.model import User
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.repository import ConversationRepository
from src.config import settings
from src.limiter import limiter
import uuid

router = APIRouter()

@router.post("/agent/chat/stream")
@limiter.limit(settings.RATE_LIMIT_CHAT)
async def stream(request: Request, req: ChatRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return await chat_stream(message=req.message, user_id=user.id, db=db, conversation_id=req.conversation_id, global_memory=req.global_memory)
    except Exception as e:
        raise HTTPException(status_code = 500, detail = str(e))

@router.post("/agent/resume")
@limiter.limit(settings.RATE_LIMIT_CHAT)
async def resume_route(request: Request, req: ResumeRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)): 
    try:
        # 查验被 resume 的会话是不是当前用户的会话
        conv_repo = ConversationRepository(db)
        conv = await conv_repo.get(user.id, req.conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话未找到，无权操作此会话")

        return await resume(thread_id=req.thread_id, approved=req.approved, db=db, conversation_id=req.conversation_id, user_id=user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code = 500, detail = str(e)) 
