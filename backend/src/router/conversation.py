import uuid
from fastapi import APIRouter, HTTPException, Depends
from src.service.file_research import notifier_manager
from src.db.session import get_db
from src.utils.security import get_current_user
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.repository import ConversationRepository, MessageRepository
from src.schemas import MessageOut, ConversationOut
from src.db.model import User, FileReport
from fastapi.responses import StreamingResponse

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
            "task": {
                "id": m.associated_task_id,
                "task_type": m.associated_task.task_type,
                "status": m.associated_task.status,
                "referred_message_id": m.referred_message_id,
                "report_id": m.associated_task.file_report.id if m.associated_task.file_report else None,
                "error_message": m.associated_task.error_message
            } if m.associated_task else None
        }
        for m in msgs
        if m.role in ("user", "assistant", "subagent")
    ]

@router.get("/conversations/{conversation_id}/telemetry")
async def stream_telemetry(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """ 实时订阅异步子 Agent 的 SSE 推送网关"""
    user_id = user.id
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get(conversation_id=conversation_id, user_id=user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return StreamingResponse(
        notifier_manager.subscribe(str(conversation_id)),
        media_type="text/event-stream"
    )

@router.get("/reports/{report_id}")
async def get_report_detail(
        report_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_user)
):
    user_id = user.id

    report = await db.get(FileReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")

    if str(report.user_id) != str(user_id):
        raise HTTPException(status_code=403, detail="无权访问该报告")

    return {
        "id": str(report.id),
        "status": report.status,
        "report_md": report.report_md or "",
        "error_message": report.error_message,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None
    }

