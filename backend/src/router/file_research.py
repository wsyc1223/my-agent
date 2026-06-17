import uuid
import json
import re
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.session import get_db
from src.utils.security import get_current_user
from src.schemas import ReportRequest
from src.db.model import User
from src.service.file_research import stream_research_session
from src.db.repository import ResearchSessionRepository, ResearchMessageRepository, FileReportRepository

router = APIRouter()

@router.post("/reports/stream")
async def stream_report(
        req: ReportRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_user)
):
    try:
        generator = stream_research_session(
            db=db,
            user_id=user.id,
            query=req.query,
            file_ids=req.file_ids,
            session_id=req.session_id
        )

        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/research/sessions")
async def list_research_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    try:
        repo = ResearchSessionRepository(db)
        sessions = await repo.list_by_user(user.id)
        return [
            {
                "id": str(s.id),
                "title": s.title or "新深度研究会话",
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in sessions
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/research/sessions/{session_id}")
async def get_research_session_details(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    try:
        session_repo = ResearchSessionRepository(db)
        sess = await session_repo.get(user.id, session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="Research session not found")

        message_repo = ResearchMessageRepository(db)
        messages = await message_repo.get_history(session_id)

        report_repo = FileReportRepository(db)
        report = await report_repo.get_latest_by_session(session_id)

        # Fetch user files to map file IDs to actual file names/types
        from src.db.repository import FileDocumentRepository
        file_repo = FileDocumentRepository(db)
        user_files = await file_repo.list_by_user(user.id)
        file_map = {
            str(f.id): {
                "name": f.filename,
                "type": f.filename.split('.')[-1] if '.' in f.filename else 'unknown'
            }
            for f in user_files
        }

        return {
            "id": str(sess.id),
            "title": sess.title or "新深度研究会话",
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "files": [
                        {
                            "id": fid,
                            "name": file_map.get(fid, {}).get("name", "未知文件"),
                            "type": file_map.get(fid, {}).get("type", "unknown")
                        }
                        for fid in (m.attached_file_ids or [])
                        if fid in file_map
                    ]
                }
                for m in messages
                if m.role in ("user", "assistant")
            ],
            "report": {
                "id": str(report.id),
                "report_md": report.report_md,
                "status": report.status,
                "error_message": report.error_message,
            } if report else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
