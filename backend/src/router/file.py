import uuid
from fastapi import APIRouter, Depends, UploadFile, BackgroundTasks, HTTPException, File
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.session import get_db
from src.utils.security import get_current_user
from src.db.model import User
from src.service.file_research import handle_file_upload

router = APIRouter(prefix="/file", tags=["file"])

@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """ 处理文件上传 """
    try:
        # 1. 从 fastapi 接收的文件对象中读取二进制字节流
        file_data = await file.read()

        # 2. 转换成为字符串
        res = await handle_file_upload(
            user_id=str(user.id), 
            filename=file.filename, 
            file_data=file_data, 
            db=db, 
            background_tasks=background_tasks)
        return res
    except Exception as e:
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
