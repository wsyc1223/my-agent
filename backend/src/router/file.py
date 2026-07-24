import uuid
import os
from pathlib import Path
import tempfile
from fastapi import APIRouter, Depends, UploadFile, BackgroundTasks, HTTPException, File, Request
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.session import get_db
from src.utils.security import get_current_user
from src.db.model import User
from src.service.file_research import handle_file_upload
from src.config import settings
from src.limiter import limiter

router = APIRouter(prefix="/file", tags=["file"])

@router.post("/upload")
@limiter.limit(settings.RATE_LIMIT_UPLOAD)
async def upload_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """ 处理文件上传 """
    try:
        # 新建一个空的临时文件
        suffix = Path(file.filename).suffix.lower()
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)

        CHUNK_SIZE = 1024 * 1024
        total_size = 0

        while True:
            chunk = await file.read(CHUNK_SIZE)

            if not chunk:
                break

            total_size += len(chunk)
            if total_size > 5 * 1024 * 1024:
                temp_file.close()
                if os.path.exists(temp_file.name):
                    os.remove(temp_file.name)
                raise ValueError("文件大小超过了5M限制")

            temp_file.write(chunk)
        temp_file.close()

        # 2. 转换成为字符串
        res = await handle_file_upload(
            user_id=str(user.id), 
            filename=file.filename,
            file_path=temp_file.name, 
            db=db, 
            background_tasks=background_tasks)

        from src.audit.logger import audit_log
        await audit_log(
            action="upload_file",
            resource="file",
            resource_id=res.get("document_id"),
            user_id=user.id,
            success=True,
            detail={"filename": file.filename, "size_bytes": total_size}
        )
        return res
    except Exception as e:
        if 'temp_file' in locals() and os.path.exists(temp_file.name):
            os.remove(temp_file.name)
        from src.audit.logger import audit_log
        await audit_log(
            action="upload_file",
            resource="file",
            user_id=user.id if 'user' in locals() else None,
            success=False,
            detail={"filename": getattr(file, "filename", None), "error": str(e)}
        )
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{document_id}")
async def get_file(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """ 获取文件信息 """
    try:
        from src.db.model import FileDocument
        doc = await db.get(FileDocument, document_id)
        if not doc or str(doc.user_id) != str(user.id):
            raise HTTPException(status_code=404, detail="Document not found")
        return {
            "id": str(doc.id),
            "filename": doc.filename,
            "full_content": doc.full_content or "",
            "size_bytes": doc.size_bytes,
            "status": doc.status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
